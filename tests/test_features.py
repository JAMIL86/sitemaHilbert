"""Testes unitários e matemáticos do módulo de DSP e Features do Hilberti.

Regras de validação obrigatórias:
1. Roda a função com uma série senoidal pura conhecida (sen(2*pi*t/20)).
2. Verifica que a saída I/Q da Transformada de Hilbert está em quadratura (fase ~90°).
3. Verifica que o CycleMode ativa quando |sin| > 0.85 ou |leadsine| > 0.85.
4. Verifica que a amplitude da EBSW (Sine e LeadSine) fica estritamente entre -1.0 e +1.0.
5. Validação de WMA, Detrender, Homodyne Discriminator, Roofing Filter, EIT, AGC e ATR.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ai.feature_engineer import (
    FeatureEngineer,
    calc_agc,
    calc_atr,
    calc_cycle_mode,
    calc_detrender,
    calc_ebsw,
    calc_eit,
    calc_hilbert_fir,
    calc_homodyne_discriminator,
    calc_phase_amplitude,
    calc_roofing_filter,
    calc_supersmoother_2p,
    calc_wma,
)
from config.settings import get_settings


# ==============================================================================
# FIXTURES E GERADORES DE SINAIS CONHECIDOS
# ==============================================================================


@pytest.fixture
def pure_sine_wave() -> tuple[np.ndarray, float, int]:
    """Gera uma onda senoidal pura conhecida: x(t) = sin(2*pi*t/20) com N=200 amostras."""
    period = 20.0
    n_samples = 200
    t = np.arange(n_samples, dtype=np.float64)
    omega = 2.0 * np.pi / period
    sine_series = np.sin(omega * t)
    return sine_series, period, n_samples


@pytest.fixture
def sample_ohlcv_df() -> pd.DataFrame:
    """Gera um DataFrame OHLCV sintético e consistente com 150 barras."""
    n_bars = 150
    t = np.arange(n_bars, dtype=np.float64)
    base_price = 2000.0 + 10.0 * np.sin(2.0 * np.pi * t / 20.0) + 0.05 * t

    high = base_price + 1.5 + np.random.uniform(0.1, 0.5, size=n_bars)
    low = base_price - 1.5 - np.random.uniform(0.1, 0.5, size=n_bars)
    close = base_price + np.random.uniform(-0.8, 0.8, size=n_bars)
    open_ = np.roll(close, 1)
    open_[0] = base_price[0]

    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n_bars, 1000),
        }
    )


# ==============================================================================
# TESTES ESPECÍFICOS DAS CONDIÇÕES OBRIGATÓRIAS
# ==============================================================================


def test_wma_known_weights():
    """Valida WMA-4 (XAU) e WMA-5 (XAG) em sequências lineares conhecidas."""
    # Teste WMA-4 com [1, 2, 3, 4] -> (4*4 + 3*3 + 2*2 + 1*1) / 10 = (16+9+4+1)/10 = 30/10 = 3.0
    series = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    w4 = calc_wma(series, weights=(4.0, 3.0, 2.0, 1.0))
    assert np.isclose(w4[3], 3.0)

    # Teste WMA-5 com [1, 2, 3, 4, 5] -> (5*5 + 4*4 + 3*3 + 2*2 + 1*1)/15 = (25+16+9+4+1)/15 = 55/15 = 3.6666667
    w5 = calc_wma(series, weights=(5.0, 4.0, 3.0, 2.0, 1.0))
    assert np.isclose(w5[4], 55.0 / 15.0)


def test_detrender_fir_linear_rejection():
    """Valida que o Detrender FIR de 7 barras atenua componente DC e tendências constantes."""
    # Série constante deve ter saída detrended nula
    const_series = np.full(50, 2500.0)
    det = calc_detrender(const_series)
    # 0.25*c + 0.75*c - 0.25*c - 0.75*c = 0
    assert np.allclose(det[6:], 0.0, atol=1e-8)


def test_hilbert_fir_quadrature_90_degrees(pure_sine_wave):
    """CONDIÇÃO OBRIGATÓRIA 2:

    Verifica que I e Q da Transformada de Hilbert FIR estão em quadratura (~90° de defasagem de fase).
    Na decomposição analítica: Q(t) é a transformada de Hilbert de I(t).
    Em um sinal senoidal puro sin(ωt), a quadratura deve resultar em cos(ωt),
    e o produto escalar médio (correlação cruzada com atraso zero) entre I e Q deve ser próximo de zero,
    enquanto a diferença de fase média fica em ~90° (pi/2 radianos).
    """
    sine_series, period, n_samples = pure_sine_wave

    det = calc_detrender(sine_series)
    i1, q1 = calc_hilbert_fir(det, n_order=3)

    # Descarte do warmup inicial e seleção de ciclos inteiros (8 períodos de 20 = 160 barras)
    i_steady = i1[30:190]
    q_steady = q1[30:190]

    # 1. Ortogonalidade: o produto escalar entre I e Q sobre ciclos completos deve ser ~0
    # A FIR discreta de 7 coeficientes de Ehlers tem defasagem de ~80° a 90° (|corr| < 0.20)
    corr = np.dot(i_steady, q_steady) / (np.linalg.norm(i_steady) * np.linalg.norm(q_steady))
    assert abs(corr) < 0.20, f"Correlação entre I e Q deveria ser ~0 (ortogonais), obtido: {corr}"

    # 2. Defasagem de fase: calcular a velocidade angular instantânea |dphi/dt|
    phase, amp = calc_phase_amplitude(i_steady, q_steady)
    unwrapped_phase = np.unwrap(phase)
    phase_diffs = np.diff(unwrapped_phase)

    # Para um período T=20, a variação de fase esperada por barra é 2*pi/20 = 0.314 rad
    expected_delta_phase = 2.0 * np.pi / period
    median_delta_phase = abs(float(np.median(phase_diffs)))
    assert np.isclose(median_delta_phase, expected_delta_phase, rtol=0.15), (
        f"Variação angular esperada ~{expected_delta_phase:.3f} rad/barra, obtido {median_delta_phase:.3f}"
    )


def test_cycle_mode_threshold_activation():
    """CONDIÇÃO OBRIGATÓRIA 3:

    Verifica que o CycleMode ativa (retorna 1) quando |sin| > 0.85 ou |leadsine| > 0.85,
    e desativa (retorna 0) quando ambos são <= 0.85.
    """
    # Casos de teste sintéticos controlados
    sine_vals = np.array([0.90, 0.50, -0.86, 0.10, 0.84, -0.95, 0.00])
    lead_vals = np.array([0.10, 0.88, 0.20, -0.90, 0.80, 0.10, 0.00])
    # Esperado: [1, 1, 1, 1, 0, 1, 0]
    expected_cycle_mode = np.array([1, 1, 1, 1, 0, 1, 0], dtype=np.int32)

    cm = calc_cycle_mode(sine_vals, lead_vals, threshold=0.85)
    assert np.array_equal(cm, expected_cycle_mode), f"Esperado {expected_cycle_mode}, obtido {cm}"

    # Teste de borda: exatamente no limiar 0.85 (não estritamente maior)
    cm_edge = calc_cycle_mode(np.array([0.85]), np.array([0.85]), threshold=0.85)
    assert cm_edge[0] == 0

    cm_over = calc_cycle_mode(np.array([0.85001]), np.array([0.0]), threshold=0.85)
    assert cm_over[0] == 1


def test_ebsw_amplitude_bounded_between_minus_one_and_plus_one(pure_sine_wave):
    """CONDIÇÃO OBRIGATÓRIA 4:

    Verifica que a amplitude da Even Better Sine Wave (Sine e LeadSine)
    fica estritamente entre -1.0 e +1.0 para todas as amostras.
    """
    sine_series, _, _ = pure_sine_wave
    det = calc_detrender(sine_series)
    i1, q1 = calc_hilbert_fir(det, n_order=3)
    phase, _ = calc_phase_amplitude(i1, q1)

    sine, lead_sine = calc_ebsw(phase)

    # Verificações estritas
    assert np.all(sine >= -1.0), f"Sine violou limite inferior: min={np.min(sine)}"
    assert np.all(sine <= 1.0), f"Sine violou limite superior: max={np.max(sine)}"
    assert np.all(lead_sine >= -1.0), f"LeadSine violou limite inferior: min={np.min(lead_sine)}"
    assert np.all(lead_sine <= 1.0), f"LeadSine violou limite superior: max={np.max(lead_sine)}"

    # Teste com fases aleatórias extremas
    random_phases = np.random.uniform(-100.0, 100.0, size=1000)
    rand_sine, rand_lead = calc_ebsw(random_phases)
    assert np.all(rand_sine >= -1.0) and np.all(rand_sine <= 1.0)
    assert np.all(rand_lead >= -1.0) and np.all(rand_lead <= 1.0)


def test_homodyne_discriminator_cycle_recovery(pure_sine_wave):
    """Valida a recuperação do período de ciclo conhecido (T=20) pelo Discriminador Homódino."""
    sine_series, period, n_samples = pure_sine_wave
    det = calc_detrender(sine_series)
    i1, q1 = calc_hilbert_fir(det, n_order=3)

    period_raw, period_smooth = calc_homodyne_discriminator(
        i1, q1, alpha_smooth=0.5, t_min=6.0, t_max=50.0
    )

    # Após período de convergência (warmup de ~30 barras)
    steady_period = period_smooth[35:]
    median_recovered_period = float(np.median(steady_period))

    assert 17.0 <= median_recovered_period <= 23.0, (
        f"Período recuperado ({median_recovered_period:.1f}) deve estar próximo do real ({period})"
    )


def test_roofing_filter_and_supersmoother():
    """Valida que o Roofing Filter e o SuperSmoother removem ruído de alta frequência e drift DC."""
    t = np.arange(100, dtype=np.float64)
    # Sinal com DC drift (1000 + 2*t) + ciclo desejado (período 20) + ruído alta frequência (período 3)
    signal = 1000.0 + 2.0 * t + 10.0 * np.sin(2.0 * np.pi * t / 20.0) + 2.0 * np.sin(2.0 * np.pi * t / 3.0)

    roofing = calc_roofing_filter(signal, hp_alpha=0.707, ss_period=10.0)
    it, is_flat = calc_eit(roofing, prices=signal, flat_factor=0.0005)

    # O roofing filter deve ter média aproximadamente zero (sem o DC drift de 1000+)
    assert abs(np.mean(roofing[30:])) < 2.0
    assert len(it) == len(signal)
    assert isinstance(is_flat, np.ndarray)


def test_agc_normalization():
    """Valida que o AGC normaliza a amplitude em torno de 1.0 para sinal estacionário."""
    # Amplitude estacionária de 5.0 com pequena variação
    n = 100
    amp = np.full(n, 5.0)
    agc_norm = calc_agc(amp, period=50)

    # Para sinal constante, após 50 períodos a normalização deve ser exatamente 1.0
    assert np.allclose(agc_norm[50:], 1.0, atol=1e-4)


def test_atr14_calculation():
    """Valida o cálculo do ATR14 com valores conhecidos."""
    high = np.array([10.0, 12.0, 11.0, 13.0, 15.0] * 10)
    low = np.array([8.0, 9.0, 10.0, 11.0, 12.0] * 10)
    close = np.array([9.0, 11.0, 10.5, 12.5, 14.0] * 10)

    atr = calc_atr(high, low, close, period=14)

    assert len(atr) == len(close)
    assert np.all(atr > 0.0)
    # ATR deve refletir o True Range típico (~2 a 3 pontos)
    assert 1.5 <= np.mean(atr[20:]) <= 4.0


def test_feature_engineer_pipeline_complete(sample_ohlcv_df):
    """Valida o pipeline completo do FeatureEngineer integrado."""
    settings = get_settings()
    engineer = FeatureEngineer(settings)

    features = engineer.compute(sample_ohlcv_df, symbol="XAUUSD")

    assert len(features.close_smooth) == len(sample_ohlcv_df)
    assert len(features.detrender) == len(sample_ohlcv_df)
    assert len(features.i1) == len(sample_ohlcv_df)
    assert len(features.q1) == len(sample_ohlcv_df)
    assert len(features.ebsw_sine) == len(sample_ohlcv_df)
    assert len(features.ebsw_leadsine) == len(sample_ohlcv_df)
    assert len(features.cycle_mode) == len(sample_ohlcv_df)
    assert len(features.atr14) == len(sample_ohlcv_df)

    # Exportação para DataFrame
    df_out = features.to_dataframe()
    assert isinstance(df_out, pd.DataFrame)
    assert df_out.shape[0] == len(sample_ohlcv_df)
    assert "ebsw_sine" in df_out.columns
    assert "cycle_mode" in df_out.columns
