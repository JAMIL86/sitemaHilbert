# Backtest — WCE / XAUUSD-VIP

**Periodo:** 2026-03-30 08:15:00+00:00 a 2026-09-25 23:55:00+00:00

**Modelo:** wce
**Custos:** spread 0.3400 USD | slippage 1 pt (0.0100 USD) | comissao 0.00 USD/lote/lado — total 312.90 USD

> **AVISO — o stop loss deste modelo NAO e regra do PDF WCE 2014.**
> O artigo nao define SL. O stop abaixo e um guardrail de projeto
> (`calculate_initial_sl` do V26, ATR14 x min(2.0, T/10)), autorizado
> pelo responsavel em 2026-09-26. Ver `docs/decisoes_tecnicas.md` §9.3.
> O filtro ISOM tambem esta DESATIVADO: o PDF nao informa o valor de
> `dx(%)` e nenhum threshold foi inventado (§9.2).

## Guardrails

O WCE 2014 nao define stop. Todo trade deste modelo carrega um stop guardrail de projeto na ENTRADA; o que os numeros abaixo separam e QUAL REGRA encerrou cada posicao.

| Encerrado por | Fonte da regra | Trades | P&L |
|---|---|---:|---:|
| SL (stop guardrail) | **V26, nao o PDF** | 165 | $-1221.62 |
| QUADRANT (saiu do quadrante) | **WCE 2014, literal** | 729 | $+953.52 |
| END (fim da janela) |—forca de janela | 0 | $+0.00 |

**165 de 894 trades (18.5%) dependem do guardrail** — o P&L deles ($ -1221.62) vem de uma regra que o artigo nao escreve. Se o WCE for julgado pelo resultado total, essa fracao e o que precisa ser lida como artificio de risco, nao como edge.

> **Rodape de fidelidade (decisoes_tecnicas.md §9.6).** O PDF nao usa o
> ISOM como *filtro* de um sinal Hilbert — usa como **entrada** do
> transform: "use that as an input for the Hilbert transform to trade
> only on times of day where volatility is at a high peak". Aqui o
> `i1`/`q1` sao calculados sobre preco bruto, sem o condicionamento de
> horario. Portanto estes numeros NAO sao replicacao do artigo sao o
> artigo menos uma etapa do pipeline, mais um stop de outra fonte.
> Ver tambem: o PF do artigo e 1.0, isto e, break-even.

## Resumo

| Metrica | Valor |
|---------|-------|
| Total de trades | 894 |
| Win rate | 42.6% |
| Profit factor | 0.88 |
| Max drawdown | 2.96% |
| Sharpe ratio | -1.95 |
| Sortino ratio | -2.31 |
| P&L total | $-268.10 |

## Balanco

- Inicial: $10000.00
- Final:   $9731.90
- Retorno: -2.68%

## Ultimos 10 trades

| # | Entrada | Dir | Preco entrada | Motivo | P&L |
|---|---------|-----|---------------|--------|-----|
| 885 | 2026-09-24 07:05:00+00:00 | SELL | 4283.96 | QUADRANT | -2.93 |
| 886 | 2026-09-24 11:35:00+00:00 | SELL | 4268.26 | QUADRANT | +8.56 |
| 887 | 2026-09-24 12:25:00+00:00 | SELL | 4255.58 | QUADRANT | -2.29 |
| 888 | 2026-09-24 13:40:00+00:00 | SELL | 4258.33 | QUADRANT | -0.23 |
| 889 | 2026-09-24 16:10:00+00:00 | BUY | 4278.27 | QUADRANT | -5.77 |
| 890 | 2026-09-24 17:45:00+00:00 | SELL | 4257.36 | QUADRANT | +6.69 |
| 891 | 2026-09-24 18:35:00+00:00 | SELL | 4253.71 | QUADRANT | -1.85 |
| 892 | 2026-09-25 11:40:00+00:00 | BUY | 4292.21 | QUADRANT | +0.69 |
| 893 | 2026-09-25 17:25:00+00:00 | SELL | 4265.96 | QUADRANT | -7.47 |
| 894 | 2026-09-25 22:10:00+00:00 | BUY | 4296.71 | QUADRANT | -4.35 |
