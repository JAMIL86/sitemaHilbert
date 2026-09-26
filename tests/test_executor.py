"""Testes unitários e de segurança para o Executor MT5 (Etapa 6).

Cobre os 7 testes obrigatórios de travas de segurança:
1. dry_run=True -> NÃO chama mt5.order_send (simula execução segura).
2. volume=0 -> Aborta envio com erro de validação.
3. volume=999 (acima do teto de 0.10) -> Aborta envio com erro de validação.
4. SL a < 50 pontos do preço atual -> Aborta envio por violação de distância mínima.
5. Symbol incorreto (ex: EURUSD) -> Aborta envio (apenas XAUUSD/XAGUSD permitidos).
6. Stop Diário estourado (>= 3.0%) -> Circuit Breaker aborta novas ordens.
7. LIVE_TRADING=False + dry_run=False -> Não envia ordem real (modo protegido).

Testes complementares:
8. Dimensionamento dinâmico de lote com risco exato de 1.0% e teto em 0.10.
9. Modificação de Stop Loss (Breakeven/Trailing) em modo simulado.
10. Fechamento parcial de posição em modo simulado.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from config.settings import Settings
from core.executor import Executor
from core.mt5_connector import MT5Connector


@pytest.fixture
def base_settings() -> Settings:
    """Configuração padrão com modo seguro ativado."""
    return Settings(
        dry_run=True,
        live_trading=False,
        confirm_live=None,
        magic_number=20250924,
        risk_percent_per_trade=1.0,
        daily_stop_percent=3.0,
        max_volume=0.10,
        min_volume=0.01,
        min_sl_distance_pts=50.0,
        allowed_symbols=("XAUUSD", "XAGUSD"),
    )


@pytest.fixture
def mock_connector() -> MT5Connector:
    """Mock de MT5Connector conectado com saldo de 10.000 USD."""
    connector = MagicMock(spec=MT5Connector)
    connector.is_connected.return_value = True
    connector.get_account_info.return_value = {
        "login": 123456,
        "trade_mode": "DEMO",
        "balance": 10000.0,
        "equity": 10000.0,
        "currency": "USD",
        "company": "VT Markets",
    }
    return connector


# ==============================================================================
# 7 TESTES OBRIGATÓRIOS DA ETAPA 6
# ==============================================================================


def test_1_dry_run_true_does_not_call_order_send(base_settings: Settings, mock_connector: MT5Connector):
    """Teste 1: dry_run=True -> NÃO chama mt5.order_send, gera ticket simulado."""
    base_settings.dry_run = True
    base_settings.live_trading = False
    executor = Executor(connector=mock_connector, settings=base_settings)

    with patch("core.executor.mt5") as mock_mt5:
        result = executor.execute_signal(
            signal="BUY",
            symbol="XAUUSD",
            current_price=2000.0,
            sl_price=1900.0,  # 100 pts de distância (> 50 pts)
            sl_points=100.0,
            volume=0.05,
        )

        # Verifica que mt5.order_send NUNCA foi chamado
        mock_mt5.order_send.assert_not_called()

        assert result["status"] == "SIMULATED"
        assert result["ticket"] >= 100000
        assert result["signal"] == "BUY"
        assert result["volume"] == 0.05
        assert result["dry_run"] is True


def test_2_volume_zero_aborts(base_settings: Settings, mock_connector: MT5Connector):
    """Teste 2: volume=0 -> Aborta envio com erro de validação."""
    executor = Executor(connector=mock_connector, settings=base_settings)

    result = executor.execute_signal(
        signal="BUY",
        symbol="XAUUSD",
        current_price=2000.0,
        sl_price=1900.0,
        sl_points=100.0,
        volume=0.0,
    )

    assert result["status"] == "ABORTED"
    assert "Volume inválido" in result["reason"]


def test_3_volume_exceeding_max_aborts(base_settings: Settings, mock_connector: MT5Connector):
    """Teste 3: volume=999 (acima de max_volume=0.10) -> Aborta envio."""
    executor = Executor(connector=mock_connector, settings=base_settings)

    result = executor.execute_signal(
        signal="BUY",
        symbol="XAUUSD",
        current_price=2000.0,
        sl_price=1900.0,
        sl_points=100.0,
        volume=999.0,
    )

    assert result["status"] == "ABORTED"
    assert "Volume inválido" in result["reason"]


def test_4_sl_distance_less_than_50_pts_aborts(base_settings: Settings, mock_connector: MT5Connector):
    """Teste 4: SL a <50 pts do preço atual -> Aborta envio."""
    executor = Executor(connector=mock_connector, settings=base_settings)

    # Distância de 30 pts (< 50 pts mínimos)
    result = executor.execute_signal(
        signal="BUY",
        symbol="XAUUSD",
        current_price=2000.0,
        sl_price=1970.0,
        sl_points=30.0,
        volume=0.02,
    )

    assert result["status"] == "ABORTED"
    assert "Distância do SL" in result["reason"]
    assert "inferior ao mínimo" in result["reason"]


def test_5_invalid_symbol_aborts(base_settings: Settings, mock_connector: MT5Connector):
    """Teste 5: symbol não autorizado (ex: EURUSD) -> Aborta envio."""
    executor = Executor(connector=mock_connector, settings=base_settings)

    result = executor.execute_signal(
        signal="BUY",
        symbol="EURUSD",
        current_price=1.0850,
        sl_price=1.0750,
        sl_points=100.0,
        volume=0.01,
    )

    assert result["status"] == "ABORTED"
    assert "Símbolo inválido 'EURUSD'" in result["reason"]


def test_6_daily_stop_loss_hit_aborts(base_settings: Settings, mock_connector: MT5Connector):
    """Teste 6: Stop diário estourado (>= 3.0%) -> Circuit breaker bloqueia novas ordens."""
    executor = Executor(connector=mock_connector, settings=base_settings)

    # Simula que o executor detecta stop diário atingido
    with patch.object(executor, "daily_stop_hit", return_value=True):
        result = executor.execute_signal(
            signal="BUY",
            symbol="XAUUSD",
            current_price=2000.0,
            sl_price=1900.0,
            sl_points=100.0,
            volume=0.02,
        )

        assert result["status"] == "ABORTED"
        assert "Daily stop loss 3% reached" in result["reason"]


def test_7_live_trading_false_dry_run_false_does_not_send_real_order(
    base_settings: Settings, mock_connector: MT5Connector
):
    """Teste 7: LIVE_TRADING=False + dry_run=False -> Trava impede execução real."""
    base_settings.dry_run = False
    base_settings.live_trading = False
    executor = Executor(connector=mock_connector, settings=base_settings)

    assert executor.is_live_execution_armed() is False

    with patch("core.executor.mt5") as mock_mt5:
        result = executor.execute_signal(
            signal="SELL",
            symbol="XAUUSD",
            current_price=2000.0,
            sl_price=2100.0,
            sl_points=100.0,
            volume=0.04,
        )

        mock_mt5.order_send.assert_not_called()
        assert result["status"] == "SIMULATED"
        assert result["signal"] == "SELL"


# ==============================================================================
# TESTES COMPLEMENTARES DE RISCO E OPERAÇÕES
# ==============================================================================


def test_calculate_lot_size_exact_risk_and_cap(base_settings: Settings, mock_connector: MT5Connector):
    """Verifica dimensionamento de 1% com SL e cap institucional de 0.10 lote."""
    executor = Executor(connector=mock_connector, settings=base_settings)

    # Saldo = $10.000, 1% de risco = $100.
    # No XAUUSD (1 pt = $100 por lote):
    # SL = 50 pts -> Lote teórico = 100 / (50 * 100) = 0.02 lote
    lot_1 = executor.calculate_lot_size(sl_points=50.0, symbol="XAUUSD", account_balance=10000.0)
    assert lot_1 == 0.02

    # SL muito curto (10 pts) daria lote 0.10 (cap institucional de 0.10)
    lot_2 = executor.calculate_lot_size(sl_points=10.0, symbol="XAUUSD", account_balance=10000.0)
    assert lot_2 == 0.10

    # SL gigantesco (1000 pts) respeita o lote mínimo (0.01)
    lot_3 = executor.calculate_lot_size(sl_points=1000.0, symbol="XAUUSD", account_balance=10000.0)
    assert lot_3 == 0.01


def test_modify_sl_simulation(base_settings: Settings, mock_connector: MT5Connector):
    """Verifica modificação de SL em modo seguro."""
    executor = Executor(connector=mock_connector, settings=base_settings)

    res = executor.modify_sl(ticket=1001, new_sl=2010.0, symbol="XAUUSD")
    assert res["status"] == "SIMULATED"
    assert res["action"] == "MODIFY_SL"
    assert res["ticket"] == 1001
    assert res["new_sl"] == 2010.0


def test_close_partial_simulation(base_settings: Settings, mock_connector: MT5Connector):
    """Verifica fechamento parcial em modo seguro."""
    executor = Executor(connector=mock_connector, settings=base_settings)

    res = executor.close_partial(ticket=1001, volume_to_close=0.03, symbol="XAUUSD", order_type="BUY")
    assert res["status"] == "SIMULATED"
    assert res["action"] == "PARTIAL_CLOSE"
    assert res["volume_closed"] == 0.03
