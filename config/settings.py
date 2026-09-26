"""Credenciais MT5 via .env e parâmetros dos modelos.

Valores extraídos dos PDFs entram com o número do documento.
Parâmetros que os PDFs NÃO numeram ficam None com # TODO: calibrar via backtest.
Não inventar defaults operacionais.
"""

from functools import lru_cache
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


Signal = Literal["BUY", "SELL", "HOLD"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Broker (execução somente) ---
    mt5_login: Optional[int] = Field(default=None, alias="MT5_LOGIN")
    mt5_password: Optional[str] = Field(default=None, alias="MT5_PASSWORD")
    mt5_server: Optional[str] = Field(default=None, alias="MT5_SERVER")
    mt5_path: Optional[str] = Field(default=None, alias="MT5_PATH")
    mt5_symbol: str = Field(default="XAUUSD", alias="MT5_SYMBOL")
    dry_run: bool = Field(default=True, alias="DRY_RUN")
    live_trading: bool = Field(default=False, alias="LIVE_TRADING")
    confirm_live: Optional[str] = Field(default=None, alias="CONFIRM_LIVE")

    # --- Regras de plataforma (CLAUDE.md, não estão nos PDFs) ---
    magic_number: int = 20250924
    risk_percent_per_trade: float = 1.0  # 1% por trade
    daily_stop_percent: float = 3.0  # stop diário 3%
    timeframe: str = "M5"
    max_volume: float = 0.10  # Lote máximo absoluto por segurança
    min_volume: float = 0.01  # Lote mínimo padrão
    min_sl_distance_pts: float = 50.0  # Distância mínima do SL/TP em pontos
    allowed_symbols: tuple[str, ...] = ("XAUUSD", "XAGUSD")
    max_reconnect_attempts: int = 3  # Máximo de tentativas de reconexão MT5
    reconnect_delay_seconds: float = 2.0

    # --- Ativos (podem ter sufixo de corretora, ex: XAUUSD-VIP) ---
    symbol_xau: str = Field(default="XAUUSD", alias="MT5_SYMBOL_XAU")
    symbol_xag: str = Field(default="XAGUSD", alias="MT5_SYMBOL_XAG")

    # --- WMA (V26 §1.1 / WCE Listing 1) ---
    wma_xau_weights: tuple[float, ...] = (4.0, 3.0, 2.0, 1.0)  # /10
    wma_xag_weights: tuple[float, ...] = (5.0, 4.0, 3.0, 2.0, 1.0)  # /15

    # --- Hilbert (V26 §1.3 / WCE n=3 operacional) ---
    hilbert_n: int = 3

    # --- Homodyne (V26 §1.5) ---
    homodyne_ema_alpha: float = 0.5
    t_min: Optional[float] = None  # TODO: calibrar via backtest
    t_max: Optional[float] = None  # TODO: calibrar via backtest

    # --- ISOM (V26 §1.6 / WCE) ---
    isom_dx_percent: Optional[float] = None  # TODO: calibrar via backtest
    isom_bin_minutes: Optional[int] = None  # TODO: calibrar via backtest
    isom_low_dc_cutoff: Optional[float] = None  # TODO: calibrar via backtest

    # --- Roofing / EIT / EBSW / CycleMode (V26 §03) ---
    roofing_alpha: float = 0.707  # corte em 0.5 × período mínimo
    eit_flat_factor: float = 0.0005  # |IT-IT[1]| < 0.0005 * price
    cyclemode_threshold: float = 0.85
    agc_sma_period: int = 50

    # --- Acumulação / ruptura (V26 §04) — N e threshold_atr NÃO estão no PDF ---
    accumulation_energy_n: Optional[int] = None  # TODO: calibrar via backtest
    accumulation_energy_factor: float = 0.5  # Roofing_energy < 0.5 * SMA(energy, N)
    breakout_threshold_atr: Optional[float] = None  # TODO: calibrar via backtest

    # --- Spread (decisão Etapa 1: default 0.15; live lê MT5) ---
    max_spread_atr_factor_default: float = 0.15
    max_spread_atr_factor_xau: float = 0.10  # frase específica V26 §4.5
    max_spread_atr_factor_xag: float = 0.20
    spread_limit_manual: Optional[float] = None  # TODO: calibrar via backtest

    # --- Modelo ativo ---
    # "v26" = V26 Precision Accumulation Breakout — padrão.
    # "wce" = WCE 2014 (Hilbert + ISOM). Implementado e testado, mas
    #         REBAIXADO de primário em 2026-09-26: o WCE medido é o artigo
    #         MENOS o ISOM usado como ENTRADA do Hilbert (não como filtro —
    #         ver docs/decisoes_tecnicas.md §9.6), mais um stop de outra
    #         fonte. O PDF reporta PF 1.0, ou seja, break-even. Ver
    #         docs/handoff.md §13 para os gates de re-promoção.
    # Nenhum dos dois é removido: `python -m backtest.engine --model wce`.
    active_model: Literal["wce", "v26"] = Field(
        default="v26", alias="ACTIVE_MODEL"
    )

    # --- Gestão V26 §07 (sem TP fixo) ---
    atr_period: int = 14
    sl_atr_cap: float = 2.0  # SL_pts = ATR14 * min(2.0, T_final/10)
    sl_period_divisor: float = 10.0
    inp_be_pts: float = 500.0
    inp_be_spread: Optional[float] = None  # TODO: calibrar via backtest
    inp_parcial1_pct: float = 30.0
    inp_parcial2_pct: float = 30.0
    inp_parcial1_pts: Optional[float] = None  # TODO: calibrar via backtest
    inp_parcial2_pts: Optional[float] = None  # TODO: calibrar via backtest
    inp_trail_start: Optional[float] = None  # TODO: calibrar via backtest
    inp_trail_base_pct: Optional[float] = None  # TODO: calibrar via backtest
    cycle_strength_on: float = 1.0
    cycle_strength_off: float = 0.6
    phase_exit_radians: float = 3.141592653589793  # π — saída 180°
    trail_after_180_factor: float = 0.5

    # --- Cooldown (V26 §9.3) ---
    inp_cooldown_bars: int = 3
    max_window: int = 1000

    # --- Lote (V26 §7.1) ---
    inp_lot_fix: Optional[float] = None  # None = lote dinâmico
    min_lot: Optional[float] = None  # preenchido pelo broker em runtime
    max_lot: Optional[float] = None

    # --- ML Cabeça 3 (shadow na v1) ---
    isom_ml_lr: float = 0.001
    isom_ml_target_winrate: float = 0.58
    head3_shadow: bool = True  # calcula e loga; NÃO filtra entrada
    head4_shadow: bool = True  # calcula e loga; NÃO filtra entrada
    # WCE 2014 é medido e testado, mas não é o que executa: em 2026-09-26 o
    # edge-strategy-reviewer o rebaixou de primário (handoff §13). A flag
    # volta a True porque o log do router depende dela para dizer a verdade.
    wce_shadow: bool = True

    # --- Loop ---
    poll_seconds: float = 1.0
    hud_timer_ms: int = 500  # V26 §9.3


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
