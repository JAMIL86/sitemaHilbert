"""Testes do backtest (Etapa 9 FASE 1)."""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest.metrics import (
    compute_metrics,
    max_drawdown,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    win_rate,
)
from backtest.report import build_markdown_report, PALETTE


# --- Teste 1: métricas básicas (win rate, PF) ------------------------------

def test_win_rate_and_profit_factor():
    trades = [
        {"pnl": 100.0},
        {"pnl": -50.0},
        {"pnl": 200.0},
        {"pnl": -25.0},
    ]
    assert win_rate(trades) == pytest.approx(50.0)
    # GP = 300, GL = 75 -> PF = 4.0
    assert profit_factor(trades) == pytest.approx(4.0)


def test_profit_factor_zero_when_no_losses():
    trades = [{"pnl": 10.0}, {"pnl": 20.0}]
    assert profit_factor(trades) == 0.0  # gross_loss == 0 -> 0.0


def test_empty_trades_all_metrics_zero():
    empty = []
    assert win_rate(empty) == 0.0
    assert profit_factor(empty) == 0.0
    assert sharpe_ratio(empty) == 0.0
    assert sortino_ratio(empty) == 0.0
    assert max_drawdown(pd.Series(dtype=float)) == 0.0


# --- Teste 2: Sharpe / Sortino -----------------------------------------------

def test_sharpe_and_sortino_positive_on_consistent_gains():
    trades = [{"pnl": float(p)} for p in (8, 10, 12, 9, 11, 13, 10, 9, 12, 11)]
    assert sharpe_ratio(trades) > 0
    assert sortino_ratio(trades) > 0


def test_sortino_infinite_without_downside():
    # Sem perdas -> downside vazio -> infinito
    assert sortino_ratio([{"pnl": 10.0}] * 10) == float("inf")


def test_sharpe_zero_when_all_trades_identical():
    trades = [{"pnl": 5.0}] * 5
    assert sharpe_ratio(trades) == 0.0  # std == 0


# --- Teste 3: max drawdown ---------------------------------------------------

def test_max_drawdown_percent():
    equity = pd.Series([1000.0, 1200.0, 900.0, 1100.0, 800.0, 1000.0])
    # Peak 1200 -> trough 800 = -33.33%, reportado como magnitude positiva
    assert max_drawdown(equity) == pytest.approx(33.33, abs=0.01)


def test_max_drawdown_zero_on_monotonic_growth():
    equity = pd.Series([1000.0, 1100.0, 1200.0, 1300.0])
    assert max_drawdown(equity) == pytest.approx(0.0)


# --- Teste 4: compute_metrics agrega tudo -----------------------------------

def test_compute_metrics_full_dict():
    trades = [
        {"pnl": 100.0, "direction": "BUY"},
        {"pnl": -40.0, "direction": "SELL"},
        {"pnl": 60.0, "direction": "BUY"},
    ]
    equity = pd.Series([10000.0, 10100.0, 10060.0, 10120.0])
    m = compute_metrics({"trades": trades, "equity_curve": equity})

    assert m["total_trades"] == 3
    assert m["winning_trades"] == 2
    assert m["losing_trades"] == 1
    assert m["win_rate_pct"] == pytest.approx(66.67, abs=0.1)
    assert m["gross_profit"] == pytest.approx(160.0)
    assert m["gross_loss"] == pytest.approx(40.0)
    assert m["profit_factor"] == pytest.approx(4.0)
    assert m["total_pnl"] == pytest.approx(120.0)
    assert m["max_drawdown_pct"] >= 0  # magnitude positiva


# --- Teste 5: invariantes anti-lookahead / anti-trading --------------------

def test_backtest_modules_never_call_order_send():
    """Nenhum módulo de backtest envia ordem ao MT5 real."""
    for mod in ("engine.py", "downloader.py", "metrics.py", "report.py"):
        path = Path("backtest") / mod
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        code_refs: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                code_refs.add(node.id)
            elif isinstance(node, ast.Attribute):
                code_refs.add(node.attr)
        for forbidden in ("order_send", "Executor", "positions_get"):
            assert forbidden not in code_refs, f"{mod} não deve referenciar {forbidden}"


