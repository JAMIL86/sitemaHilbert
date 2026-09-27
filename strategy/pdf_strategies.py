"""Estratégias operacionais do Hilberti extraídas dos PDFs de especificação.

Modelos implementados:
1. V26 (Hilbert Cycle + Chimera SSM) — Motor de Execução Ativo:
   - Head 1 (CHilbertEngine): Ciclo, Fase e EBSW (Sine/LeadSine).
   - Head 2 (CHoloHilbert): Energia de Acumulação e Breakout Latch.
   - Head 3 (CISOMEngine): Shadow Mode na v1 (ML One-vs-Rest).
   - Head 4 (GatingLayer): Shadow Mode na v1 (SwiGLU Gating).
   - Gestão de Saída: Breakeven 500 pts, Parciais 30%+30%, Trailing AGC e Saída 180° de Fase.
   - SEM Take Profit fixo.

2. WCE 2014 (Hilbert Transform + ISOM Directional Changes) — Modo Sombra (Shadow):
   - Execução paralela sem envio de ordens ao MT5 para comparação de performance.

3. StrategyRouter:
   - Orquestrador de decisão que unifica V26, WCE Shadow e ML Shadow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional
import numpy as np
import pandas as pd
from loguru import logger

from ai.feature_engineer import DSPFeatures
from config.settings import Settings, get_settings

Signal = Literal["BUY", "SELL", "HOLD"]
TradeActionType = Literal["HOLD", "CLOSE", "PARTIAL_CLOSE", "MODIFY_SL"]


# ==============================================================================
# ESTRUTURAS DE DADOS DE GESTÃO DE TRADES E SINAIS
# ==============================================================================


@dataclass
class Position:
    """Representação em memória de uma posição aberta para a estratégia."""

    ticket: int
    symbol: str
    order_type: Literal["BUY", "SELL"]
    volume: float
    open_price: float
    sl: float
    tp: Optional[float] = None
    open_time: Optional[datetime] = None
    entry_phase: float = 0.0
    partial1_done: bool = False
    partial2_done: bool = False
    be_done: bool = False
    bars_held: int = 0
    highest_price: float = field(init=False)
    lowest_price: float = field(init=False)

    def __post_init__(self) -> None:
        self.highest_price = self.open_price
        self.lowest_price = self.open_price

    def update_price(self, current_price: float) -> None:
        """Atualiza preços extremos alcançados pela posição."""
        if current_price > self.highest_price:
            self.highest_price = current_price
        if current_price < self.lowest_price:
            self.lowest_price = current_price

    def get_profit_points(self, current_price: float) -> float:
        """Calcula o lucro flutuante em pontos (ou unidades de preço)."""
        if self.order_type == "BUY":
            return current_price - self.open_price
        else:
            return self.open_price - current_price


@dataclass
class TradeAction:
    """Instrução de gerenciamento de posição emitida pela estratégia."""

    action: TradeActionType
    volume_to_close: float = 0.0
    new_sl: Optional[float] = None
    new_tp: Optional[float] = None
    reason: str = ""


@dataclass
class SignalDecision:
    """Decisão estruturada emitida pelo motor de estratégia."""

    signal: Signal
    symbol: str
    price: float
    sl_points: float
    initial_sl: float
    # Take profit em PRECO e em PONTOS. 0.0 = sem take profit. Nenhum PDF do
    # projeto define TP fixo (V26: "SEM Take Profit fixo"; WCE 2014: nao
    # escreve nenhum), entao o default 0.0 mantem os dois motores inalterados
    # e so as variantes de pesquisa preenchem isto.
    tp_points: float = 0.0
    tp: float = 0.0
    reasons: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# ==============================================================================
# MOTOR V26 — PRECISION ACCUMULATION BREAKOUT (ACTIVE ENGINE)
# ==============================================================================


class V26Strategy:
    """Motor de execução operacional ativo baseado no modelo V26.

    Regras extraídas de: Hilbert_Chimera_Dashboard_V26.pdf
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def get_quadrant(self, i1: float, q1: float) -> int:
        """Identifica o quadrante no plano analítico I/Q de Hilbert.

        - Q1: I > 0, Q > 0 (Fase 0° a 90°)
        - Q2: I < 0, Q > 0 (Fase 90° a 180°)
        - Q3: I < 0, Q < 0 (Fase 180° a 270°)
        - Q4: I > 0, Q < 0 (Fase 270° a 360°)
        """
        if i1 >= 0.0 and q1 >= 0.0:
            return 1
        elif i1 < 0.0 and q1 >= 0.0:
            return 2
        elif i1 < 0.0 and q1 < 0.0:
            return 3
        else:
            return 4

    def check_accumulation(
        self,
        features: DSPFeatures,
        current_price: float,
    ) -> tuple[bool, str]:
        """Head 2 (CHoloHilbert): Valida acumulação lateral de baixa energia.

        Condições obrigatórias:
        1. Roofing_Energy < 0.5 * SMA(Roofing_Energy, N)
        2. |IT(t) - IT(t-1)| < 0.0005 * price (EIT flat)
        3. CycleMode == 1
        """
        n_bars = len(features.roofing)
        if n_bars < 5:
            return False, "Dados insuficientes para acumulação"

        # 1. Energia do Roofing
        roofing_energy = features.roofing**2
        window_n = self.settings.accumulation_energy_n or 20  # default 20 se None
        window_n = min(window_n, n_bars)

        energy_sma = float(np.mean(roofing_energy[-window_n:]))
        curr_energy = float(roofing_energy[-1])
        energy_factor = self.settings.accumulation_energy_factor  # 0.5

        energy_ok = curr_energy < (energy_factor * energy_sma) if energy_sma > 1e-8 else True

        # 2. Declive da Instantaneous Trendline (EIT)
        it_curr = float(features.eit[-1])
        it_prev = float(features.eit[-2])
        flat_threshold = self.settings.eit_flat_factor * current_price  # 0.0005 * price
        eit_ok = abs(it_curr - it_prev) < flat_threshold

        # 3. CycleMode
        cycle_ok = int(features.cycle_mode[-1]) == 1

        if energy_ok and eit_ok and cycle_ok:
            return True, "Acumulação confirmada (Baixa energia + EIT flat + CycleMode)"

        reasons = []
        if not energy_ok:
            reasons.append(f"Energia alta ({curr_energy:.4f} >= {energy_factor * energy_sma:.4f})")
        if not eit_ok:
            reasons.append(f"EIT com inclinação ({abs(it_curr - it_prev):.4f} >= {flat_threshold:.4f})")
        if not cycle_ok:
            reasons.append("CycleMode inativo")

        return False, "; ".join(reasons)

    def check_breakout(
        self,
        features: DSPFeatures,
        current_price: float,
        direction: Literal["BUY", "SELL"],
    ) -> tuple[bool, str]:
        """Head 2: Valida rompimento de alta energia além da Instantaneous Trendline.

        Condições:
        - BUY: Price > IT + threshold_atr
        - SELL: Price < IT - threshold_atr
        """
        it_curr = float(features.eit[-1])
        atr_curr = float(features.atr14[-1])

        # Se breakout_threshold_atr for None, usa fallback seguro de 0.5 * ATR14
        threshold = (
            self.settings.breakout_threshold_atr
            if self.settings.breakout_threshold_atr is not None
            else (0.5 * atr_curr)
        )

        if direction == "BUY":
            breakout_level = it_curr + threshold
            if current_price > breakout_level:
                return True, f"Breakout de alta ({current_price:.2f} > IT {it_curr:.2f} + {threshold:.2f})"
            return False, f"Abaixo do nível de breakout de alta ({current_price:.2f} <= {breakout_level:.2f})"
        else:
            breakout_level = it_curr - threshold
            if current_price < breakout_level:
                return True, f"Breakout de baixa ({current_price:.2f} < IT {it_curr:.2f} - {threshold:.2f})"
            return False, f"Acima do nível de breakout de baixa ({current_price:.2f} >= {breakout_level:.2f})"

    def check_spread(
        self,
        symbol: str,
        current_spread: Optional[float],
        atr14: float,
    ) -> tuple[bool, str]:
        """Valida se o spread atual está dentro dos limites operacionais seguros."""
        if current_spread is None:
            # Em dry-run ou ausência de spread dinâmico, assume liberado
            return True, "Spread não informado (assumindo liberado em dry-run)"

        is_xau = "XAU" in symbol.upper()
        is_xag = "XAG" in symbol.upper()

        if is_xau:
            factor = self.settings.max_spread_atr_factor_xau  # 0.10
        elif is_xag:
            factor = self.settings.max_spread_atr_factor_xag  # 0.20
        else:
            factor = self.settings.max_spread_atr_factor_default  # 0.15

        max_allowed_spread = factor * atr14
        if current_spread <= max_allowed_spread:
            return True, f"Spread OK ({current_spread:.3f} <= máx {max_allowed_spread:.3f})"
        return False, f"Spread excessivo ({current_spread:.3f} > máx {max_allowed_spread:.3f})"

    def calculate_initial_sl(
        self,
        current_price: float,
        atr14: float,
        period_smooth: float,
        direction: Literal["BUY", "SELL"],
    ) -> tuple[float, float]:
        """Calcula o Stop Loss estrutural inicial conforme V26 §07.

        Fórmula: SL_pontos = ATR14 * min(2.0, T_final / 10.0)
        """
        cap = self.settings.sl_atr_cap  # 2.0
        divisor = self.settings.sl_period_divisor  # 10.0

        sl_multiplier = min(cap, period_smooth / divisor) if divisor > 0 else cap
        sl_points = atr14 * sl_multiplier

        # Proteção mínima contra SL nulo ou negativo
        sl_points = max(sl_points, 1e-4)

        if direction == "BUY":
            initial_sl = current_price - sl_points
        else:
            initial_sl = current_price + sl_points

        return sl_points, initial_sl

    def signal(
        self,
        features: DSPFeatures,
        patterns: Any = None,
        symbol: str = "XAUUSD",
        current_price: Optional[float] = None,
        current_spread: Optional[float] = None,
        bars_since_last_entry: int = 999,
    ) -> SignalDecision:
        """Gera o sinal de entrada ativo da estratégia V26."""
        n_bars = len(features.close_smooth)
        if n_bars < 7:
            return SignalDecision(
                signal="HOLD",
                symbol=symbol,
                price=0.0,
                sl_points=0.0,
                initial_sl=0.0,
                reasons=["Histórico insuficiente para cálculo de DSP (< 7 barras)"],
            )

        price = current_price if current_price is not None else float(features.close_smooth[-1])
        atr = float(features.atr14[-1])
        period = float(features.period_smooth[-1])

        # 1. Filtro de Cooldown
        if bars_since_last_entry < self.settings.inp_cooldown_bars:
            return SignalDecision(
                signal="HOLD",
                symbol=symbol,
                price=price,
                sl_points=0.0,
                initial_sl=0.0,
                reasons=[f"Cooldown ativo ({bars_since_last_entry} < {self.settings.inp_cooldown_bars} barras)"],
            )

        # 2. Filtro de Spread
        spread_ok, spread_msg = self.check_spread(symbol, current_spread, atr)
        if not spread_ok:
            return SignalDecision(
                signal="HOLD",
                symbol=symbol,
                price=price,
                sl_points=0.0,
                initial_sl=0.0,
                reasons=[spread_msg],
            )

        # 3. Head 1: Ciclo, Quadrante e Transição EBSW
        i_curr, q_curr = float(features.i1[-1]), float(features.q1[-1])
        i_prev, q_prev = float(features.i1[-2]), float(features.q1[-2])
        quad_curr = self.get_quadrant(i_curr, q_curr)
        quad_prev = self.get_quadrant(i_prev, q_prev)

        sine_curr = float(features.ebsw_sine[-1])
        leadsine_curr = float(features.ebsw_leadsine[-1])
        sine_prev = float(features.ebsw_sine[-2])
        leadsine_prev = float(features.ebsw_leadsine[-2])

        # Cruzamento EBSW de alta: Sine cruza acima de LeadSine
        ebsw_cross_up = (sine_prev <= leadsine_prev) and (sine_curr > leadsine_curr)
        # Cruzamento EBSW de baixa: Sine cruza abaixo de LeadSine
        ebsw_cross_down = (sine_prev >= leadsine_prev) and (sine_curr < leadsine_curr)

        # Condições de transição de fase
        buy_phase_transition = (quad_curr == 1 or quad_prev == 4) and (ebsw_cross_up or sine_curr > leadsine_curr)
        sell_phase_transition = (quad_curr == 3 or quad_prev == 2) and (ebsw_cross_down or sine_curr < leadsine_curr)

        # 4. Head 2: Acumulação Prévia e Breakout
        acc_ok, acc_msg = self.check_accumulation(features, price)

        # Avaliação de COMPRA (BUY)
        if buy_phase_transition and acc_ok:
            breakout_ok, breakout_msg = self.check_breakout(features, price, direction="BUY")
            if breakout_ok:
                sl_pts, sl_price = self.calculate_initial_sl(price, atr, period, direction="BUY")
                logger.info(
                    "V26 BUY SIGNAL em {} @ {:.2f} | SL={:.2f} ({:.2f} pts) | Quad={} -> {} | EBSW Sine={:.3f} Lead={:.3f}",
                    symbol,
                    price,
                    sl_price,
                    sl_pts,
                    quad_prev,
                    quad_curr,
                    sine_curr,
                    leadsine_curr,
                )
                return SignalDecision(
                    signal="BUY",
                    symbol=symbol,
                    price=price,
                    sl_points=sl_pts,
                    initial_sl=sl_price,
                    reasons=[
                        f"Transição Q4->Q1 (Quad {quad_prev}->{quad_curr})",
                        acc_msg,
                        breakout_msg,
                    ],
                    metadata={
                        "quadrant": quad_curr,
                        "cycle_mode": int(features.cycle_mode[-1]),
                        "ebsw_sine": sine_curr,
                        "ebsw_leadsine": leadsine_curr,
                        "atr14": atr,
                        "period_smooth": period,
                    },
                )

        # Avaliação de VENDA (SELL)
        if sell_phase_transition and acc_ok:
            breakout_ok, breakout_msg = self.check_breakout(features, price, direction="SELL")
            if breakout_ok:
                sl_pts, sl_price = self.calculate_initial_sl(price, atr, period, direction="SELL")
                logger.info(
                    "V26 SELL SIGNAL em {} @ {:.2f} | SL={:.2f} ({:.2f} pts) | Quad={} -> {} | EBSW Sine={:.3f} Lead={:.3f}",
                    symbol,
                    price,
                    sl_price,
                    sl_pts,
                    quad_prev,
                    quad_curr,
                    sine_curr,
                    leadsine_curr,
                )
                return SignalDecision(
                    signal="SELL",
                    symbol=symbol,
                    price=price,
                    sl_points=sl_pts,
                    initial_sl=sl_price,
                    reasons=[
                        f"Transição Q2->Q3 (Quad {quad_prev}->{quad_curr})",
                        acc_msg,
                        breakout_msg,
                    ],
                    metadata={
                        "quadrant": quad_curr,
                        "cycle_mode": int(features.cycle_mode[-1]),
                        "ebsw_sine": sine_curr,
                        "ebsw_leadsine": leadsine_curr,
                        "atr14": atr,
                        "period_smooth": period,
                    },
                )

        return SignalDecision(
            signal="HOLD",
            symbol=symbol,
            price=price,
            sl_points=0.0,
            initial_sl=0.0,
            reasons=["Condições operacionais de entrada não satisfeitas"],
            metadata={"quadrant": quad_curr, "cycle_mode": int(features.cycle_mode[-1])},
        )

    def manage_open_trade(
        self,
        position: Position,
        features: DSPFeatures,
        current_price: float,
    ) -> TradeAction:
        """Gerencia ordens abertas com as regras completas do V26:

        1. Breakeven em +500.0 pts (move SL para entry + 10 pts)
        2. Parciais Automáticas (30% no alvo 1 / EBSW cross, 30% no alvo 2)
        3. Trailing Stop Adaptativo (AGC + Regime de Ciclo, monotônico)
        4. Saída Suave por Inversão de Fase 180° (aperto de trailing stop)
        5. SEM Take Profit fixo
        """
        position.update_price(current_price)
        profit_pts = position.get_profit_points(current_price)
        atr_curr = float(features.atr14[-1])
        amp_norm = float(features.amplitude_norm[-1])
        cycle_mode = int(features.cycle_mode[-1])
        curr_phase = float(features.phase[-1])

        sine_curr = float(features.ebsw_sine[-1])
        leadsine_curr = float(features.ebsw_leadsine[-1])

        # ----------------------------------------------------------------------
        # 1. BREAKEVEN (+500 pts)
        # ----------------------------------------------------------------------
        be_target = self.settings.inp_be_pts  # 500.0 pts
        be_spread_buffer = self.settings.inp_be_spread or 10.0  # +10 pts de lucro protegido

        if not position.be_done and profit_pts >= be_target:
            if position.order_type == "BUY":
                new_sl = position.open_price + be_spread_buffer
                if new_sl > position.sl:
                    position.be_done = True
                    logger.info(
                        "Position #{} BUY Breakeven ativado (+{:.1f} pts) -> Novo SL={:.2f}",
                        position.ticket,
                        profit_pts,
                        new_sl,
                    )
                    return TradeAction(
                        action="MODIFY_SL",
                        new_sl=new_sl,
                        reason=f"Breakeven atingido (+{profit_pts:.1f} >= {be_target:.1f} pts)",
                    )
            else:  # SELL
                new_sl = position.open_price - be_spread_buffer
                if position.sl == 0.0 or new_sl < position.sl:
                    position.be_done = True
                    logger.info(
                        "Position #{} SELL Breakeven ativado (+{:.1f} pts) -> Novo SL={:.2f}",
                        position.ticket,
                        profit_pts,
                        new_sl,
                    )
                    return TradeAction(
                        action="MODIFY_SL",
                        new_sl=new_sl,
                        reason=f"Breakeven atingido (+{profit_pts:.1f} >= {be_target:.1f} pts)",
                    )

        # ----------------------------------------------------------------------
        # 2. PARCIAIS AUTOMÁTICAS (30% + 30%)
        # ----------------------------------------------------------------------
        # Parcial 1: +500 pts OU cruzamento EBSW adverso
        p1_target_pts = self.settings.inp_parcial1_pts or 500.0
        ebsw_adverse = (
            (position.order_type == "BUY" and sine_curr < leadsine_curr)
            or (position.order_type == "SELL" and sine_curr > leadsine_curr)
        )

        if not position.partial1_done:
            if profit_pts >= p1_target_pts or (profit_pts > 100.0 and ebsw_adverse):
                partial_vol = round(position.volume * (self.settings.inp_parcial1_pct / 100.0), 2)
                if partial_vol > 0.0:
                    position.partial1_done = True
                    logger.info(
                        "Position #{} Parcial 1 ({:.0f}%, vol={}) | Lucro={:.1f} pts | EBSW adverso={}",
                        position.ticket,
                        self.settings.inp_parcial1_pct,
                        partial_vol,
                        profit_pts,
                        ebsw_adverse,
                    )
                    return TradeAction(
                        action="PARTIAL_CLOSE",
                        volume_to_close=partial_vol,
                        reason=f"Parcial 1 executada (+{profit_pts:.1f} pts)",
                    )

        # Parcial 2: +1000 pts
        p2_target_pts = self.settings.inp_parcial2_pts or 1000.0
        if position.partial1_done and not position.partial2_done:
            if profit_pts >= p2_target_pts:
                partial_vol = round(position.volume * (self.settings.inp_parcial2_pct / 100.0), 2)
                if partial_vol > 0.0:
                    position.partial2_done = True
                    logger.info(
                        "Position #{} Parcial 2 ({:.0f}%, vol={}) | Lucro={:.1f} pts",
                        position.ticket,
                        self.settings.inp_parcial2_pct,
                        partial_vol,
                        profit_pts,
                    )
                    return TradeAction(
                        action="PARTIAL_CLOSE",
                        volume_to_close=partial_vol,
                        reason=f"Parcial 2 executada (+{profit_pts:.1f} pts)",
                    )

        # ----------------------------------------------------------------------
        # 3. TRAILING STOP ADAPTATIVO (AGC + CICLO + SAÍDA 180° DE FASE)
        # ----------------------------------------------------------------------
        cycle_strength = (
            self.settings.cycle_strength_on if cycle_mode == 1 else self.settings.cycle_strength_off
        )
        # Base do trailing: ATR14 como distância padrão calibrável
        base_trail_dist = (
            self.settings.inp_trail_base_pct
            if self.settings.inp_trail_base_pct is not None
            else (1.0 * atr_curr)
        )

        trail_points = amp_norm * base_trail_dist * cycle_strength

        # Verificação de Saída por Inversão de Fase (180° = π radianos)
        phase_delta = abs(curr_phase - position.entry_phase)
        # Ajuste de wrap angular em [-π, π]
        if phase_delta > np.pi:
            phase_delta = abs(2.0 * np.pi - phase_delta)

        # Se fase virou ~180° contra a posição, aperta o trailing para saída suave
        if phase_delta >= (self.settings.phase_exit_radians * 0.90):  # >= ~162° a 180°
            trail_points *= self.settings.trail_after_180_factor  # 0.5 * TrailPoints
            logger.debug(
                "Position #{} Inversão de fase detectada (Δphi={:.2f} rad) -> Trailing apertado para {:.2f} pts",
                position.ticket,
                phase_delta,
                trail_points,
            )

        # Atualização monotônica do Trailing Stop
        if position.order_type == "BUY":
            candidate_sl = current_price - trail_points
            if candidate_sl > position.sl:
                logger.info(
                    "Position #{} BUY Trailing Stop atualizado: {:.2f} -> {:.2f} (Distância={:.2f} pts)",
                    position.ticket,
                    position.sl,
                    candidate_sl,
                    trail_points,
                )
                position.sl = candidate_sl
                return TradeAction(
                    action="MODIFY_SL",
                    new_sl=candidate_sl,
                    reason=f"Trailing Stop AGC adaptativo (dist={trail_points:.2f} pts)",
                )
        else:  # SELL
            candidate_sl = current_price + trail_points
            if position.sl == 0.0 or candidate_sl < position.sl:
                logger.info(
                    "Position #{} SELL Trailing Stop atualizado: {:.2f} -> {:.2f} (Distância={:.2f} pts)",
                    position.ticket,
                    position.sl,
                    candidate_sl,
                    trail_points,
                )
                position.sl = candidate_sl
                return TradeAction(
                    action="MODIFY_SL",
                    new_sl=candidate_sl,
                    reason=f"Trailing Stop AGC adaptativo (dist={trail_points:.2f} pts)",
                )

        return TradeAction(action="HOLD", reason="Manter posição sem alterações")


