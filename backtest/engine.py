"""Engine de backtest — executa V26 em dados históricos sem lookahead bias (Etapa 9).

ANTI-LOOKAHEAD:
- Cada barra é processada em ordem cronológica estrita.
- A janela de features é `df.iloc[start:i]` — barra `i` NUNCA entra na própria
  janela de decisão. Só entra na janela da PRÓXIMA iteração.
- Nenhum `.shift(-n)`, `.rolling(center=True)` ou `bfill()` sobre a série.

GESTÃO DE POSIÇÃO (fonte única de verdade):
- As saídas NÃO são implementadas aqui. O engine delega a
  `V26Strategy.manage_open_trade()`, que aplica as regras do PDF: breakeven
  (+500 pts), parciais automáticas (30%/30%), trailing AGC adaptativo e saída
  por inversão de fase 180°. O PDF declara explicitamente "SEM Take Profit
  fixo" — por isso não existe TP, e nenhum alvo de preço é inventado.
- O engine só simula o preenchimento: se o preço alcançar o SL vigente, o
  trade fecha.

PARÂMETROS:
- Todos vêm de `settings` ou de `SignalDecision`. Nada é inventado aqui.
- `initial_balance` é explícito no construtor (padrão 10 000 USD).

TRADING:
- Simulação pura. `Executor` nunca importado, `order_send` nunca chamado,
  `dry_run` nunca alterado. Zero escrita em `shadow_log`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger

from ai.feature_engineer import FeatureEngineer
from config.settings import Settings, get_settings
from strategy.pdf_strategies import Position, V26Strategy

MIN_BARS = 200  # mesmo piso usado pelo dashboard para computar features


@dataclass
class Trade:
    """Registro de um trade simulado, incluindo o resultado das parciais."""
    entry_time: object
    entry_price: float
    direction: str  # "BUY" | "SELL"
    volume: float
    sl: float
    sl_points: float
    exit_time: Optional[object] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None  # "SL" | "TRAIL" | "END"
    pnl: Optional[float] = None
    partials: list[dict] = field(default_factory=list)

    def close(self, exit_time, exit_price: float, reason: str) -> None:
        """Fecha o trade e calcula P&L em USD.

        XAUUSD: 1.00 lot = 100 oz = 100 USD por 1.00 de variação de preço.
        Com volume em lotes: pnl = delta_preco * volume * 100. As parciais
        entram como P&L próprio e reduzem o volume restante.
        """
        self.exit_time = exit_time
        self.exit_price = exit_price
        self.exit_reason = reason

        delta = (
            exit_price - self.entry_price
            if self.direction == "BUY"
            else self.entry_price - exit_price
        )
        final = delta * self.volume * 100.0
        self.pnl = final + sum(p["pnl"] for p in self.partials)


@dataclass
class BacktestResult:
    """Resultado agregado do backtest."""
    symbol: str
    start_date: object
    end_date: object
    initial_balance: float
    final_balance: float
    trades: list[Trade] = field(default_factory=list)
    equity_curve: pd.DataFrame = field(default_factory=pd.DataFrame)
    bars_processed: int = 0
    bars_skipped: int = 0

    def to_dict(self) -> dict:
        """Serializa para dict (consumido por metrics.py e report.py)."""
        return {
            "symbol": self.symbol,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "initial_balance": self.initial_balance,
            "final_balance": self.final_balance,
            "trades": [t.__dict__.copy() for t in self.trades],
            "equity_curve": (
                self.equity_curve["equity"]
                if not self.equity_curve.empty
                else pd.Series(dtype=float)
            ),
            "bars_processed": self.bars_processed,
            "bars_skipped": self.bars_skipped,
        }


class BacktestEngine:
    """Engine de backtest sequencial, sem lookahead bias."""

    def __init__(self, settings: Optional[Settings] = None, initial_balance: float = 10_000.0):
        self.settings = settings or get_settings()
        self.strategy = V26Strategy(self.settings)
        self.feature_eng = FeatureEngineer()
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.open_trade: Optional[Trade] = None
        self.position: Optional[Position] = None
        self.closed_trades: list[Trade] = []
        self._ticket = 0

    def reset(self) -> None:
        """Zera o estado entre execuções (permite reuso do engine)."""
        self.current_balance = self.initial_balance
        self.open_trade = None
        self.position = None
        self.closed_trades = []
        self._ticket = 0

    def run(self, df: pd.DataFrame, symbol: Optional[str] = None) -> BacktestResult:
        """Executa o backtest barra a barra.

        Args:
            df: DataFrame com [time, open, high, low, close, tick_volume],
                ordenado cronologicamente.
            symbol: Símbolo negociado (default: settings.symbol_xau).

        Returns:
            BacktestResult com trades, curva de equity e contadores.
        """
        df = self._prepare(df)
        symbol = symbol or self.settings.symbol_xau

        if len(df) < MIN_BARS:
            raise ValueError(f"Dados insuficientes: {len(df)} barras (mín {MIN_BARS})")

        self.reset()
        logger.info(
            "Backtest {}: {} barras de {} a {}",
            symbol, len(df), df["time"].iloc[0], df["time"].iloc[-1],
        )

        window = min(self.settings.max_window, 1000)
        equity_rows: list[dict] = []
        skipped = 0

        for i in range(MIN_BARS, len(df)):
            bar = df.iloc[i]
            features = self._features(df, i, window)

            if features is None:
                skipped += 1
                equity_rows.append(self._equity_row(bar))
                continue

            price = float(bar["close"])

            # 1) Fecha por stop ANTES de gerenciar: se o preço já matou a
            #    posição, a gestão da barra é irrelevante.
            if self._stop_hit(bar):
                self._close(bar["time"], self.open_trade.sl, self._exit_reason())
            else:
                self._manage(features, price, bar["time"])

            # 2) Abre posição apenas se não houver uma aberta.
            if self.open_trade is None:
                self._maybe_open(features, df["time"].iloc[i], symbol, price)

            equity_rows.append(self._equity_row(bar))

        if self.open_trade is not None:
            last = df.iloc[-1]
            self._close(last["time"], float(last["close"]), "END")

        result = BacktestResult(
            symbol=symbol,
            start_date=df["time"].iloc[0],
            end_date=df["time"].iloc[-1],
            initial_balance=self.initial_balance,
            final_balance=self.current_balance,
            trades=list(self.closed_trades),
            equity_curve=pd.DataFrame(equity_rows),
            bars_processed=len(df) - MIN_BARS,
            bars_skipped=skipped,
        )
        logger.info(
            "Concluído: {} trades, saldo {} -> {}",
            len(self.closed_trades), self.initial_balance, self.current_balance,
        )
        return result

    # --- features e janela -------------------------------------------------

    def _features(self, df: pd.DataFrame, i: int, window: int):
        """Features da barra i-1 (janela SOMENTE do passado)."""
        history = df.iloc[max(0, i - window):i]
        if len(history) < MIN_BARS:
            return None
        try:
            return self.feature_eng.compute(history)
        except Exception as exc:  # janela degenerada (ex.: pré-abertura plana)
            logger.debug("Features indisponíveis: {}", exc)
            return None

    def _maybe_open(self, features, when, symbol: str, price: float) -> None:
        """Abre trade quando V26 emite sinal e não há posição aberta.

        Recebe as MESMAS features já computadas para a barra atual — a janela
        é o passado para as duas decisões, então recalcular só dobraria o
        custo do backtest sem mudar o resultado.
        """
        decision = self.strategy.signal(
            features, symbol=symbol, current_price=price, current_spread=0.0
        )
        if decision is None or decision.signal not in ("BUY", "SELL"):
            return
        if decision.sl_points <= 0:
            return

        sl = float(decision.initial_sl) or (
            price - decision.sl_points
            if decision.signal == "BUY"
            else price + decision.sl_points
        )

        self._ticket += 1
        self.open_trade = Trade(
            entry_time=when,
            entry_price=price,
            direction=decision.signal,
            volume=self.settings.min_volume,
            sl=sl,
            sl_points=float(decision.sl_points),
        )
        # `entry_phase` é lido pelo V26 para a saída por inversão de fase.
        self.position = Position(
            ticket=self._ticket,
            symbol=symbol,
            order_type=decision.signal,
            volume=self.settings.min_volume,
            open_price=price,
            sl=sl,
            open_time=when,
            entry_phase=float(features.phase[-1]),
        )
        logger.debug("Aberto {} @ {} SL {}", decision.signal, price, sl)

    # --- gestão e saída ----------------------------------------------------

    def _stop_hit(self, bar) -> bool:
        """O preço da barra alcançou o SL vigente?"""
        if self.open_trade is None:
            return False
        low, high = float(bar["low"]), float(bar["high"])
        return (
            low <= self.open_trade.sl
            if self.open_trade.direction == "BUY"
            else high >= self.open_trade.sl
        )

    def _exit_reason(self) -> str:
        """Distingue stop inicial de stop movido (trailing/breakeven).

        Reportar tudo como "SL" esconderia que a maior parte das saídas
        lucrativas veio do trailing adaptativo do V26, não do stop original.
        """
        if self.open_trade is None:
            return "SL"
        moved = (
            self.open_trade.sl > self.open_trade.entry_price
            if self.open_trade.direction == "BUY"
            else self.open_trade.sl < self.open_trade.entry_price
        )
        return "TRAIL" if moved else "SL"

    def _manage(self, features, price: float, when) -> None:
        """Delega ao V26 e aplica a ação emitindo fill e P&L."""
        if self.open_trade is None or self.position is None:
            return

        action = self.strategy.manage_open_trade(self.position, features, price)
        kind = getattr(action, "action", None)

        if kind == "MODIFY_SL" and action.new_sl is not None:
            # Trailing é MONOTÔNICO: o SL nunca afasta do preço.
            if self.position.order_type == "BUY" and action.new_sl > self.open_trade.sl:
                self.open_trade.sl = action.new_sl
                self.position.sl = action.new_sl
            elif self.position.order_type == "SELL":
                worse = self.open_trade.sl == 0.0 or action.new_sl < self.open_trade.sl
                if worse and action.new_sl > 0.0:
                    self.open_trade.sl = action.new_sl
                    self.position.sl = action.new_sl

        elif kind == "PARTIAL_CLOSE" and action.volume_to_close > 0:
            self._partial(when, price, action)

    def _partial(self, when, price: float, action) -> None:
        """Fecha parte do volume e realiza o P&L correspondente."""
        volume = min(action.volume_to_close, self.open_trade.volume)
        if volume <= 0:
            return
        delta = (
            price - self.open_trade.entry_price
            if self.open_trade.direction == "BUY"
            else self.open_trade.entry_price - price
        )
        pnl = delta * volume * 100.0

        self.current_balance += pnl
        self.open_trade.volume = round(self.open_trade.volume - volume, 4)
        self.open_trade.partials.append(
            {
                "time": when,
                "volume": volume,
                "price": price,
                "pnl": pnl,
                "reason": action.reason,
            }
        )
        if self.position is not None:
            self.position.volume = self.open_trade.volume
        logger.debug("Parcial {:.2f} @ {} P&L {:.2f}", volume, price, pnl)

    def _close(self, when, price: float, reason: str) -> None:
        if self.open_trade is None:
            return
        if self.open_trade.volume > 0:
            self.open_trade.close(when, price, reason)
            self.current_balance += self.open_trade.pnl or 0.0
        else:
            # Todo o volume já saiu nas parciais.
            self.open_trade.exit_time = when
            self.open_trade.exit_price = price
            self.open_trade.exit_reason = reason
            self.open_trade.pnl = sum(p["pnl"] for p in self.open_trade.partials)
        self.closed_trades.append(self.open_trade)
        logger.debug("Fechado {} P&L {:.2f}", reason, self.open_trade.pnl or 0.0)
        self.open_trade = None
        self.position = None

    # --- curva de equity ---------------------------------------------------

    def _equity_row(self, bar) -> dict:
        """Balance + P&L flutuante da posição aberta."""
        floating = 0.0
        if self.open_trade is not None:
            price = float(bar["close"])
            delta = (
                price - self.open_trade.entry_price
                if self.open_trade.direction == "BUY"
                else self.open_trade.entry_price - price
            )
            floating = delta * self.open_trade.volume * 100.0
        return {
            "time": bar["time"],
            "balance": self.current_balance,
            "equity": self.current_balance + floating,
        }

    @staticmethod
    def _prepare(df: pd.DataFrame) -> pd.DataFrame:
        """Normaliza tipos e rejeita séries fora de ordem."""
        out = df.copy()
        out["time"] = pd.to_datetime(out["time"])
        if not out["time"].is_monotonic_increasing:
            # Falhar expõe o dado ruim; ordenar automaticamente o esconderia.
            raise ValueError("Dados fora de ordem cronológica.")
        for col in ("open", "high", "low", "close"):
            out[col] = out[col].astype("float64")
        return out.reset_index(drop=True)