def test_backtest_uses_temporal_split_not_random():
    """Anti-lookahead: split deve ser temporal (iloc), nunca random."""
    path = Path("backtest/engine.py")
    source = path.read_text(encoding="utf-8")

    # Nenhuma chamada a train_test_split (sklearn) ou np.random permutação
    assert "train_test_split" not in source
    assert "sample(" not in source  # df.sample() = aleatório
    assert "iloc" in source  # split temporal por posição


def test_dry_run_still_true_with_backtest_present():
    """REGRA: backtest não altera dry_run=True / live_trading=False."""
    from config.settings import Settings

    s = Settings()
    assert s.dry_run is True
    assert s.live_trading is False


# --- Teste 6: relatório markdown --------------------------------------------

def test_build_markdown_report_contains_key_sections():
    result = {
        "symbol": "XAUUSD-VIP",
        "start_date": "2026-01-01",
        "end_date": "2026-06-30",
        "initial_balance": 10_000.0,
        "final_balance": 10_500.0,
        "trades": [
            {"pnl": 100.0, "direction": "BUY", "entry_time": "2026-02-01", "entry_price": 2000.0, "exit_reason": "REVERSE"},
            {"pnl": -50.0, "direction": "SELL", "entry_time": "2026-03-01", "entry_price": 2010.0, "exit_reason": "SL"},
        ],
        "equity_curve": pd.Series([10_000.0, 10_500.0]),
    }
    md = build_markdown_report(result)

    assert "# Backtest" in md
    assert "XAUUSD-VIP" in md
    assert "Win rate" in md
    assert "Profit factor" in md
    assert "Max drawdown" in md
    assert "REVERSE" in md and "SL" in md


def test_report_is_ascii_safe():
    """O relatório roda em console Windows cp1252 — sem emoji/arrows."""
    md = build_markdown_report({"symbol": "XAUUSD-VIP", "trades": []})
    md.encode("cp1252")  # levanta UnicodeEncodeError se violar


def test_equity_figure_uses_single_y_axis():
    """Regra dataviz: nunca dois eixos Y de escalas diferentes."""
    from backtest.report import build_equity_figure

    n = 50
    equity = pd.DataFrame({
        "time": pd.date_range("2026-01-01", periods=n, freq="5min"),
        "equity": np.linspace(10_000.0, 10_500.0, n),
        "drawdown_pct": np.zeros(n),
    })
    fig = build_equity_figure(equity)

    # Nenhum trace pode declarar eixo secundário
    assert all(t.yaxis is None or t.yaxis == "y" for t in fig.data)
    assert len(fig.data) == 2  # equity + drawdown


def test_palette_colors_are_valid_hex():
    """Paleta do relatório usa apenas hex de 6 dígitos."""
    for name, color in PALETTE.items():
        assert color.startswith("#"), f"{name} deve começar com #"
        assert len(color) == 7, f"{name} deve ter 7 caracteres (#RRGGBB)"
        int(color[1:], 16)  # válido como hex


# --- Teste 7: engine — anti-lookahead no comportamento, não no texto --------

def _synthetic(n: int = 600, seed: int = 7) -> pd.DataFrame:
    """Série OHLCV sintética determinística."""
    rng = np.random.default_rng(seed)
    close = 2350.0 + np.cumsum(rng.normal(0, 2.5, n))
    op = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame({
        "time": pd.date_range("2026-01-05", periods=n, freq="5min"),
        "open": op,
        "high": np.maximum(op, close) + np.abs(rng.normal(0, 1.2, n)),
        "low": np.minimum(op, close) - np.abs(rng.normal(0, 1.2, n)),
        "close": close,
        "tick_volume": rng.integers(80, 400, n).astype(np.int64),
    })


def test_engine_rejects_insufficient_data():
    from backtest.engine import BacktestEngine, MIN_BARS

    with pytest.raises(ValueError, match="insuficientes"):
        BacktestEngine().run(_synthetic(50))


def test_engine_rejects_out_of_order_data():
    """Ordenar automaticamente esconderia dado ruim — falhar é o correto."""
    from backtest.engine import BacktestEngine

    df = _synthetic(300)
    shuffled = pd.concat([df.iloc[150:], df.iloc[:150]]).reset_index(drop=True)
    with pytest.raises(ValueError, match="ordem cronol"):
        BacktestEngine().run(shuffled)


