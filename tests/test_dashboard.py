"""Testes do dashboard Streamlit (Etapa 8)."""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from config.settings import Settings
from web.components.logs_viewer import read_shadow_logs
from web.components.market_watch import (
    WATCH_SYMBOLS,
    is_tradable_symbol,
)
from web.dashboard import (
    CHART_BARS,
    WATCH_BARS,
    account_metrics,
    compute_features,
    fetch_market_data,
    fetch_watch_data,
    get_mode_banner,
    get_open_positions_table,
    get_recent_orders_table,
    get_signals,
)


# --- Teste 1: dashboard importa sem erro -----------------------------------


def test_dashboard_imports_without_error():
    """Teste 1: o módulo do dashboard e seus componentes importam sem erro."""
    import web.dashboard
    import web.components.chart_plotly
    import web.components.logs_viewer
    import web.components.signals_panel

    assert hasattr(web.dashboard, "main")
    assert callable(web.dashboard.main)
    assert hasattr(web.components.chart_plotly, "build_figure")
    assert hasattr(web.components.signals_panel, "render_signals")
    assert hasattr(web.components.logs_viewer, "read_shadow_logs")


# --- Teste 2: fetch de dados retorna DataFrame válido (mock MT5) -----------


def test_fetch_market_data_returns_dataframe_with_mock():
    """Teste 2: fetch_market_data retorna DataFrame válido com MT5 mockado."""
    n = 50
    df_mock = pd.DataFrame(
        {
            "time": pd.date_range("2024-01-01", periods=n, freq="5min"),
            "open": np.linspace(2000.0, 2050.0, n),
            "high": np.linspace(2001.0, 2051.0, n),
            "low": np.linspace(1999.0, 2049.0, n),
            "close": np.linspace(2000.5, 2050.5, n),
            "tick_volume": np.full(n, 100),
        }
    )

    mock_md = MagicMock()
    mock_md.fetch_ohlcv.return_value = df_mock

    result = fetch_market_data(mock_md, "XAUUSD-VIP", n_bars=n)

    assert isinstance(result, pd.DataFrame)
    assert not result.empty
    assert len(result) == n
    for col in ("time", "open", "high", "low", "close"):
        assert col in result.columns
    assert result["close"].iloc[-1] > result["close"].iloc[0]

    # Symbol/timeframe/n_bars repassados corretamente
    mock_md.fetch_ohlcv.assert_called_once_with(
        symbol="XAUUSD-VIP", timeframe="M5", n_bars=n
    )


def test_fetch_market_data_handles_failure():
    """Teste 2b: exceção do MT5 retorna DataFrame vazio em vez de propagar."""
    mock_md = MagicMock()
    mock_md.fetch_ohlcv.side_effect = RuntimeError("terminal fechado")

    result = fetch_market_data(mock_md, "XAUUSD-VIP")

    assert isinstance(result, pd.DataFrame)
    assert result.empty


# --- Teste 3: banner mostra SIMULAÇÃO quando dry_run=True ------------------


def test_banner_shows_simulation_when_dry_run_true():
    """Teste 3: com dry_run=True o banner indica MODO SIMULAÇÃO."""
    settings = Settings(DRY_RUN=True)
    kind, message = get_mode_banner(settings)

    assert settings.dry_run is True
    assert kind == "simulation"
    assert "SIMULAÇÃO" in message
    assert "DRY-RUN" in message
    assert "MODO REAL" not in message


# --- Teste 4: banner mostra MODO REAL quando dry_run=False -----------------


def test_banner_shows_real_when_dry_run_false():
    """Teste 4: com dry_run=False o banner indica MODO REAL.

    Usa o alias ``DRY_RUN``: pydantic-settings ignora o nome do campo quando há
    alias declarado, então ``Settings(dry_run=False)`` seria silenciosamente
    descartado por ``extra="ignore"``.
    """
    settings = Settings(DRY_RUN=False)
    kind, message = get_mode_banner(settings)

    assert settings.dry_run is False
    assert kind == "real"
    assert "MODO REAL" in message
    assert "SIMULAÇÃO" not in message


def test_dry_run_is_true_in_project_env():
    """Segurança: o .env do projeto tem dry_run ligado."""
    settings = Settings()
    assert settings.dry_run is True


# --- Teste 5: leitura de shadow_*.jsonl retorna vazio se não existe -------


def test_read_shadow_logs_returns_empty_when_missing(tmp_path):
    """Teste 5a: diretório de logs inexistente retorna lista vazia."""
    assert read_shadow_logs(tmp_path / "nao_existe") == []


