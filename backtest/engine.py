"""Engine de backtest — executa V26 em dados históricos sem lookahead bias (Etapa 9).

INVARIANTE ANTI-LOOKAHEAD:
- Cada barra é processada sequencialmente (ordem cronológica estrita).
- Features DSP computadas apenas com barras ANTERIORES (shift temporal).
- Sinais V26 gerados sem conhecimento do futuro.
- SL/TP aplicados retroativamente na próxima barra (realismo de execução).

INVARIANTE DE TRADING:
- Modo SIMULAÇÃO pura — nenhuma ordem enviada ao MT5 real.
- dry_run=True obrigatório.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd
from loguru import logger

from ai.feature_engineer import FeatureEngineer
from config.settings import Settings, get_settings
from strategy.pdf_strategies import V26Strategy


@dataclass
class Trade:
    """Registro de um trade simulado."""
    entry_time: datetime
    entry_price: float
    direction: str  # "BUY" | "SELL"
    volume: float
    sl: float
    tp: Optional[float]
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None  # "SL" | "TP" | "SIGNAL_REVERSE" | "END"
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None

    def close(self, exit_time: datetime, exit_price: float, reason: str) -> None:
        """Fecha o trade e calcula P&L."""
        self.exit_time = exit_time
        self.exit_price = exit_price
        self.exit_reason = reason

        if self.direction == "BUY":
            self.pnl = (exit_price - self.entry_price) * self.volume * 100  # 1 lot XAU = $100/ponto
        else:  # SELL
            self.pnl = (self.entry_price - exit_price) * self.volume * 100

        self.pnl_pct = (self.pnl / (self.entry_price * self.volume * 100)) * 100


@dataclass
class BacktestResult:
    """Resultado agregado do backtest."""
    symbol: str
    start_date: datetime
    end_date: datetime
    initial_balance: float
    final_balance: float
    trades: list[Trade] = field(default_factory=list)
    equity_curve: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def winning_trades(self) -> int:
        return sum(1 for t in self.trades if t.pnl and t.pnl > 0)

    @property
    def losing_trades(self) -> int:
        return sum(1 for t in self.trades if t.pnl and t.pnl < 0)

    @property
    def win_rate(self) -> float:
        return (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0.0

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.trades if t.pnl is not None)

    @property
    def gross_profit(self) -> float:
        return sum(t.pnl for t in self.trades if t.pnl and t.pnl > 0)

    @property
    def gross_loss(self) -> float:
        return abs(sum(t.pnl for t in self.trades if t.pnl and t.pnl < 0))

    @property
    def profit_factor(self) -> float:
        return (self.gross_profit / self.gross_loss) if self.gross_loss > 0 else 0.0


class BacktestEngine:
    """Engine de backtest walk-forward sem lookahead bias."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.strategy = V26Strategy(self.settings)
        self.feature_eng = FeatureEngineer()
        self.initial_balance = 10_000.0
        self.current_balance = self.initial_balance
        self.open_trade: Optional[Trade] = None
        self.closed_trades: list[Trade] = []

    def run(
        self,
        df: pd.DataFrame,
        symbol: str = "XAUUSD-VIP",
    ) -> BacktestResult:
        """Executa o backtest em dados históricos.

        Args:
            df: DataFrame com colunas [time, open, high, low, close, tick_volume]
            symbol: Símbolo negociado

        Returns:
            BacktestResult com trades e equity curve
        """
        if df.empty or len(df) < 200:
            raise ValueError(f"Dados insuficientes: {len(df)} barras (mín 200)")

        logger.info("Iniciando backtest: {} barras de {} a {}", len(df), df["time"].iloc[0], df["time"].iloc[-1])

        equity_history = []

        for i in range(200, len(df)):
            window = df.iloc[:i].copy()  # ANTI-LOOKAHEAD: apenas barras anteriores
            current_bar = df.iloc[i]

            try:
                features = self.feature_eng.compute(window)
                features_df = features.to_dataframe()

                if features_df.empty:
                    continue

                decision = self.strategy.signal(
                    features_df,
                    symbol=symbol,
                    current_price=float(current_bar["close"]),
                    current_spread=0.0,
                )

                self._process_signal(decision, current_bar, symbol)

            except Exception as e:
                logger.warning("Erro na barra {}: {}", i, e)
                continue

            equity_history.append({
                "time": current_bar["time"],
                "balance": self.current_balance,
                "equity": self.current_balance + (self.open_trade.pnl if self.open_trade and self.open_trade.pnl else 0),
            })

        if self.open_trade:
            last_bar = df.iloc[-1]
            self.open_trade.close(last_bar["time"], float(last_bar["close"]), "END")
            self.current_balance += self.open_trade.pnl or 0.0
            self.closed_trades.append(self.open_trade)
            self.open_trade = None

        equity_curve = pd.DataFrame(equity_history)

        return BacktestResult(
            symbol=symbol,
            start_date=df["time"].iloc[0],
            end_date=df["time"].iloc[-1],
            initial_balance=self.initial_balance,
            final_balance=self.current_balance,
            trades=self.closed_trades,
            equity_curve=equity_curve,
        )

    def _process_signal(self, decision, current_bar, symbol: str) -> None:
        """Processa sinal V26 e executa lógica de SL/TP."""
        if self.open_trade:
            self._check_exit(current_bar)

        if not self.open_trade and decision and decision.signal in ("BUY", "SELL"):
            volume = 0.01  # lote fixo (simplificação)
            sl_dist = 50.0  # pontos (simplificação)
            entry_price = float(current_bar["close"])

            if decision.signal == "BUY":
                sl = entry_price - (sl_dist * 0.01)
            else:
                sl = entry_price + (sl_dist * 0.01)

            self.open_trade = Trade(
                entry_time=current_bar["time"],
                entry_price=entry_price,
                direction=decision.signal,
                volume=volume,
                sl=sl,
                tp=None,
            )
            logger.debug("Trade aberto: {} @ {}", decision.signal, entry_price)

    def _check_exit(self, current_bar) -> None:
        """Verifica SL/TP na barra atual."""
        if not self.open_trade:
            return

        low = float(current_bar["low"])
        high = float(current_bar["high"])
        close = float(current_bar["close"])

        if self.open_trade.direction == "BUY":
            if low <= self.open_trade.sl:
                self.open_trade.close(current_bar["time"], self.open_trade.sl, "SL")
            elif self.open_trade.tp and high >= self.open_trade.tp:
                self.open_trade.close(current_bar["time"], self.open_trade.tp, "TP")

        elif self.open_trade.direction == "SELL":
            if high >= self.open_trade.sl:
                self.open_trade.close(current_bar["time"], self.open_trade.sl, "SL")
            elif self.open_trade.tp and low <= self.open_trade.tp:
                self.open_trade.close(current_bar["time"], self.open_trade.tp, "TP")

        if self.open_trade.exit_time:
            self.current_balance += self.open_trade.pnl or 0.0
            self.closed_trades.append(self.open_trade)
            logger.debug("Trade fechado: {} → P&L {:.2f}", self.open_trade.exit_reason, self.open_trade.pnl or 0)
            self.open_trade = None
