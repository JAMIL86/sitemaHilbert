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

    if isinstance(equity_curve, pd.DataFrame) and "time" in equity_curve.columns:
        x = equity_curve["time"]
        y = equity_curve["equity"]
        dd = equity_curve["drawdown_pct"] if "drawdown_pct" in equity_curve.columns else None
    else:
        # `BacktestResult.to_dict()` achata a curva numa Series de equity.
        # Sem 'time', o índice é a ordem cronológica das barras.
        x = equity_curve.index
        y = equity_curve
        dd = None

    fig.add_trace(go.Scatter(
        x=x, y=y, name="Equity",
        line=dict(color=PALETTE["equity"], width=2),
    ))

    if dd is not None:
        fig.add_trace(go.Scatter(
            x=x, y=dd, name="Drawdown %",
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

    model = result.get("model", "v26")
    lines = [
        f"# Backtest — {model.upper()} / {result.get('symbol', '?')}",
        "",
        f"**Periodo:** {result.get('start_date', '?')} a {result.get('end_date', '?')}",
        "",
        f"**Modelo:** {model}",
        f"**Custos:** {result.get('cost_model_desc', 'desligado')}"
        f" — total {result.get('total_costs', 0.0):.2f} USD",
        "",
    ]

    if model == "wce":
        # O stop do WCE nao vem do artigo (decisoes_tecnicas.md §7.3 e §9.3).
        # Printing-lo sem este aviso faria o relatorio apresentar um numero de
        # outra fonte como se fosse regra do PDF.
        lines += [
            "> **AVISO — o stop loss deste modelo NAO e regra do PDF WCE 2014.**",
            "> O artigo nao define SL. O stop abaixo e um guardrail de projeto",
            "> (`calculate_initial_sl` do V26, ATR14 x min(2.0, T/10)), autorizado",
            "> pelo responsavel em 2026-09-26. Ver `docs/decisoes_tecnicas.md` §9.3.",
            "> O filtro ISOM tambem esta DESATIVADO: o PDF nao informa o valor de",
            "> `dx(%)` e nenhum threshold foi inventado (§9.2).",
            "",
        ]

        # §9.3: o relatorio tem que QUANTIFICAR o quanto do resultado depende do
        # guardrail, nao apenas avisar que ele existe. Um aviso sem numero e
        # decoracao; o numero diz quanto do P&L veio de uma regra que o artigo
        # nao escreve.
        #
        # Contagem por `exit_reason`:
        #   SL        -> o stop guardrail segurou a posicao. Este P&L e do V26.
        #   QUADRANT  -> a regra literal do PDF ("closed when the signal exits
        #                 the quarter") encerrou antes do stop. Logica pura.
        #   END       -> fim da janela, posicao forcada a fechar.
        sl_hits = [t for t in trades if t.get("exit_reason") == "SL"]
        quad_exits = [t for t in trades if t.get("exit_reason") == "QUADRANT"]
        end_exits = [t for t in trades if t.get("exit_reason") == "END"]
        sl_pnl = sum(t.get("pnl") or 0.0 for t in sl_hits)
        quad_pnl = sum(t.get("pnl") or 0.0 for t in quad_exits)

        lines += [
            "## Guardrails",
            "",
            "O WCE 2014 nao define stop. Todo trade deste modelo carrega um stop "
            "guardrail de projeto na ENTRADA; o que os numeros abaixo separam e "
            "QUAL REGRA encerrou cada posicao.",
            "",
            "| Encerrado por | Fonte da regra | Trades | P&L |",
            "|---|---|---:|---:|",
            f"| SL (stop guardrail) | **V26, nao o PDF** | {len(sl_hits)} | ${sl_pnl:+.2f} |",
            f"| QUADRANT (saiu do quadrante) | **WCE 2014, literal** | {len(quad_exits)} | ${quad_pnl:+.2f} |",
            f"| END (fim da janela) |—forca de janela | {len(end_exits)} | "
            f"${sum(t.get('pnl') or 0.0 for t in end_exits):+.2f} |",
            "",
        ]
        total = len(trades) or 1
        lines += [
            f"**{len(sl_hits)} de {total} trades ({len(sl_hits) / total * 100:.1f}%) "
            f"dependem do guardrail** — o P&L deles ($ {sl_pnl:+.2f}) vem de uma "
            "regra que o artigo nao escreve. Se o WCE for julgado pelo resultado "
            "total, essa fracao e o que precisa ser lida como artificio de "
            "risco, nao como edge.",
            "",
        ]

    if model == "wce":
        # §9.6: a lacuna maior que o ISOM-desativado. O artigo usa o ISOM
        # como ENTRADA do transform, nao como filtro; `feature_engineer.py`
        # calcula i1/q1 sobre preco bruto. O resultado medido e o artigo
        # MENOS esse condicionamento — nao "o artigo com o filtro off".
        lines += [
            "> **Rodape de fidelidade (decisoes_tecnicas.md §9.6).** O PDF nao usa o",
            "> ISOM como *filtro* de um sinal Hilbert — usa como **entrada** do",
            "> transform: \"use that as an input for the Hilbert transform to trade",
            "> only on times of day where volatility is at a high peak\". Aqui o",
            "> `i1`/`q1` sao calculados sobre preco bruto, sem o condicionamento de",
            "> horario. Portanto estes numeros NAO sao replicacao do artigo sao o",
            "> artigo menos uma etapa do pipeline, mais um stop de outra fonte.",
            "> Ver tambem: o PF do artigo e 1.0, isto e, break-even.",
            "",
        ]

    lines += [
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

    # O nome precisa do MODELO: V26 e WCE produzem o mesmo símbolo e a mesma
    # janela, e sem isto um backtest sobrescreve o relatório do outro.
    stem = (
        f"backtest_{result.get('model', 'v26')}_"
        f"{result.get('symbol', 'xau').replace('-', '_')}"
    )
    md_path = output_dir / f"{stem}.md"
    fig_path = output_dir / f"{stem}_equity.html"

    md_path.write_text(build_markdown_report(result, metrics), encoding="utf-8")

    equity = result.get("equity_curve")
    if equity is not None and not equity.empty:
        build_equity_figure(equity).write_html(str(fig_path), include_plotlyjs="cdn")

    logger.info("Relatório salvo: {} | {}", md_path, fig_path)
    return {"markdown": md_path, "figure": fig_path, "metrics": metrics}
