# Backtest — WCE_QUADRANT_TP_SL / XAUUSD-VIP

**Periodo:** 2026-03-30 08:15:00+00:00 a 2026-09-25 23:55:00+00:00

**Modelo:** wce_quadrant_tp_sl
**Custos:** spread 0.3400 USD | slippage 1 pt (0.0100 USD) | comissao 0.00 USD/lote/lado — total 312.90 USD

> **VARIANTE DE PESQUISA — wce_quadrant_tp_sl.** WCE 2014 + take profit de 50 pontos (0,50 USD) + stop fixo de 250 pontos (2,50 USD). Nem o TP nem o SL vem do PDF: sao parametros de pesquisa, e o SL e FIXO para nao se confundir com o stop ATR do V26.
>
> O WCE 2014 define APENAS a saida ("closed when the signal exits the quarter"). O que for usado alem disso aqui — take profit fixo de 50 pontos, stop fixo de 250 pontos — NAO e regra do artigo: sao parametros de pesquisa, escolhidos para medir o efeito de cada um. Um resultado bom nesta variante nao valida o WCE 2014; valida que estes numeros funcionam NESTES dados.

> O stop desta variante e FIXO, e nao o `calculate_initial_sl` ATR do V26: um stop que varia por barra nao distinguiria o efeito do SL do efeito da formula ATR.

## Guardrails

O que os numeros abaixo separam e QUAL REGRA encerrou cada posicao — e de que documento ela vem.

| Encerrado por | Fonte da regra | Trades | P&L |
|---|---|---:|---:|
| SL (stop guardrail) | **V26, nao o PDF** | 344 | $-980.40 |
| TP (alvo de 50 pts) | **parametro de pesquisa, nao o PDF** | 538 | $+80.70 |
| QUADRANT (saiu do quadrante) | **WCE 2014, literal** | 12 | $-16.30 |

**882 de 894 trades (98.7%) dependem de uma regra que o artigo nao escreve** — P&L $-899.70. Se esta variante for julgada pelo resultado total, essa fracao e o que precisa ser lida como parametro de pesquisa, nao como edge do WCE 2014.

## Resumo

| Metrica | Valor |
|---------|-------|
| Total de trades | 894 |
| Win rate | 60.2% |
| Profit factor | 0.08 |
| Max drawdown | 9.16% |
| Sharpe ratio | -30.09 |
| Sortino ratio | -15.56 |
| P&L total | $-916.00 |

## Balanco

- Inicial: $10000.00
- Final:   $9084.00
- Retorno: -9.16%

## Ultimos 10 trades

| # | Entrada | Dir | Preco entrada | Motivo | P&L |
|---|---------|-----|---------------|--------|-----|
| 885 | 2026-09-24 07:05:00+00:00 | SELL | 4283.96 | TP | +0.15 |
| 886 | 2026-09-24 11:35:00+00:00 | SELL | 4268.26 | TP | +0.15 |
| 887 | 2026-09-24 12:25:00+00:00 | SELL | 4255.58 | SL | -2.85 |
| 888 | 2026-09-24 13:40:00+00:00 | SELL | 4258.33 | SL | -2.85 |
| 889 | 2026-09-24 16:10:00+00:00 | BUY | 4278.27 | TP | +0.15 |
| 890 | 2026-09-24 17:45:00+00:00 | SELL | 4257.36 | SL | -2.85 |
| 891 | 2026-09-24 18:35:00+00:00 | SELL | 4253.71 | TP | +0.15 |
| 892 | 2026-09-25 11:40:00+00:00 | BUY | 4292.21 | TP | +0.15 |
| 893 | 2026-09-25 17:25:00+00:00 | SELL | 4265.96 | TP | +0.15 |
| 894 | 2026-09-25 22:10:00+00:00 | BUY | 4296.71 | SL | -2.85 |