# ==============================================================================
# MOTOR WCE 2014 — HILBERT TRANSFORM + DIRECTIONAL CHANGES (SHADOW MODE)
# ==============================================================================


class Quadrant(str, Enum):
    """Quadrante do plano I-Q. Herda de `str` para que o report e os logs
    continuem imprimindo "Q1" e nao "Quadrant.Q1".

    `AXIS` cobre o caso em que I ou Q e exatamente zero: nao ha quadrante
    definido, e inventar um dispararia entrada fora do PDF (§9.1). Ele existe
    como membro explicito do enum em vez de `None` solto pelo codigo, para que
    "sem quadrante" seja um valor do dominio e nao um vazamento de `None`.
    """

    Q1 = "Q1"  # I>0, Q>0
    Q2 = "Q2"  # I<0, Q>0
    Q3 = "Q3"  # I<0, Q<0
    Q4 = "Q4"  # I>0, Q<0
    AXIS = "AXIS"  # I==0 ou Q==0: sinal degenerado

    def __str__(self) -> str:
        return self.value


class WCE2014Strategy:
    """Motor ATIVO baseado no artigo WCE 2014 (pp. 927-933).

    Ativado como modelo primario em 2026-09-26 (decisao do responsavel).
    As regras implementadas sao as literais do PDF:

      Entrada (p. 929, secao "Buy and Sell Signals"):
        "whenever the signal crosses Quarter 1, the price is likely to rise
        afterwards, until it exits from Quarter 1 to any other quarter."
        "…whenever the signal crosses Quarter 3, the price is likely to fall
        afterwards, until it exits from Quarter 3 to any other quarter."

      O verbo e "crosses". A entrada e a TRAVESSIA para dentro de Q1 (a partir
      de Q4) ou de Q3 (a partir de Q2) — nao o simples fato de estar dentro
      do quadrante. Implementar por nivel reentraria toda barra dentro de Q1,
      o que a versao anterior (modo sombra) fazia e o PDF nao diz.

      Mapeamento algebrico dos quadrantes: NAO esta no WCE, que os define
      geometricamente (Fig. 5 e 7). Vem do V26 p.3, secao Hilbert Transform,
      por decisao do responsavel — ver `docs/decisoes_tecnicas.md` §7.1.
        Q1={I>0,Q>0}  Q2={I<0,Q>0}  Q3={I<0,Q<0}  Q4={I>0,Q<0}

    O que o PDF NAO tem, e por isso nao esta aqui:
      - Stop loss / TP / trailing / break-even: o artigo so diz fechar ao sair
        do quadrante. Ver `initial_sl` abaixo.
      - O filtro ISOM precisa do threshold `dx(%)`. O simbolo aparece no
        artigo; o VALOR nao. Ver `isom_allows`.
    """

    # O stop deste modelo NAO vem do PDF WCE. `guardrail_projeto=True` existe
    # para impedir que ele seja lido como regra do artigo em code review.
    SL_GUARDRAIL_PROJETO = True

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._isom_warned = False
        self._v26: Optional[V26Strategy] = None

    # --- quadrantes ---------------------------------------------------------

    @staticmethod
    def quadrant(i: float, q: float) -> Quadrant:
        """Classifica (I, Q) no plano I-Q. `AXIS` no eixo (sinal zero)."""
        if i > 0.0 and q > 0.0:
            return Quadrant.Q1
        if i < 0.0 and q > 0.0:
            return Quadrant.Q2
        if i < 0.0 and q < 0.0:
            return Quadrant.Q3
        if i > 0.0 and q < 0.0:
            return Quadrant.Q4
        return Quadrant.AXIS

    @staticmethod
    def _iq(data: Any) -> tuple[np.ndarray, np.ndarray]:
        """Aceita DSPFeatures ou DataFrame com colunas i1/q1.

        O engine entrega `DSPFeatures`; a spec da FASE 2 pede `df`. Suportar
        os dois evita que o modelo se comporte diferente em teste e producao.
        """
        if isinstance(data, pd.DataFrame):
            return data["i1"].to_numpy(dtype=float), data["q1"].to_numpy(dtype=float)
        return np.asarray(data.i1, dtype=float), np.asarray(data.q1, dtype=float)

    # --- regra de saida (literal do PDF) ------------------------------------

    def should_exit(self, quadrante_atual: Quadrant, side: str) -> bool:
        """Literal: "…which is closed when the signal exits the quarter."

        Long (entrou em Q1) sai ao deixar Q1; short (entrou em Q3) sai ao
        deixar Q3. Estar dentro do quadrante de origem mantem a posicao.

        `AXIS` conta como saida: sair do quadrante para o eixo e sair dele.
        """
        origem = {
            "BUY": Quadrant.Q1,
            "SELL": Quadrant.Q3,
        }.get(side)
        if origem is None:
            # `return False` aqui significaria "nunca sair" — uma posicao
            # ficaria aberta para sempre por um typo. Falhar e o correto.
            raise ValueError(f"side invalido: {side!r} (esperado BUY ou SELL)")
        return quadrante_atual != origem

    # --- filtro ISOM --------------------------------------------------------

    def isom_allows(self, dx_percent: Optional[float] = None) -> bool:
        """Filtro ISOM do Listing 1: "Filter out data with low numbers of
        directional changes".

        DESATIVADO por decisão de projeto (§7.2 e §9.2 de
        `docs/decisoes_tecnicas.md`): o artigo nomeia `dx(%)` mas nao publica
        o valor do threshold, e "low numbers" e qualitativo. Fixar um numero
        seria INVENTAR regra, entao o filtro nao rejeita barra nenhuma e emite
        um WARNING unico.

        O parametro existe para que a calibracao futura tenha um lugar fixo
        quando — e se — o responsavel fornecer um `dx%` medido. Ate la ele
        rejeita o valor, em vez de aceitar um numero que o PDF nao sustenta.
        """
        if dx_percent is not None:
            raise ValueError(
                "ISOM continua desativado: o PDF WCE 2014 nomeia o threshold "
                "dx(%) mas nao informa seu valor. Calibrar o filtro exige um "
                "dx% medido, autorizado pelo responsavel (decisoes_tecnicas "
                "§7.2/§9.2). Nenhum corte sera aplicado."
            )
        if not self._isom_warned:
            self._isom_warned = True
            logger.warning(
                "ISOM desativado: o PDF WCE 2014 nomeia o threshold dx(%) "
                "mas nao informa seu valor. Nenhum corte sera aplicado."
            )
        return True

    # --- guardrail de risco (NAO e regra do PDF) ---------------------------

    def initial_sl(
        self,
        current_price: float,
        atr14: float,
        period_smooth: float,
        direction: Literal["BUY", "SELL"],
    ) -> tuple[float, float]:
        """Stop inicial = `V26Strategy.calculate_initial_sl`.

        guardrail_projeto=True: o WCE 2014 nao define stop loss nenhum. Sem
        isto o trade atravessa o ciclo inteiro do Hilbert e o Max DD do
        backtest sai sem teto. Formula e a do V26 p.3, reaproveitada.
        """
        # Uma instancia so: construir V26Strategy a cada barra custa caro
        # num backtest de 35k barras e o objeto nao tem estado.
        if self._v26 is None:
            self._v26 = V26Strategy(self.settings)
        return self._v26.calculate_initial_sl(
            current_price, atr14, period_smooth, direction
        )

    @staticmethod
    def _hold(reasons: list[str]) -> SignalDecision:
        """HOLD sem preco: o WCE decide por quadrante, nao por nivel de preco."""
        return SignalDecision(
            signal="HOLD", symbol="", price=0.0, sl_points=0.0, initial_sl=0.0,
            reasons=reasons,
        )

    # --- entrada ------------------------------------------------------------

    def generate_signal(
        self,
        df: Any,
        dx_percent: Optional[float] = None,
    ) -> SignalDecision:
        """Decisao de entrada por TRAVESSIA de quadrante (Q4->Q1, Q2->Q3)."""
        i1, q1 = self._iq(df)
        n = len(i1)
        if n < 2:
            return self._hold(["Historico insuficiente para classificar quadrante"])

        quad_prev = self.quadrant(float(i1[-2]), float(q1[-2]))
        quad_curr = self.quadrant(float(i1[-1]), float(q1[-1]))

        if not self.isom_allows(dx_percent):
            return self._hold(["ISOM filtrou a barra"])

        decision, reason = "HOLD", "sem travessia de quadrante"
        if quad_prev == "Q4" and quad_curr == "Q1":
            decision = "BUY"
            reason = "travessia Q4 -> Q1 (literal WCE p.929)"
        elif quad_prev == "Q2" and quad_curr == "Q3":
            decision = "SELL"
            reason = "travessia Q2 -> Q3 (literal WCE p.929)"

        return SignalDecision(
            signal=decision,
            symbol="",
            price=0.0,
            sl_points=0.0,
            initial_sl=0.0,
            reasons=[reason],
            metadata={
                "quadrant_prev": quad_prev,
                "quadrant_curr": quad_curr,
                "guardrail_projeto": self.SL_GUARDRAIL_PROJETO,
                "isom_ativo": dx_percent is not None,
            },
        )

    # --- compatibilidade com o motor V26 ------------------------------------

    def signal(
        self,
        features: DSPFeatures,
        patterns: Any = None,
        symbol: str = "XAUUSD",
        current_price: Optional[float] = None,
    ) -> Signal:
        """Alias em nivel para o `StrategyRouter` legado (shadow)."""
        return self.generate_signal(features).signal



