# Backtest — WCE_QUADRANT_TP / XAUUSD-VIP

**Periodo:** 2026-03-30 08:15:00+00:00 a 2026-09-25 23:55:00+00:00

**Modelo:** wce_quadrant_tp
**Custos:** spread 0.3400 USD | slippage 1 pt (0.0100 USD) | comissao 0.00 USD/lote/lado — total 312.90 USD

> **VARIANTE DE PESQUISA — wce_quadrant_tp.** WCE 2014 + take profit fixo de 50 pontos (0,50 USD). O PDF nao define TP: este numero e parametro de pesquisa, nao regra do artigo. A primeira medicao usou 500 e produziu ZERO TPs, mas a causa nao era geometria do mercado: os `*_points` estavam sendo somados ao preco como se fossem USD, colocando o alvo a +50,00 USD. Ver docs/handoff.md §14.6.
>
> O WCE 2014 define APENAS a saida ("closed when the signal exits the quarter"). O que for usado alem disso aqui — take profit fixo de 50 pontos, sem stop loss — NAO e regra do artigo: sao parametros de pesquisa, escolhidos para medir o efeito de cada um. Um resultado bom nesta variante nao valida o WCE 2014; valida que estes numeros funcionam NESTES dados.

## Guardrails

O que os numeros abaixo separam e QUAL REGRA encerrou cada posicao — e de que documento ela vem.

| Encerrado por | Fonte da regra | Trades | P&L |
|---|---|---:|---:|
| TP (alvo de 50 pts) | **parametro de pesquisa, nao o PDF** | 800 | $+120.00 |
| QUADRANT (saiu do quadrante) | **WCE 2014, literal** | 94 | $-494.05 |

**800 de 894 trades (89.5%) dependem de uma regra que o artigo nao escreve** — P&L $+120.00. Se esta variante for julgada pelo resultado total, essa fracao e o que precisa ser lida como parametro de pesquisa, nao como edge do WCE 2014.

## Resumo

| Metrica | Valor |
|---------|-------|
| Total de trades | 894 |
| Win rate | 89.5% |
| Profit factor | 0.24 |
| Max drawdown | 3.75% |
| Sharpe ratio | -8.58 |
| Sortino ratio | -2.73 |
| P&L total | $-374.05 |

## Balanco

- Inicial: $10000.00
- Final:   $9625.95
- Retorno: -3.74%

## Ultimos 10 trades

| # | Entrada | Dir | Preco entrada | Motivo | P&L |
|---|---------|-----|---------------|--------|-----|
| 885 | 2026-09-24 07:05:00+00:00 | SELL | 4283.96 | TP | +0.15 |
| 886 | 2026-09-24 11:35:00+00:00 | SELL | 4268.26 | TP | +0.15 |
| 887 | 2026-09-24 12:25:00+00:00 | SELL | 4255.58 | TP | +0.15 |
| 888 | 2026-09-24 13:40:00+00:00 | SELL | 4258.33 | TP | +0.15 |
| 889 | 2026-09-24 16:10:00+00:00 | BUY | 4278.27 | TP | +0.15 |
| 890 | 2026-09-24 17:45:00+00:00 | SELL | 4257.36 | TP | +0.15 |
| 891 | 2026-09-24 18:35:00+00:00 | SELL | 4253.71 | TP | +0.15 |
| 892 | 2026-09-25 11:40:00+00:00 | BUY | 4292.21 | TP | +0.15 |
| 893 | 2026-09-25 17:25:00+00:00 | SELL | 4265.96 | TP | +0.15 |
| 894 | 2026-09-25 22:10:00+00:00 | BUY | 4296.71 | QUADRANT | -4.35 |