def test_engine_never_sees_the_current_or_future_bar():
    """ANTICORRIDA CENTRAL: a janela de features para na barra anterior.

    Espiona `FeatureEngineer.compute` e compara o último timestamp recebido
    com o timestamp da barra que o engine está processando. Se qualquer barra
    atual ou futura entrar, o teste falha.
    """
    from backtest.engine import MIN_BARS, BacktestEngine

    df = _synthetic(400)
    seen: list[tuple] = []
    engine = BacktestEngine()

    original = engine.feature_eng.compute

    def spy(history):
        seen.append((history["time"].iloc[-1], len(history)))
        return original(history)

    engine.feature_eng.compute = spy
    result = engine.run(df)

    assert seen, "o engine deve ter chamado compute()"
    # Cada janelaobservada termina ANTES da barra que aENGINE está avaliando.
    # Reconstruímos essa barra a partir do offset: run() começa em MIN_BARS.
    for idx, (last_time, _) in enumerate(seen):
        current_bar_time = df["time"].iloc[idx + MIN_BARS]
        assert last_time < current_bar_time, (
            f"janela incluiu a barra atual/futura: {last_time} >= {current_bar_time}"
        )
    assert result.bars_processed == 400 - MIN_BARS


def test_engine_trades_respect_stops_and_are_chronological():
    """Todo trade fecha no SL, e a ordem de saída segue a ordem cronológica."""
    from backtest.engine import BacktestEngine

    result = BacktestEngine().run(_synthetic(600))

    assert result.trades, "a estratégia deve gerar ao menos um trade na série"
    for t in result.trades:
        assert t.exit_reason in ("SL", "TRAIL", "END")
        assert t.exit_time >= t.entry_time
        assert t.pnl is not None
        if t.exit_reason in ("SL", "TRAIL"):
            # fill exato no SL vigente
            assert t.exit_price == pytest.approx(t.sl)
            if t.exit_reason == "SL":
                # stop nunca movido: continua do lado adverso da entrada
                if t.direction == "BUY":
                    assert t.sl < t.entry_price
                else:
                    assert t.sl > t.entry_price
            else:
                # trailing/breakeven só sobem o stop a favor da posição
                if t.direction == "BUY":
                    assert t.sl >= t.entry_price
                else:
                    assert t.sl <= t.entry_price

    entradas = [t.entry_time for t in result.trades]
    assert entradas == sorted(entradas)


def test_engine_pnl_math_is_correct():
    """P&L de um trade conhecido, com valor literado à mão."""
    from backtest.engine import Trade

    t = Trade(
        entry_time=pd.Timestamp("2026-01-01"),
        entry_price=2000.0,
        direction="BUY",
        volume=0.01,
        sl=1990.0,
        sl_points=10.0,
    )
    t.close(pd.Timestamp("2026-01-02"), 2010.0, "REVERSE")
    # (2010 - 2000) * 0.01 * 100 = 10.00
    assert t.pnl == pytest.approx(10.0)

    s = Trade(
        entry_time=pd.Timestamp("2026-01-01"),
        entry_price=2000.0,
        direction="SELL",
        volume=0.01,
        sl=2010.0,
        sl_points=10.0,
    )
    s.close(pd.Timestamp("2026-01-02"), 1990.0, "REVERSE")
    # (2000 - 1990) * 0.01 * 100 = 10.00
    assert s.pnl == pytest.approx(10.0)


def test_engine_balance_matches_sum_of_trade_pnl():
    """O saldo final é a soma dos P&Ls — invariante contábil."""
    from backtest.engine import BacktestEngine

    result = BacktestEngine().run(_synthetic(500))
    esperado = result.initial_balance + sum(t.pnl for t in result.trades)
    assert result.final_balance == pytest.approx(esperado)


def test_engine_equity_curve_is_chronological():
    from backtest.engine import BacktestEngine

    curve = BacktestEngine().run(_synthetic(500)).equity_curve
    assert not curve.empty
    assert curve["time"].is_monotonic_increasing
    assert set(curve.columns) == {"time", "balance", "equity"}
