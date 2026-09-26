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
    """Max drawdown percentual a partir da curva de equity."""
    if equity_curve.empty:
        return 0.0
    peak = equity_curve.cummax()
    dd = (equity_curve - peak) / peak * 100
    return dd.min()


def sharpe_ratio(
    trades: list[dict],
    rf: float = 0.0,
    periods_per_year: int = 252 * 78,  # M5 bars por ano
) -> float:
    """Sharpe ratio a partir dos P&Ls dos trades."""
    if not trades:
        return 0.0
    pnls = [t.get("pnl", 0) for t in trades]
    mean = sum(pnls) / len(pnls)
    std = math.sqrt(sum((p - mean) ** 2 for p in pnls) / len(pnls))
    return (mean - rf) / std * math.sqrt(periods_per_year) if std > 0 else 0.0


def sortino_ratio(
    trades: list[dict],
    rf: float = 0.0,
    periods_per_year: int = 252 * 78,
) -> float:
    """Sortino ratio — só penaliza downside deviation."""
    if not trades:
        return 0.0
    pnls = [t.get("pnl", 0) for t in trades]
    mean = sum(pnls) / len(pnls)
    downside = [p - rf for p in pnls if p < rf]
    if not downside:
        return float("inf")
    dd = math.sqrt(sum(d ** 2 for d in downside) / len(downside))
    return (mean - rf) / dd * math.sqrt(periods_per_year) if dd > 0 else 0.0


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
