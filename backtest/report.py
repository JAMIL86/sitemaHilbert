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

#: Rotulos de quem encerrou cada posicao -> de que documento a REGRA vem.
#: A coluna "Fonte da regra" do relatório existe para que um número de outra
#: fonte nunca seja lido como regra do PDF.
EXIT_SOURCES = {
    "SL": "**V26, nao o PDF**",
    "TRAIL": "**V26, nao o PDF**",
    "QUADRANT": "**WCE 2014, literal**",
    "TP": "**parametro de pesquisa, nao o PDF**",
    "END": "—forca de janela",
}

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

    if model.startswith("wce"):
        # Import tardio: `backtest.engine` importa este modulo dentro de main(),
        # entao um import de topo aqui viraria ciclo.
        from backtest.engine import WCE_VARIANTS

        variant = WCE_VARIANTS.get(model)

        if variant is None:
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
        else:
            # Variante: o SL/TP sao parametros de pesquisa, nao regra de artigo.
            # Um TP de 50 pts lido sem este aviso pareceria vir do PDF.
            tp_txt = f"take profit fixo de {variant.tp_points:.0f} pontos" if variant.use_tp else "sem take profit"
            sl_txt = (
                f"stop fixo de {variant.sl_points:.0f} pontos" if variant.use_sl
                else "sem stop loss"
            )
            linhas = [
                f"> **VARIANTE DE PESQUISA — {model}.** {variant.description}",
                ">",
                f"> O WCE 2014 define APENAS a saida (\"closed when the signal "
                "exits the quarter\"). O que for usado alem disso aqui — "
                f"{tp_txt}, {sl_txt} — NAO e regra do artigo: sao parametros "
                "de pesquisa, escolhidos para medir o efeito de cada um. Um "
                "resultado bom nesta variante nao valida o WCE 2014; valida "
                "que estes numeros funcionam NESTES dados.",
                "",
            ]
            if variant.use_sl and variant.sl_points:
                linhas += [
                    "> O stop desta variante e FIXO, e nao o `calculate_initial_sl` "
                    "ATR do V26: um stop que varia por barra nao distinguiria o "
                    "efeito do SL do efeito da formula ATR.",
                    "",
                ]
            lines += linhas

        # §9.3: o relatorio tem que QUANTIFICAR o quanto do resultado depende do
        # guardrail, nao apenas avisar que ele existe. Um aviso sem numero e
        # decoracao; o numero diz quanto do P&L veio de uma regra que o artigo
        # nao escreve.
        #
        # Contagem por `exit_reason`:
        #   SL        -> o stop segurou a posicao. Este P&L e de outra fonte.
        #   QUADRANT  -> a regra literal do PDF ("closed when the signal exits
        #                 the quarter") encerrou a posicao. Logica pura.
        #   TP        -> alvo fixo de pesquisa.
        #   END       -> fim da janela, posicao forcada a fechar.
        by_reason: dict[str, list[dict]] = {}
        for t in trades:
            by_reason.setdefault(t.get("exit_reason") or "?", []).append(t)

        ordem = ["SL", "TRAIL", "TP", "QUADRANT", "END"]
        presentes = [r for r in ordem if r in by_reason] + [
            r for r in by_reason if r not in ordem
        ]

        nao_pdf = {"SL", "TRAIL", "TP"}
        fora = [t for r in nao_pdf for t in by_reason.get(r, [])]
        pnl_pdf = sum(
            t.get("pnl") or 0.0 for t in trades
            if (t.get("exit_reason") or "") not in nao_pdf
        )
        pnl_fora = sum(t.get("pnl") or 0.0 for t in fora)

        linhas_guard = [
            "## Guardrails",
            "",
            "O que os numeros abaixo separam e QUAL REGRA encerrou cada "
            "posicao — e de que documento ela vem.",
            "",
            "| Encerrado por | Fonte da regra | Trades | P&L |",
            "|---|---|---:|---:|",
        ]
        for r in presentes:
            grupo = by_reason[r]
            pnl = sum(t.get("pnl") or 0.0 for t in grupo)
            rotulo = {
                "SL": "SL (stop guardrail)",
                "TRAIL": "TRAIL (trailing)",
                "TP": f"TP (alvo de {variant.tp_points:.0f} pts)" if variant else "TP (alvo)",
                "QUADRANT": "QUADRANT (saiu do quadrante)",
                "END": "END (fim da janela)",
            }.get(r, r)
            linhas_guard.append(
                f"| {rotulo} | {EXIT_SOURCES.get(r, r)} | {len(grupo)} | ${pnl:+.2f} |"
            )
        linhas_guard.append("")
        total = len(trades) or 1
        if fora:
            linhas_guard += [
                f"**{len(fora)} de {total} trades ({len(fora) / total * 100:.1f}%) "
                f"dependem de uma regra que o artigo nao escreve** — P&L "
                f"${pnl_fora:+.2f}. Se esta variante for julgada pelo resultado "
                "total, essa fracao e o que precisa ser lida como parametro de "
                "pesquisa, nao como edge do WCE 2014.",
                "",
            ]
        else:
            linhas_guard += [
                f"**Nenhum trade dependeu de stop nem de take profit.** Todos os "
                f"{total} foram encerrados pela regra literal do PDF "
                f"(sair do quadrante) ou por fim de janela — P&L "
                f"${pnl_pdf:+.2f}. Este e o numero mais proximo do artigo "
                "possivel neste pipeline.",
                "",
            ]
        lines += linhas_guard

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
