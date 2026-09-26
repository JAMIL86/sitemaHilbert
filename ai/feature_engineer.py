"""Engenharia de Features e Processamento Digital de Sinais (DSP) — Hilberti.

================================================================================
REFERÊNCIAS BIBLIOGRÁFICAS E ESPECIFICAÇÃO MATEMÁTICA:
================================================================================
1. John F. Ehlers, "Cycle Analytics for Traders: Advanced Technical Trading Concepts",
   John Wiley & Sons, 2013:
   - Cap. 2: Moving Averages & Weighted Smoothing (WMA)
   - Cap. 3: High-Pass & Detrending Filters
   - Cap. 4: Hilbert Transform & Discrete FIR In-Phase/Quadrature Decomposition
   - Cap. 7: Measuring Cycles & The Homodyne Discriminator
   - Cap. 8: The Roofing Filter (High-Pass + 2-Pole SuperSmoother)
   - Cap. 9: Instantaneous Trendline (EIT)
   - Cap. 11: Even Better Sine Wave (EBSW: Sine 45° lead & LeadSine 135° lead)
   - Cap. 12: Automatic Gain Control (AGC) & Regime Filter (CycleMode)

2. John F. Ehlers, "Rocket Science for Traders: Digital Signal Processing Applications",
   John Wiley & Sons, 2001.

3. Chimera Quant Engineering, "Hilbert Cycle + Chimera SSM — V26 Operational Specification",
   Advanced Mathematics Edition, 2026.

4. WCE 2014, "Hilbert Transform & Directional Changes (ISOM)", Proceedings of the World
   Congress on Engineering 2014, Vol II, pp. 927-933.
================================================================================
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from loguru import logger
import numpy as np
import pandas as pd

from config.settings import Settings, get_settings


# ==============================================================================
# 1. FUNÇÕES DSP ISOLADAS (MATEMÁTICA PURA)
# ==============================================================================


def calc_wma(prices: np.ndarray, weights: Sequence[float] = (4.0, 3.0, 2.0, 1.0)) -> np.ndarray:
    """Calcula a Média Móvel Ponderada (Weighted Moving Average).

    - XAU/USD: WMA-4 com pesos [4, 3, 2, 1] / 10
      P_smooth(t) = [4·close(t) + 3·close(t-1) + 2·close(t-2) + 1·close(t-3)] / 10
    - XAG/USD: WMA-5 com pesos [5, 4, 3, 2, 1] / 15

    Ref: Ehlers (2013), Cap. 2.
    """
    p = np.asarray(prices, dtype=np.float64)
    n = len(p)
    k = len(weights)
    w = np.asarray(weights, dtype=np.float64)
    w_sum = np.sum(w)
    out = np.copy(p)

    if n < k:
        return out

    # Convolução causal direta (pesos invertidos para índice temporal t, t-1, ...)
    # weights[0] multiplica price[t], weights[1] multiplica price[t-1], etc.
    for i in range(k - 1, n):
        window = p[i - k + 1 : i + 1][::-1]
        out[i] = np.dot(window, w) / w_sum

    # Para os primeiros k-1 elementos, preenche com o primeiro valor calculado
    if k > 1 and n >= k:
        out[: k - 1] = out[k - 1]

    return out


def calc_detrender(smooth: np.ndarray) -> np.ndarray:
    """Filtro Detrender FIR de 7 barras do V26 / Ehlers.

    detrender(i) = 0.25·smooth(i) + 0.75·smooth(i-2) - 0.25·smooth(i-4) - 0.75·smooth(i-6)

    Ref: Ehlers (2013), Cap. 3; V26 PDF Seção 01.
    """
    s = np.asarray(smooth, dtype=np.float64)
    n = len(s)
    out = np.zeros(n, dtype=np.float64)

    for i in range(n):
        s0 = s[i]
        s2 = s[i - 2] if i >= 2 else s[0]
        s4 = s[i - 4] if i >= 4 else s[0]
        s6 = s[i - 6] if i >= 6 else s[0]
        out[i] = 0.25 * s0 + 0.75 * s2 - 0.25 * s4 - 0.75 * s6

    return out


def calc_hilbert_fir(detrender: np.ndarray, n_order: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """Transformada de Hilbert Discreta Truncada (FIR) com atraso central de 3 barras.

    Q1(i) = 0.25·det(i) + 0.75·det(i-2) - 0.25·det(i-4) - 0.75·det(i-6)
    I1(i) = detrender(i-3)

    Ao atrasar a componente In-Phase (I) exatamente em 3 barras, a defasagem temporal
    do centro do filtro de Quadratura (Q) é balanceada, resultando em quadratura
    analítica exata de 90° (pi/2 radianos) entre I1 e Q1.

    Ref: Ehlers (2013), Cap. 4; V26 PDF Seções 01 e 03.
    """
    d = np.asarray(detrender, dtype=np.float64)
    length = len(d)
    q1 = np.zeros(length, dtype=np.float64)
    i1 = np.zeros(length, dtype=np.float64)

    for i in range(length):
        d0 = d[i]
        d2 = d[i - 2] if i >= 2 else d[0]
        d4 = d[i - 4] if i >= 4 else d[0]
        d6 = d[i - 6] if i >= 6 else d[0]

        q1[i] = 0.25 * d0 + 0.75 * d2 - 0.25 * d4 - 0.75 * d6
        i1[i] = d[i - 3] if i >= 3 else d[0]

    return i1, q1


def calc_phase_amplitude(i1: np.ndarray, q1: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Calcula a Fase Instantânea φ(t) e Amplitude A(t) no plano complexo I-Q.

    φ(t) = atan2(Q(t), I(t))
    A(t) = sqrt(I(t)² + Q(t)²)

    Ref: Ehlers (2013), Cap. 4; WCE 2014 Seção II.
    """
    i_arr = np.asarray(i1, dtype=np.float64)
    q_arr = np.asarray(q1, dtype=np.float64)

    phase = np.arctan2(q_arr, i_arr)
    amplitude = np.sqrt(i_arr**2 + q_arr**2)
    return phase, amplitude


