"""Métricas de backtest — win rate, profit factor, max DD, Sharpe, Sortino (Etapa 9).

INVARIANTE:
- Todas as métricas derivam SOMENTE da lista de trades fechados.
- Sem dados futuros, sem otimização, sem curva de ajuste.
"""

from __future__ import annotations

import math
from typing import Optional

import pandas as pd


def win_rate(trades: list[dict]) -> float:
    """Percentual de trades positivos."""
    if not trades:
        return 0.0
    w = sum(1 for t in trades if t.get("pnl", 0) > 0)
    return w / len(trades) * 100


def profit_factor(trades: list[dict]) -> float:
    """Gross Profit / Gross Loss. 0 se sem losses ou sem trades."""
    gross_profit = sum(t.get("pnl", 0) for t in trades if t.get("pnl", 0) > 0)
    gross_loss = abs(sum(t.get("pnl", 0) for t in trades if t.get("pnl", 0) < 0))
    return gross_profit / gross_loss if gross_loss > 0 else 0.0


def max_drawdown(equity_curve: pd.Series) -> float:
    """Max drawdown como MAGNITUDE positiva em % (0 se curva vazia/crescente).

    Convenção: retorna 10.0 para uma queda de 10%. O sinal é perdido de
    propósito — todo relatório apresenta drawdown como risco, não como ganho.
    """
    if equity_curve.empty:
        return 0.0
    peak = equity_curve.cummax()
    dd = (equity_curve - peak) / peak * 100
    return abs(dd.min())


def _periods_per_year(trades: list[dict]) -> float:
    """Trades por ano, derivado da densidade REAL da amostra.

    Fixar 252*78 (um trade por barra) inflaria o Sharpe em ordens de
    grandeza num conjunto com poucos trades. A anualização usa o período
    efetivo coberto pelos timestamps dos trades.
    """
    stamps = [t.get("exit_time") or t.get("entry_time") for t in trades]
    stamps = [pd.Timestamp(s) for s in stamps if s is not None]
    if len(stamps) < 2:
        return 1.0
    days = (max(stamps) - min(stamps)).total_seconds() / 86_400.0
    if days <= 0:
        return 1.0
    return len(trades) / (days / 365.25)


def sharpe_ratio(trades: list[dict], rf: float = 0.0) -> float:
    """Sharpe anualizado dos P&Ls por trade."""
    if not trades:
        return 0.0
    pnls = [t.get("pnl", 0) for t in trades]
    mean = sum(pnls) / len(pnls)
    std = math.sqrt(sum((p - mean) ** 2 for p in pnls) / len(pnls))
    if std == 0:
        return 0.0
    return (mean - rf) / std * math.sqrt(_periods_per_year(trades))


def sortino_ratio(trades: list[dict], rf: float = 0.0) -> float:
    """Sortino anualizado — só penaliza desvio de downside."""
    if not trades:
        return 0.0
    pnls = [t.get("pnl", 0) for t in trades]
    mean = sum(pnls) / len(pnls)
    downside = [p - rf for p in pnls if p < rf]
    if not downside:
        return float("inf")
    dd = math.sqrt(sum(d ** 2 for d in downside) / len(downside))
    if dd == 0:
        return float("inf")
    return (mean - rf) / dd * math.sqrt(_periods_per_year(trades))


def compute_metrics(result: dict) -> dict:
    """Computa todas as métricas a partir do resultado do engine.

    Args:
        result: dict com chaves "trades" (list[dict]) e "equity_curve" (pd.Series)

    Returns:
        Dict com todas as métricas calculadas
    """
    trades = result.get("trades", [])
    equity = result.get("equity_curve", pd.Series(dtype=float))

    return {
        "total_trades": len(trades),
        "winning_trades": sum(1 for t in trades if t.get("pnl", 0) > 0),
        "losing_trades": sum(1 for t in trades if t.get("pnl", 0) < 0),
        "win_rate_pct": win_rate(trades),
        "profit_factor": profit_factor(trades),
        "max_drawdown_pct": max_drawdown(equity),
        "sharpe_ratio": sharpe_ratio(trades),
        "sortino_ratio": sortino_ratio(trades),
        "total_pnl": sum(t.get("pnl", 0) for t in trades),
        "gross_profit": sum(t.get("pnl", 0) for t in trades if t.get("pnl", 0) > 0),
        "gross_loss": abs(sum(t.get("pnl", 0) for t in trades if t.get("pnl", 0) < 0)),
    }