def test_read_shadow_logs_returns_empty_when_dir_exists_but_empty(tmp_path):
    """Teste 5b: diretório existente sem arquivos JSONL retorna lista vazia."""
    assert read_shadow_logs(tmp_path) == []


def test_read_shadow_logs_empty_file_returns_empty(tmp_path):
    """Teste 5c: arquivo JSONL existente mas vazio retorna lista vazia."""
    (tmp_path / "shadow_20260926.jsonl").write_text("", encoding="utf-8")
    assert read_shadow_logs(tmp_path) == []


def test_read_shadow_logs_parses_records_and_filters(tmp_path):
    """Teste 5d: registros são lidos, filtrados por modelo e ordenados por data."""
    ts_old = (datetime.now() - timedelta(hours=2)).isoformat()
    ts_new = datetime.now().isoformat()

    (tmp_path / "shadow_20260926.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": ts_old,
                        "model": "WCE2014",
                        "signal": "BUY",
                        "confidence": 0.7,
                        "would_have_entered": True,
                    }
                ),
                json.dumps(
                    {
                        "timestamp": ts_new,
                        "model": "Head3_ISOM",
                        "signal": "SELL",
                        "confidence": 0.6,
                        "would_have_entered": False,
                    }
                ),
                "",  # linha em branco não deve quebrar o parser
                "{json inválido",  # linha corrompida é ignorada
            ]
        ),
        encoding="utf-8",
    )

    todos = read_shadow_logs(tmp_path)
    assert len(todos) == 2
    # mais recente primeiro
    assert todos[0]["model"] == "Head3_ISOM"

    somente_wce = read_shadow_logs(tmp_path, model_filter="WCE2014")
    assert len(somente_wce) == 1
    assert somente_wce[0]["signal"] == "BUY"

    # limit respeitado
    assert len(read_shadow_logs(tmp_path, limit=1)) == 1


# --- Testes extras de segurança e integração -------------------------------


def test_dashboard_has_no_order_send_button():
    """Segurança: o dashboard não pode ter botão de envio de ordem."""
    source = Path("web/dashboard.py").read_text(encoding="utf-8")

    for forbidden in ("order_send", "execute_signal", "modify_sl", "close_partial"):
        assert forbidden not in source, f"dashboard não deve chamar {forbidden}"


def test_positions_filtered_by_magic_number():
    """Posições de outros robôs (magic != 20250924) não aparecem."""
    settings = Settings()
    connector = MagicMock()
    connector.is_connected.return_value = True

    def _pos(ticket, magic):
        p = MagicMock()
        p.ticket = ticket
        p.type = 0
        p.volume = 0.01
        p.price_open = 2000.0
        p.price_current = 2010.0
        p.profit = 100.0
        p.sl = 0.0
        p.tp = 0.0
        p.magic = magic
        return p

    fake = MagicMock()
    fake.positions_get.return_value = [
        _pos(1, settings.magic_number),  # nosso robô
        _pos(2, 12345),  # manual / outro robô
    ]

    with patch.dict(sys.modules, {"MetaTrader5": fake}):
        df = get_open_positions_table(connector, settings)

    assert len(df) == 1
    assert df["ticket"].iloc[0] == 1


def test_recent_orders_filtered_by_magic_number():
    """Ordens de outros robôs (magic != 20250924) não aparecem."""
    settings = Settings()
    connector = MagicMock()
    connector.is_connected.return_value = True

    def _order(ticket, magic, state):
        o = MagicMock()
        o.ticket = ticket
        o.type = 0
        o.magic = magic
        o.state = state
        o.volume_initial = 0.01
        o.volume_current = 0.0
        o.price_open = 2000.0
        o.sl = 1990.0
        o.tp = 2020.0
        o.time_setup = 1_700_000_000
        o.time_done = 1_700_000_500
        return o

    fake = MagicMock()
    fake.history_orders_get.return_value = [
        _order(1, settings.magic_number, 2),  # nosso robô, cancelada
        _order(2, 99999, 2),  # outro robô
    ]

    with patch.dict(sys.modules, {"MetaTrader5": fake}):
        df = get_recent_orders_table(connector, settings)

    assert len(df) == 1
    assert df["ticket"].iloc[0] == 1
    assert df["state"].iloc[0] == "cancelada"


def test_recent_orders_empty_when_disconnected():
    """Desconectado do MT5 retorna tabela vazia, sem levantar."""
    settings = Settings()
    connector = MagicMock()
    connector.is_connected.return_value = False

    assert get_recent_orders_table(connector, settings).empty


