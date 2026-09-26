"""Testes unitários para as estratégias operacionais do Hilberti (Etapa 5).

Cobre:
1. V26: Quadrantes de Hilbert e transições de fase.
2. V26: Head 2 Acumulação (energia Roofing, EIT flat, CycleMode).
3. V26: Head 2 Breakout Latch (rompimento com threshold ATR).
4. V26: Filtros de Cooldown e Spread dinâmico.
5. V26: Cálculo do Stop Loss estrutural inicial (ATR14 * min(2.0, T/10)).
6. V26: Gestão de Trade (Breakeven +500 pts, Parciais 30%+30%, Trailing AGC e Saída 180° de Fase).
7. WCE 2014: Modo Shadow em Q1 e Q3.
8. StrategyRouter: Orquestração unificada de execução e logs shadow.
"""

from __future__ import annotations

import numpy as np
import pytest

from ai.feature_engineer import DSPFeatures
from config.settings import Settings, get_settings
from strategy.pdf_strategies import (
    Position,
    SignalDecision,
    StrategyRouter,
    TradeAction,
    V26Strategy,
    WCE2014Strategy,
)


# ==============================================================================
# FIXTURES DE SUPORTE
# ==============================================================================


@pytest.fixture
def mock_dsp_features() -> DSPFeatures:
    """Gera um conjunto de DSPFeatures sintéticas para 50 barras."""
    n = 50
    return DSPFeatures(
        close_smooth=np.full(n, 2000.0, dtype=np.float64),
        detrender=np.zeros(n, dtype=np.float64),
        i1=np.full(n, 1.0, dtype=np.float64),
        q1=np.full(n, 1.0, dtype=np.float64),
        phase=np.full(n, 0.5, dtype=np.float64),
        amplitude=np.full(n, 2.0, dtype=np.float64),
        period_raw=np.full(n, 20.0, dtype=np.float64),
        period_smooth=np.full(n, 20.0, dtype=np.float64),
        roofing=np.full(n, 0.05, dtype=np.float64),
        eit=np.full(n, 2000.0, dtype=np.float64),
        eit_flat=np.ones(n, dtype=np.int32),
        ebsw_sine=np.full(n, 0.90, dtype=np.float64),
        ebsw_leadsine=np.full(n, 0.40, dtype=np.float64),
        cycle_mode=np.ones(n, dtype=np.int32),
        amplitude_norm=np.ones(n, dtype=np.float64),
        atr14=np.full(n, 5.0, dtype=np.float64),
    )


# ==============================================================================
# TESTES DO MOTOR V26
# ==============================================================================


def test_v26_quadrant_detection():
    """Valida a classificação dos 4 quadrantes analíticos de Hilbert."""
    strategy = V26Strategy()

    assert strategy.get_quadrant(1.0, 1.0) == 1  # Q1: I>0, Q>0
    assert strategy.get_quadrant(-1.0, 1.0) == 2  # Q2: I<0, Q>0
    assert strategy.get_quadrant(-1.0, -1.0) == 3  # Q3: I<0, Q<0
    assert strategy.get_quadrant(1.0, -1.0) == 4  # Q4: I>0, Q<0


def test_v26_accumulation_detection(mock_dsp_features):
    """Valida as 3 condições obrigatórias de acumulação lateral da Head 2."""
    strategy = V26Strategy()

    # Cenário Ideal: Baixa energia, EIT flat, CycleMode=1
    # Cria histórico de energia com média ~1.0 e valor atual 0.0025 (< 0.5 * 1.0)
    mock_dsp_features.roofing[:-1] = 1.0
    mock_dsp_features.roofing[-1] = 0.05  # 0.05^2 = 0.0025
    mock_dsp_features.eit[-2:] = 2000.0  # diff = 0 < 0.0005 * 2000 = 1.0
    mock_dsp_features.cycle_mode[-1] = 1

    ok, msg = strategy.check_accumulation(mock_dsp_features, current_price=2000.0)
    assert ok is True
    assert "Acumulação confirmada" in msg

    # Cenário de falha 1: CycleMode inativo (0)
    mock_dsp_features.cycle_mode[-1] = 0
    ok, msg = strategy.check_accumulation(mock_dsp_features, current_price=2000.0)
    assert ok is False
    assert "CycleMode inativo" in msg
    mock_dsp_features.cycle_mode[-1] = 1

    # Cenário de falha 2: EIT com inclinação excessiva (tendência forte)
    mock_dsp_features.eit[-1] = 2010.0  # diff = 10.0 > 1.0
    ok, msg = strategy.check_accumulation(mock_dsp_features, current_price=2000.0)
    assert ok is False
    assert "EIT com inclinação" in msg