# ==============================================================================
# STRATEGY ROUTER — ORQUESTRADOR CENTRAL
# ==============================================================================


class StrategyRouter:
    """Orquestrador central de sinais de trading do Hilberti.

    - O modelo ATIVO (`settings.active_model`) decide a execução real e o
      campo `modelo_ativo` da decisão — os dois não podem divergir.
      Padrão "v26" desde 2026-09-26; o WCE 2014 fica acessível por
      `ACTIVE_MODEL=wce` e por `--model wce` no backtest.
    - O modelo inativo continua sendo calculado e reportado como sombra.
    - As cabeças de ML (3 e 4) seguem em Shadow Mode e registram logs.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.v26 = V26Strategy(self.settings)
        self.wce = WCE2014Strategy(self.settings)

    def decide(
        self,
        features: DSPFeatures,
        patterns: Any = None,
        symbol: str = "XAUUSD",
        current_price: Optional[float] = None,
        current_spread: Optional[float] = None,
        bars_since_last_entry: int = 999,
        shadow_ml: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Gera a decisão consolidada de trading."""
        v26_decision = self.v26.signal(
            features=features,
            patterns=patterns,
            symbol=symbol,
            current_price=current_price,
            current_spread=current_spread,
            bars_since_last_entry=bars_since_last_entry,
        )
        wce_decision = self.wce.generate_signal(features)
        wce_signal = wce_decision.signal

        # `active_model` decide o que EXECUTA. Até 2026-09-26 este valor era
        # lido só pelo backtest: o `decide()` executava o V26 fixo, de modo que
        # um default "wce" produzia um sistema que dizia executar o WCE e
        # executava o V26. O outro modelo continua sendo calculado e logado.
        if self.settings.active_model == "wce":
            ativa = wce_decision
            sombra_v26 = v26_decision
        else:
            ativa = v26_decision
            sombra_v26 = None

        execute = ativa.signal in ("BUY", "SELL")

        logger.info(
            "StrategyRouter [{}] | Ativo_{}: {} | Sombra: {} | Shadow_ML: {} | Execute: {}",
            symbol,
            self.settings.active_model.upper(),
            ativa.signal,
            wce_signal if sombra_v26 is not None else v26_decision.signal,
            shadow_ml,
            execute,
        )

        out: dict[str, Any] = {
            "signal": ativa.signal,
            "symbol": symbol,
            "price": ativa.price,
            "sl_points": ativa.sl_points,
            "initial_sl": ativa.initial_sl,
            "reasons": ativa.reasons,
            "metadata": ativa.metadata,
            "modelo_ativo": self.settings.active_model,
            "shadow_wce": wce_signal,
            "shadow_v26": sombra_v26.signal if sombra_v26 is not None else None,
            "shadow_ml": shadow_ml,
            "execute": execute,
        }
        return out