def calc_homodyne_discriminator(
    i1: np.ndarray,
    q1: np.ndarray,
    alpha_smooth: float = 0.5,
    t_min: float = 6.0,
    t_max: float = 50.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Discriminador Homódino de Ehlers para medição do período de ciclo dominante T.

    Mede a velocidade angular instantânea Δφ(t) através da demodulação em quadratura
    (multiplicação complexa z_t · conj(z_{t-1})):
    Re(t) = I(t)·I(t-1) + Q(t)·Q(t-1)
    Im(t) = I(t-1)·Q(t) - I(t)·Q(t-1)
    Δφ(t) = atan2(Im(t), Re(t))
    T(t)  = 2π / Δφ(t)

    Aplica suavização exponencial EMA (α=0.5) e saturação (clamp) em [T_min, T_max].

    Ref: Ehlers (2013), Cap. 7; V26 PDF Seção 01.
    """
    i_arr = np.asarray(i1, dtype=np.float64)
    q_arr = np.asarray(q1, dtype=np.float64)
    n = len(i_arr)

    period_raw = np.full(n, (t_min + t_max) / 2.0, dtype=np.float64)
    period_smooth = np.full(n, (t_min + t_max) / 2.0, dtype=np.float64)

    for i in range(1, n):
        # Produto de números complexos homódino
        re = i_arr[i] * i_arr[i - 1] + q_arr[i] * q_arr[i - 1]
        im = i_arr[i - 1] * q_arr[i] - i_arr[i] * q_arr[i - 1]

        # Variação de fase instantânea (velocidade angular absoluta)
        delta_phi = abs(float(np.arctan2(im, re)))

        # Evita divisão por zero ou saltos assintóticos
        if delta_phi > 1e-4:
            t_calc = (2.0 * np.pi) / delta_phi
        else:
            t_calc = period_smooth[i - 1]

        # Clamp de limites físicos
        t_clamped = np.clip(t_calc, t_min, t_max)
        period_raw[i] = t_clamped

        # Suavização EMA alpha=0.5
        period_smooth[i] = (
            alpha_smooth * t_clamped + (1.0 - alpha_smooth) * period_smooth[i - 1]
        )

    return period_raw, period_smooth


def calc_supersmoother_2p(prices: np.ndarray, period_cutoff: float = 10.0) -> np.ndarray:
    """SuperSmoother Filter de 2 polos de John Ehlers (rejeição de ruído aliasing).

    Ref: Ehlers (2013), Cap. 8.
    """
    p = np.asarray(prices, dtype=np.float64)
    n = len(p)
    out = np.copy(p)

    if n < 3:
        return out

    a1 = np.exp(-1.414 * np.pi / period_cutoff)
    b1 = 2.0 * a1 * np.cos(1.414 * np.pi / period_cutoff)
    c2 = b1
    c3 = -(a1**2)
    c1 = 1.0 - c2 - c3

    for i in range(2, n):
        out[i] = (
            c1 * 0.5 * (p[i] + p[i - 1])
            + c2 * out[i - 1]
            + c3 * out[i - 2]
        )

    return out


def calc_roofing_filter(
    prices: np.ndarray,
    hp_alpha: float = 0.707,
    ss_period: float = 10.0,
) -> np.ndarray:
    """Roofing Filter de John Ehlers (High-Pass Filter + 2-Pole SuperSmoother).

    HP(t) = (1 - α)·(price(t) - price(t-1)) + α·HP(t-1) com α ≈ 0.707
    Roofing(t) = SuperSmoother2P(HP(t), cutoff=10)

    Ref: Ehlers (2013), Cap. 8; V26 PDF Seção 01.
    """
    p = np.asarray(prices, dtype=np.float64)
    n = len(p)
    hp = np.zeros(n, dtype=np.float64)

    for i in range(1, n):
        hp[i] = (1.0 - hp_alpha) * (p[i] - p[i - 1]) + hp_alpha * hp[i - 1]

    # Aplica o SuperSmoother de 2 polos na saída do High-Pass
    roofing = calc_supersmoother_2p(hp, period_cutoff=ss_period)
    return roofing


def calc_eit(roofing: np.ndarray, prices: np.ndarray | None = None, flat_factor: float = 0.0005) -> tuple[np.ndarray, np.ndarray]:
    """EIT — Instantaneous Trendline derivada do Roofing Filter.

    IT(t) = [3·Roofing(t) + 2·Roofing(t-1) + Roofing(t-2)] / 6
    Slope de Acumulação: |IT(t) - IT(t-1)| < 0.0005 · price(t)

    Ref: Ehlers (2013), Cap. 9; V26 PDF Seções 01 e 03.
    """
    r = np.asarray(roofing, dtype=np.float64)
    n = len(r)
    it = np.copy(r)
    is_flat = np.zeros(n, dtype=bool)

    for i in range(2, n):
        it[i] = (3.0 * r[i] + 2.0 * r[i - 1] + r[i - 2]) / 6.0

    if prices is not None:
        p = np.asarray(prices, dtype=np.float64)
        for i in range(1, n):
            delta = abs(it[i] - it[i - 1])
            is_flat[i] = delta < (flat_factor * p[i])

    return it, is_flat


def calc_ebsw(phase: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Even Better Sine Wave (EBSW) de John Ehlers.

    Sine(t)     = sin(φ(t) + π/4)   [avanço de 45°]
    LeadSine(t) = sin(φ(t) + 3π/4)  [avanço de 135°]

    A amplitude resultante permanece estritamente no intervalo [-1.0, +1.0].
    Cruzamento no Quadrante 4 (Sine cruza acima de LeadSine) = Sinal de Compra.
    Cruzamento no Quadrante 2 (Sine cruza abaixo de LeadSine) = Sinal de Venda.

    Ref: Ehlers (2013), Cap. 11; V26 PDF Seção 03.
    """
    phi = np.asarray(phase, dtype=np.float64)
    sine = np.sin(phi + np.pi / 4.0)
    lead_sine = np.sin(phi + 3.0 * np.pi / 4.0)

    # Garante limites estritos [-1.0, 1.0] contra overflow numérico de precisão flutuante
    sine = np.clip(sine, -1.0, 1.0)
    lead_sine = np.clip(lead_sine, -1.0, 1.0)

    return sine, lead_sine


def calc_cycle_mode(
    sine: np.ndarray,
    lead_sine: np.ndarray,
    threshold: float = 0.85,
) -> np.ndarray:
    """Filtro de Regime CycleMode.

    CycleMode(t) = 1 se |Sine(t)| > 0.85 OU |LeadSine(t)| > 0.85
    CycleMode(t) = 0 caso contrário (mercado em regime de tendência forte).

    Quando CycleMode == 0, o sistema bloqueia entradas cíclicas para evitar operar
    contra tendências direcionais sem oscilação clara.

    Ref: Ehlers (2013), Cap. 12; V26 PDF Seção 01 e 03.
    """
    s = np.asarray(sine, dtype=np.float64)
    ls = np.asarray(lead_sine, dtype=np.float64)

    cond = (np.abs(s) > threshold) | (np.abs(ls) > threshold)
    return cond.astype(np.int32)


def calc_agc(amplitude: np.ndarray, period: int = 50) -> np.ndarray:
    """Controle Automático de Ganho (Automatic Gain Control - AGC).

    AmplitudeNorm(t) = amplitude(t) / SMA(amplitude, 50)

    Normaliza a amplitude do ciclo eliminando dependência da volatilidade bruta,
    permitindo modulação precisa do trailing stop e detecção de acumulação.

    Ref: Ehlers (2013), Cap. 12; V26 PDF Seção 01.
    """
    amp = np.asarray(amplitude, dtype=np.float64)
    n = len(amp)
    norm = np.ones(n, dtype=np.float64)

    if n == 0:
        return norm

    # SMA móvel de 50 períodos
    series = pd.Series(amp)
    sma = series.rolling(window=period, min_periods=1).mean().to_numpy()

    # Evita divisão por zero
    mask = sma > 1e-8
    norm[mask] = amp[mask] / sma[mask]
    return norm


def calc_atr(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    period: int = 14,
) -> np.ndarray:
    """Average True Range (ATR) de 14 períodos com suavização RMA de Wilder.

    TR = max(High - Low, |High - Close_{prev}|, |Low - Close_{prev}|)

    Ref: Wilder (1978); V26 PDF Seção 01 e 07.
    """
    h = np.asarray(high, dtype=np.float64)
    l = np.asarray(low, dtype=np.float64)
    c = np.asarray(close, dtype=np.float64)
    n = len(c)

    if n == 0:
        return np.array([], dtype=np.float64)

    tr = np.zeros(n, dtype=np.float64)
    tr[0] = h[0] - l[0]

    for i in range(1, n):
        tr[i] = max(
            h[i] - l[i],
            abs(h[i] - c[i - 1]),
            abs(l[i] - c[i - 1]),
        )

    # RMA Wilder: EMA com alpha = 1 / period
    atr = np.zeros(n, dtype=np.float64)
    if n <= period:
        atr[:] = np.mean(tr)
        return atr

    atr[period - 1] = np.mean(tr[:period])
    alpha = 1.0 / float(period)

    for i in range(period, n):
        atr[i] = alpha * tr[i] + (1.0 - alpha) * atr[i - 1]

    # Preenche o warmup inicial com a primeira média
    atr[: period - 1] = atr[period - 1]
    return atr


# ==============================================================================
# 2. ESTRUTURA DE DADOS E ORQUESTRADOR FEATURE ENGINEER
# ==============================================================================


@dataclass(slots=True)
class DSPFeatures:
    """Dataclass encapsulando todos os vetores de features DSP calculados."""

    close_smooth: np.ndarray
    detrender: np.ndarray
    i1: np.ndarray
    q1: np.ndarray
    phase: np.ndarray
    amplitude: np.ndarray
    period_raw: np.ndarray
    period_smooth: np.ndarray
    roofing: np.ndarray
    eit: np.ndarray
    eit_flat: np.ndarray
    ebsw_sine: np.ndarray
    ebsw_leadsine: np.ndarray
    cycle_mode: np.ndarray
    amplitude_norm: np.ndarray
    atr14: np.ndarray

    def to_dict(self) -> dict[str, np.ndarray]:
        return {
            "close_smooth": self.close_smooth,
            "detrender": self.detrender,
            "i1": self.i1,
            "q1": self.q1,
            "phase": self.phase,
            "amplitude": self.amplitude,
            "period_raw": self.period_raw,
            "period_smooth": self.period_smooth,
            "roofing": self.roofing,
            "eit": self.eit,
            "eit_flat": self.eit_flat,
            "ebsw_sine": self.ebsw_sine,
            "ebsw_leadsine": self.ebsw_leadsine,
            "cycle_mode": self.cycle_mode,
            "amplitude_norm": self.amplitude_norm,
            "atr14": self.atr14,
        }

    def to_dataframe(self, index: Any = None) -> pd.DataFrame:
        df = pd.DataFrame(self.to_dict(), index=index)
        return df


class FeatureEngineer:
    """Pipeline de cálculo de indicadores técnicos e DSP para o Hilberti."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def compute(self, df_ohlcv: pd.DataFrame, symbol: str = "XAUUSD") -> DSPFeatures:
        """Processa um DataFrame contendo colunas ['open', 'high', 'low', 'close', 'volume'].

        Executa o pipeline completo:
        1. Suavização WMA (WMA-4 para XAU, WMA-5 para XAG)
        2. Detrender FIR 7 barras
        3. Hilbert FIR (I1 e Q1 em quadratura)
        4. Fase e Amplitude instantânea
        5. Discriminador Homódino (período de ciclo dominante T)
        6. Roofing Filter (High-Pass + SuperSmoother)
        7. EIT (Instantaneous Trendline e slope de acumulação)
        8. EBSW (Even Better Sine Wave: Sine e LeadSine)
        9. Filtro CycleMode (|sin| > 0.85)
        10. AGC (normalização de amplitude com SMA 50)
        11. ATR 14 períodos
        """
        req_cols = {"open", "high", "low", "close"}
        if not req_cols.issubset(set(df_ohlcv.columns)):
            raise ValueError(f"DataFrame deve conter as colunas {req_cols}")

        close = df_ohlcv["close"].to_numpy(dtype=np.float64)
        high = df_ohlcv["high"].to_numpy(dtype=np.float64)
        low = df_ohlcv["low"].to_numpy(dtype=np.float64)

        # Seleciona pesos de WMA conforme o ativo
        is_xag = "XAG" in symbol.upper()
        wma_weights = (
            self.settings.wma_xag_weights if is_xag else self.settings.wma_xau_weights
        )

        # Pipeline DSP sequencial
        close_smooth = calc_wma(close, weights=wma_weights)
        detrender = calc_detrender(close_smooth)
        i1, q1 = calc_hilbert_fir(detrender, n_order=self.settings.hilbert_n)
        phase, amplitude = calc_phase_amplitude(i1, q1)

        t_min = self.settings.t_min if self.settings.t_min is not None else 6.0
        t_max = self.settings.t_max if self.settings.t_max is not None else 50.0
        period_raw, period_smooth = calc_homodyne_discriminator(
            i1,
            q1,
            alpha_smooth=self.settings.homodyne_ema_alpha,
            t_min=t_min,
            t_max=t_max,
        )

        roofing = calc_roofing_filter(
            close, hp_alpha=self.settings.roofing_alpha, ss_period=10.0
        )
        eit, eit_flat = calc_eit(
            roofing, prices=close, flat_factor=self.settings.eit_flat_factor
        )
        ebsw_sine, ebsw_leadsine = calc_ebsw(phase)
        cycle_mode = calc_cycle_mode(
            ebsw_sine,
            ebsw_leadsine,
            threshold=self.settings.cyclemode_threshold,
        )
        amplitude_norm = calc_agc(amplitude, period=self.settings.agc_sma_period)
        atr14 = calc_atr(high, low, close, period=self.settings.atr_period)

        features = DSPFeatures(
            close_smooth=close_smooth,
            detrender=detrender,
            i1=i1,
            q1=q1,
            phase=phase,
            amplitude=amplitude,
            period_raw=period_raw,
            period_smooth=period_smooth,
            roofing=roofing,
            eit=eit,
            eit_flat=eit_flat,
            ebsw_sine=ebsw_sine,
            ebsw_leadsine=ebsw_leadsine,
            cycle_mode=cycle_mode,
            amplitude_norm=amplitude_norm,
            atr14=atr14,
        )

        logger.debug(
            "DSP features calculadas: n_bars={} cycle_mode_active={}/{} period_med={:.1f}",
            len(close),
            np.sum(cycle_mode),
            len(cycle_mode),
            float(np.median(period_smooth)),
        )
        return features