def test_v26_breakout_latch(mock_dsp_features):
    """Valida o breakout de alta e baixa além da Instantaneous Trendline."""
    strategy = V26Strategy()
    mock_dsp_features.eit[-1] = 2000.0
    mock_dsp_features.atr14[-1] = 10.0  # threshold padrão = 0.5 * 10.0 = 5.0

    # Breakout de alta: preço > 2005.0
    ok_buy, msg_buy = strategy.check_breakout(mock_dsp_features, current_price=2006.0, direction="BUY")
    assert ok_buy is True
    assert "Breakout de alta" in msg_buy

    no_buy, _ = strategy.check_breakout(mock_dsp_features, current_price=2004.0, direction="BUY")
    assert no_buy is False

    # Breakout de baixa: preço < 1995.0
    ok_sell, msg_sell = strategy.check_breakout(mock_dsp_features, current_price=1994.0, direction="SELL")
    assert ok_sell is True
    assert "Breakout de baixa" in msg_sell

    no_sell, _ = strategy.check_breakout(mock_dsp_features, current_price=1996.0, direction="SELL")
    assert no_sell is False


def test_v26_spread_filter():
    """Valida a regra de spread máximo (XAU <= 0.10 ATR, XAG <= 0.20 ATR)."""
    strategy = V26Strategy()
    atr = 10.0

    # XAUUSD: limite = 0.10 * 10 = 1.0 pt
    ok_xau, _ = strategy.check_spread(symbol="XAUUSD", current_spread=0.8, atr14=atr)
    assert ok_xau is True

    fail_xau, msg = strategy.check_spread(symbol="XAUUSD", current_spread=1.2, atr14=atr)
    assert fail_xau is False
    assert "Spread excessivo" in msg

    # XAGUSD: limite = 0.20 * 10 = 2.0 pts
    ok_xag, _ = strategy.check_spread(symbol="XAGUSD", current_spread=1.8, atr14=atr)
    assert ok_xag is True

    fail_xag, _ = strategy.check_spread(symbol="XAGUSD", current_spread=2.2, atr14=atr)
    assert fail_xag is False


def test_v26_initial_structural_sl():
    """Valida a fórmula do SL estrutural: SL_pts = ATR14 * min(2.0, T / 10.0)."""
    strategy = V26Strategy()
    atr = 10.0

    # Caso 1: T = 15.0 -> min(2.0, 1.5) = 1.5 -> SL_pts = 15.0 pts
    sl_pts, sl_price_buy = strategy.calculate_initial_sl(
        current_price=2000.0,
        atr14=atr,
        period_smooth=15.0,
        direction="BUY",
    )
    assert np.isclose(sl_pts, 15.0)
    assert np.isclose(sl_price_buy, 1985.0)

    # Caso 2: T = 30.0 -> min(2.0, 3.0) = 2.0 (cap) -> SL_pts = 20.0 pts
    sl_pts_sell, sl_price_sell = strategy.calculate_initial_sl(
        current_price=2000.0,
        atr14=atr,
        period_smooth=30.0,
        direction="SELL",
    )
    assert np.isclose(sl_pts_sell, 20.0)
    assert np.isclose(sl_price_sell, 2020.0)


