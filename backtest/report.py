"""Relatório de backtest — markdown + curva de equity (Etapa 9).

Regras dataviz aplicadas:
- UM eixo Y por gráfico (nunca dois eixos de escalas diferentes).
- Paleta validada pelo validador de seis checks (contraste + CVD).
- Legenda sempre presente com 2+ séries.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from loguru import logger

from backtest.metrics import compute_metrics

# Paleta validada 6/6 (light): #1D4ED8, #B45309, #7C3AED
PALETTE = {
    "equity": "#1D4ED8",
    "drawdown": "#B45309",
    "grid": "#E5E7EB",
    "text": "#374151",
}


def build_equity_figure(equity_curve: pd.DataFrame) -> "object":
    """Curva de equity em UM eixo Y único (regra dataviz).

    Se o DataFrame tiver coluna 'drawdown_pct', ela é plotted como trace
    separado (trace-único no mesmo eixo, sem eixo secundário).
    """
    import plotly.graph_objects as go

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=equity_curve["time"],
        y=equity_curve["equity"],
        name="Equity",
        line=dict(color=PALETTE["equity"], width=2),
    ))

    if "drawdown_pct" in equity_curve.columns:
        fig.add_trace(go.Scatter(
            x=equity_curve["time"],
            y=equity_curve["drawdown_pct"],
            name="Drawdown %",
            line=dict(color=PALETTE["drawdown"], width=1, dash="dot"),
        ))

    fig.update_layout(
        title="Curva de Equity — Backtest",
        xaxis_title="Tempo",
        yaxis_title="USD",  # eixo ÚNICO
        template="plotly_white",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=60, r=30, t=60, b=50),
    )

    # Grelha recessiva (dataviz: grid/axes são rebaixados)
    fig.update_xaxes(showgrid=True, gridcolor=PALETTE["grid"], griddash="dot")
    fig.update_yaxes(showgrid=True, gridcolor=PALETTE["grid"], griddash="dot")

    return fig


def build_markdown_report(result: dict, metrics: dict | None = None) -> str:
    """Gera relatório markdown do backtest.

    Args:
        result: dict com symbol, start_date, end_date, initial_balance,
                final_balance, trades, equity_curve
        metrics: dict de métricas (calculado automaticamente se ausente)
    """
    m = metrics or compute_metrics(result)
    trades = result.get("trades", [])

    lines = [
        f"# Backtest — {result.get('symbol', '?')}",
        "",
        f"**Periodo:** {result.get('start_date', '?')} a {result.get('end_date', '?')}",
        "",
        "## Resumo",
        "",
        "| Metrica | Valor |",
        "|---------|-------|",
        f"| Total de trades | {m['total_trades']} |",
        f"| Win rate | {m['win_rate_pct']:.1f}% |",
        f"| Profit factor | {m['profit_factor']:.2f} |",
        f"| Max drawdown | {m['max_drawdown_pct']:.2f}% |",
        f"| Sharpe ratio | {m['sharpe_ratio']:.2f} |",
        f"| Sortino ratio | {m['sortino_ratio']:.2f} |",
        f"| P&L total | ${m['total_pnl']:.2f} |",
        "",
        "## Balanco",
        "",
        f"- Inicial: ${result.get('initial_balance', 0):.2f}",
        f"- Final:   ${result.get('final_balance', 0):.2f}",
        f"- Retorno: {(result.get('final_balance', 0) - result.get('initial_balance', 0)) / result.get('initial_balance', 1) * 100:.2f}%",
        "",
    ]

    if trades:
        lines += [
            "## Ultimos 10 trades",
            "",
            "| # | Entrada | Dir | Preco entrada | Motivo | P&L |",
            "|---|---------|-----|---------------|--------|-----|",
        ]
        for i, t in enumerate(trades[-10:], start=max(1, len(trades) - 9)):
            pnl = t.get("pnl", 0)
            lines.append(
                f"| {i} | {t.get('entry_time', '?')} | {t.get('direction', '?')} | "
                f"{t.get('entry_price', 0):.2f} | {t.get('exit_reason', '-')} | "
                f"{pnl:+.2f} |"
            )
        lines.append("")

    return "\n".join(lines)


def save_report(result: dict, output_dir: Path = Path("backtest/reports")) -> dict:
    """Salva relatório markdown e figura HTML.

    Returns:
        Dict com paths dos arquivos gerados
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics = compute_metrics(result)

    stem = f"backtest_{result.get('symbol', 'xau').replace('-', '_')}"
    md_path = output_dir / f"{stem}.md"
    fig_path = output_dir / f"{stem}_equity.html"

    md_path.write_text(build_markdown_report(result, metrics), encoding="utf-8")

    equity = result.get("equity_curve")
    if equity is not None and not equity.empty:
        build_equity_figure(equity).write_html(str(fig_path), include_plotlyjs="cdn")

    logger.info("Relatório salvo: {} | {}", md_path, fig_path)
    return {"markdown": md_path, "figure": fig_path, "metrics": metrics}