def test_recent_orders_respects_limit():
    """O limite de linhas é respeitado (últimas ordens)."""
    settings = Settings()
    connector = MagicMock()
    connector.is_connected.return_value = True

    def _order(ticket):
        o = MagicMock()
        o.ticket = ticket
        o.type = 0
        o.magic = settings.magic_number
        o.state = 1
        o.volume_initial = 0.01
        o.volume_current = 0.01
        o.price_open = 2000.0
        o.sl = 0.0
        o.tp = 0.0
        o.time_setup = ticket
        o.time_done = ticket
        return o

    fake = MagicMock()
    fake.history_orders_get.return_value = [_order(i) for i in range(25)]

    with patch.dict(sys.modules, {"MetaTrader5": fake}):
        df = get_recent_orders_table(connector, settings, limit=5)

    assert len(df) == 5
    assert df["ticket"].iloc[-1] == 24


def test_compute_features_returns_none_below_minimum_bars():
    """FeatureEngineer não é chamado com menos de 200 barras."""
    df = pd.DataFrame(
        {
            "time": pd.date_range("2024-01-01", periods=10, freq="5min"),
            "open": np.full(10, 2000.0),
            "high": np.full(10, 2001.0),
            "low": np.full(10, 1999.0),
            "close": np.full(10, 2000.0),
            "tick_volume": np.full(10, 100),
        }
    )
    assert compute_features(df) is None


def test_account_metrics_defaults():
    """account_metrics tolera None e chaves ausentes."""
    assert account_metrics(None)["balance"] == 0.0

    metrics = account_metrics({"balance": 1000.0, "equity": 1010.0, "profit": 10.0})
    assert metrics["balance"] == 1000.0
    assert metrics["equity"] == 1010.0
    assert metrics["profit"] == 10.0
    assert metrics["currency"] == "USD"


def test_add_indicators_creates_ema_and_bb():
    """As três overlays (EMA 9, EMA 21, BB 20/2.0) são calculadas."""
    from web.components.chart_plotly import add_indicators

    n = 60
    df = pd.DataFrame(
        {
            "time": pd.date_range("2024-01-01", periods=n, freq="5min"),
            "close": np.linspace(2000.0, 2100.0, n),
        }
    )
    out = add_indicators(df)

    for col in ("ema9", "ema21", "bb_upper", "bb_lower"):
        assert col in out.columns
        assert out[col].notna().any()

    assert out["bb_upper"].iloc[-1] > out["bb_lower"].iloc[-1]


def test_build_figure_uses_single_y_axis():
    """Regra dataviz: nunca dois eixos Y de escalas diferentes."""
    from web.components.chart_plotly import build_figure

    n = 30
    df = pd.DataFrame(
        {
            "time": pd.date_range("2024-01-01", periods=n, freq="5min"),
            "open": np.full(n, 2000.0),
            "high": np.full(n, 2001.0),
            "low": np.full(n, 1999.0),
            "close": np.full(n, 2000.0),
        }
    )
    figure = build_figure(df)

    # Nenhum trace pode declarar eixo secundário (y2)
    assert all(trace.yaxis is None or trace.yaxis == "y" for trace in figure.data)
    assert len(figure.data) >= 3  # candles + 2 EMAs


# --- BTCUSD: widget de preço, zero trading --------------------------------


def test_v26_never_receives_btcusd():
    """REGRA 1: a estratégia V26 é chamada apenas com o símbolo de XAUUSD.

    `get_signals` recebe o símbolo da conta e não tem como ver BTCUSD —
    as estratégias são instanciadas dentro dela com `settings`, cujo
    `symbol_xau` é a única fonte. Este teste fixa esse contrato.
    """
    settings = Settings()
    assert settings.symbol_xau == "XAUUSD-VIP"
    assert not settings.symbol_xau.upper().startswith("BTCUSD")

    captured: list[str] = []

    class _Spy:
        def __init__(self, s):
            captured.append(s.symbol_xau)

        def signal(self, *a, **kw):
            return None

    with patch("web.dashboard.V26Strategy", _Spy), patch(
        "web.dashboard.WCE2014Strategy", _Spy
    ):
        get_signals(
            object(),
            settings,
            symbol=settings.symbol_xau,
        )

    assert captured == ["XAUUSD-VIP", "XAUUSD-VIP"]
    assert all("BTCUSD" not in s for s in captured)