def test_v26_buy_and_sell_signals(mock_dsp_features):
    """Valida geração completa de sinais BUY e SELL da V26."""
    strategy = V26Strategy()

    # Prepara setup de BUY:
    # 1. Transição Q4 -> Q1 (I1 > 0, Q1 cruza de - para +)
    mock_dsp_features.i1[-2] = 1.0
    mock_dsp_features.q1[-2] = -1.0  # Q4
    mock_dsp_features.i1[-1] = 1.0
    mock_dsp_features.q1[-1] = 1.0  # Q1
    # EBSW Sine cruza acima de LeadSine
    mock_dsp_features.ebsw_sine[-2] = 0.20
    mock_dsp_features.ebsw_leadsine[-2] = 0.50
    mock_dsp_features.ebsw_sine[-1] = 0.90
    mock_dsp_features.ebsw_leadsine[-1] = 0.40
    # Acumulação
    mock_dsp_features.roofing[:-1] = 1.0
    mock_dsp_features.roofing[-1] = 0.05
    mock_dsp_features.eit[-2:] = 2000.0
    mock_dsp_features.cycle_mode[-1] = 1
    mock_dsp_features.atr14[-1] = 10.0

    # Breakout de alta: preço 2010 > EIT 2000 + 5.0
    decision_buy = strategy.signal(
        features=mock_dsp_features,
        symbol="XAUUSD",
        current_price=2010.0,
        current_spread=0.5,
        bars_since_last_entry=5,
    )
    assert decision_buy.signal == "BUY"
    assert decision_buy.sl_points > 0.0
    assert decision_buy.initial_sl < 2010.0

    # Prepara setup de SELL:
    # Transição Q2 -> Q3
    mock_dsp_features.i1[-2] = -1.0
    mock_dsp_features.q1[-2] = 1.0  # Q2
    mock_dsp_features.i1[-1] = -1.0
    mock_dsp_features.q1[-1] = -1.0  # Q3
    # EBSW Sine cruza abaixo de LeadSine
    mock_dsp_features.ebsw_sine[-2] = 0.50
    mock_dsp_features.ebsw_leadsine[-2] = 0.20
    mock_dsp_features.ebsw_sine[-1] = -0.90
    mock_dsp_features.ebsw_leadsine[-1] = -0.40

    # Breakout de baixa: preço 1990 < EIT 2000 - 5.0
    decision_sell = strategy.signal(
        features=mock_dsp_features,
        symbol="XAUUSD",
        current_price=1990.0,
        current_spread=0.5,
        bars_since_last_entry=5,
    )
    assert decision_sell.signal == "SELL"
    assert decision_sell.sl_points > 0.0
    assert decision_sell.initial_sl > 1990.0


def test_v26_cooldown_rejection(mock_dsp_features):
    """Valida rejeição de sinal durante o cooldown (< 3 barras)."""
    strategy = V26Strategy()
    decision = strategy.signal(
        features=mock_dsp_features,
        symbol="XAUUSD",
        current_price=2010.0,
        bars_since_last_entry=2,  # < 3
    )
    assert decision.signal == "HOLD"
    assert any("Cooldown" in r for r in decision.reasons)


# ==============================================================================
# TESTES DE GESTÃO DE TRADE (SAÍDAS V26)
# ==============================================================================


def test_v26_trade_management_breakeven(mock_dsp_features):
    """Valida ativação do Breakeven ao atingir +500 pts de lucro."""
    strategy = V26Strategy()
    pos = Position(
        ticket=1001,
        symbol="XAUUSD",
        order_type="BUY",
        volume=1.0,
        open_price=2000.0,
        sl=1980.0,
    )

    # Preço sobe +550 pts (2550.0) -> Dispara Breakeven para open + 10 = 2010.0
    action = strategy.manage_open_trade(pos, mock_dsp_features, current_price=2550.0)
    assert action.action == "MODIFY_SL"
    assert np.isclose(action.new_sl, 2010.0)
    assert pos.be_done is True


def test_v26_trade_management_partials(mock_dsp_features):
    """Valida as parciais automáticas de 30% no alvo 1 e 30% no alvo 2."""
    strategy = V26Strategy()
    pos = Position(
        ticket=1002,
        symbol="XAUUSD",
        order_type="BUY",
        volume=1.0,
        open_price=2000.0,
        sl=2010.0,
        be_done=True,  # BE já executado
    )

    # Parcial 1: +500 pts -> Fecha 30% (0.30 lote)
    action_p1 = strategy.manage_open_trade(pos, mock_dsp_features, current_price=2500.0)
    assert action_p1.action == "PARTIAL_CLOSE"
    assert np.isclose(action_p1.volume_to_close, 0.30)
    assert pos.partial1_done is True

    # Parcial 2: +1000 pts -> Fecha mais 30% (0.30 lote)
    action_p2 = strategy.manage_open_trade(pos, mock_dsp_features, current_price=3000.0)
    assert action_p2.action == "PARTIAL_CLOSE"
    assert np.isclose(action_p2.volume_to_close, 0.30)
    assert pos.partial2_done is True


def test_v26_trade_management_trailing_and_phase_reversal(mock_dsp_features):
    """Valida o Trailing Stop Adaptativo e o aperto de stop na saída de 180° de fase."""
    strategy = V26Strategy()
    pos = Position(
        ticket=1003,
        symbol="XAUUSD",
        order_type="BUY",
        volume=0.40,
        open_price=2000.0,
        sl=2010.0,
        entry_phase=0.0,
        be_done=True,
        partial1_done=True,
        partial2_done=True,
    )

    mock_dsp_features.atr14[-1] = 20.0
    mock_dsp_features.amplitude_norm[-1] = 1.0
    mock_dsp_features.cycle_mode[-1] = 1  # strength = 1.0
    # TrailPoints normal = 1.0 * 20.0 * 1.0 = 20.0 pts

    # 1. Trailing normal com preço em 2100.0 -> SL sobe para 2100 - 20 = 2080.0
    mock_dsp_features.phase[-1] = 0.5  # delta = 0.5 rad (< pi)
    action_trail = strategy.manage_open_trade(pos, mock_dsp_features, current_price=2100.0)
    assert action_trail.action == "MODIFY_SL"
    assert np.isclose(action_trail.new_sl, 2080.0)
    assert np.isclose(pos.sl, 2080.0)

    # 2. Inversão de fase de 180° (pi radianos) -> TrailPoints reduz pela metade (10.0 pts)
    # Com preço em 2100.0, SL sobe para 2100 - 10 = 2090.0
    mock_dsp_features.phase[-1] = np.pi  # delta = pi radianos (180°)
    action_rev = strategy.manage_open_trade(pos, mock_dsp_features, current_price=2100.0)
    assert action_rev.action == "MODIFY_SL"
    assert np.isclose(action_rev.new_sl, 2090.0)


# ==============================================================================
# TESTES DO MOTOR WCE 2014 E ROUTER
# ==============================================================================


def test_wce2014_shadow_signals(mock_dsp_features):
    """WCE 2014: a entrada e a TRAVESSIA de quadrante, nao o nivel.

    ATUALIZADO em 2026-09-26 (ativacao do WCE como modelo primario).
    Este teste fixava o comportamento SHADOW antigo, que emitia BUY/SELL
    apenas por estar dentro de Q1/Q3. O PDF diz "whenever the signal CROSSES
    Quarter 1" — por nivel, o modelo reentra toda barra dentro do quadrante,
    o que o artigo nao descreve. As regras por travessia tem cobertura propria
    em `tests/test_wce.py`; aqui fica o contrato do alias `signal()`.
    """
    strategy = WCE2014Strategy()

    # Travessia Q4 -> Q1 -> BUY
    mock_dsp_features.i1[-2] = 2.0
    mock_dsp_features.q1[-2] = -3.0
    mock_dsp_features.i1[-1] = 2.0
    mock_dsp_features.q1[-1] = 3.0
    assert strategy.signal(mock_dsp_features) == "BUY"

    # Travessia Q2 -> Q3 -> SELL
    mock_dsp_features.i1[-2] = -2.0
    mock_dsp_features.q1[-2] = 3.0
    mock_dsp_features.i1[-1] = -2.0
    mock_dsp_features.q1[-1] = -3.0
    assert strategy.signal(mock_dsp_features) == "SELL"

    # Q2 / Q4 / staying em Q1 -> HOLD (nenhuma travessia de entrada)
    mock_dsp_features.i1[-2] = -2.0
    mock_dsp_features.q1[-2] = 3.0
    mock_dsp_features.i1[-1] = -2.0
    mock_dsp_features.q1[-1] = 3.0
    assert strategy.signal(mock_dsp_features) == "HOLD"


def test_strategy_router_integration(mock_dsp_features):
    """Valida que o StrategyRouter orquestra V26, WCE Shadow e ML Shadow."""
    router = StrategyRouter()

    # Setup para BUY
    mock_dsp_features.i1[-2] = 1.0
    mock_dsp_features.q1[-2] = -1.0
    mock_dsp_features.i1[-1] = 1.0
    mock_dsp_features.q1[-1] = 1.0
    mock_dsp_features.ebsw_sine[-2:] = [0.2, 0.9]
    mock_dsp_features.ebsw_leadsine[-2:] = [0.5, 0.4]
    mock_dsp_features.roofing[:-1] = 1.0
    mock_dsp_features.roofing[-1] = 0.05
    mock_dsp_features.eit[-2:] = 2000.0
    mock_dsp_features.cycle_mode[-1] = 1
    mock_dsp_features.atr14[-1] = 10.0

    shadow_ml_sample = {"head3_isom_regime": "High", "head4_gating_trend_weight": 0.82}

    decision = router.decide(
        features=mock_dsp_features,
        symbol="XAUUSD",
        current_price=2010.0,
        current_spread=0.5,
        bars_since_last_entry=5,
        shadow_ml=shadow_ml_sample,
    )

    assert decision["signal"] == "BUY"
    assert decision["execute"] is True
    assert decision["shadow_wce"] == "BUY"
    assert decision["shadow_ml"] == shadow_ml_sample
    assert decision["sl_points"] > 0.0