def test_btcusd_is_not_tradable_by_executor_allowlist():
    """REGRA 1/3: BTCUSD está FORA da allowlist do Executor."""
    settings = Settings()

    assert is_tradable_symbol(settings, "XAUUSD-VIP") is True
    assert is_tradable_symbol(settings, "XAUUSD") is True
    assert is_tradable_symbol(settings, "BTCUSD") is False
    assert is_tradable_symbol(settings, "btcusd") is False

    # O portfolio só permite metais; nenhum símbolo de watch é executável.
    assert tuple(settings.allowed_symbols) == ("XAUUSD", "XAGUSD")
    assert all(
        is_tradable_symbol(settings, sym) is False for sym in WATCH_SYMBOLS
    )


def test_market_watch_module_never_imports_trading_or_logging():
    """REGRA 1/2/3: o módulo de watch não referencia estratégia, log ou executor.

    Varre o CÓDIGO EXECUTÁVEL (sem docstrings/comentários) para não bloquear a
    documentação que precisa nomear o que o módulo NÃO faz.
    """
    import ast

    source = Path("web/components/market_watch.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    # Nomes referenciados em código: imports, atributos, chamadas, nomes locais
    referenced: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                referenced.add(alias.name.split(".")[-1])
        elif isinstance(node, ast.Name):
            referenced.add(node.id)
        elif isinstance(node, ast.Attribute):
            referenced.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            referenced.add(node.value)

    for forbidden in (
        "V26Strategy",
        "WCE2014Strategy",
        "ShadowLogger",
        "log_signal",
        "Executor",
        "order_send",
        "StrategyRouter",
    ):
        assert forbidden not in referenced, (
            f"market_watch não deve referenciar {forbidden} em código executável"
        )


def test_fetch_watch_data_returns_dataframe_and_never_raises():
    """A busca do BTCUSD falha de forma graciosa (DataFrame vazio)."""
    mock_md = MagicMock()
    mock_md.fetch_ohlcv.side_effect = RuntimeError("símbolo inexistente")
    assert fetch_watch_data(mock_md, "BTCUSD").empty

    ok = pd.DataFrame(
        {
            "time": pd.date_range("2024-01-01", periods=WATCH_BARS, freq="5min"),
            "open": np.full(WATCH_BARS, 60000.0),
            "high": np.full(WATCH_BARS, 60100.0),
            "low": np.full(WATCH_BARS, 59900.0),
            "close": np.full(WATCH_BARS, 60050.0),
        }
    )
    mock_md2 = MagicMock()
    mock_md2.fetch_ohlcv.return_value = ok
    result = fetch_watch_data(mock_md2, "BTCUSD")
    assert len(result) == WATCH_BARS
    mock_md2.fetch_ohlcv.assert_called_once_with(
        symbol="BTCUSD", timeframe="M5", n_bars=WATCH_BARS
    )


def test_dashboard_source_has_no_btcusd_trading_wiring():
    """REGRA 2/3: BTCUSD nunca é hardcoded nem ligado a sinal, log ou execução.

    Verifica o código executável via AST: o dashboard só pode obter o símbolo
    de watch por `WATCH_SYMBOLS`, nunca por literal.
    """
    import ast

    source = Path("web/dashboard.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    # Docstrings mencionam BTCUSD para documentar a exclusão; literais de
    # código, nunca. Identificadas por posição, não por prefixo de texto.
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                docstrings.add(doc)

    offending = [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and "BTCUSD" in n.value
        and n.value not in docstrings
    ]
    assert not offending, f"BTCUSD não deve ser literal em código: {offending}"

    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "WATCH_SYMBOLS" in names, "o dashboard deve iterar WATCH_SYMBOLS"
    assert "fetch_watch_data" in names
    assert "render_market_watch" in names

    # Nenhum acesso a shadow_logger no dashboard inteiro
    assert "ShadowLogger" not in names
    assert "log_signal" not in names
    assert "order_send" not in names


def test_dry_run_and_live_trading_untouched_after_btcusd():
    """REGRA 4: dry_run=True e live_trading=False permanecem."""
    settings = Settings()
    assert settings.dry_run is True
    assert settings.live_trading is False

    import config.settings as settings_module

    source = Path("config/settings.py").read_text(encoding="utf-8")
    assert 'dry_run: bool = Field(default=True, alias="DRY_RUN")' in source
    assert 'live_trading: bool = Field(default=False, alias="LIVE_TRADING")' in source
    assert settings_module.Settings is Settings
