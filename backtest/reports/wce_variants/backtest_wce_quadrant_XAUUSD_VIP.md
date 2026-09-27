# Backtest — WCE_QUADRANT / XAUUSD-VIP

**Periodo:** 2026-03-30 08:15:00+00:00 a 2026-09-25 23:55:00+00:00

**Modelo:** wce_quadrant
**Custos:** spread 0.3400 USD | slippage 1 pt (0.0100 USD) | comissao 0.00 USD/lote/lado — total 312.90 USD

> **VARIANTE DE PESQUISA — wce_quadrant.** WCE 2014 literal: entra por travessia de quadrante e sai ao sair do quadrante. SEM stop, SEM take profit — o artigo nao escreve nenhum dos dois.
>
> O WCE 2014 define APENAS a saida ("closed when the signal exits the quarter"). O que for usado alem disso aqui — sem take profit, sem stop loss — NAO e regra do artigo: sao parametros de pesquisa, escolhidos para medir o efeito de cada um. Um resultado bom nesta variante nao valida o WCE 2014; valida que estes numeros funcionam NESTES dados.

## Guardrails

O que os numeros abaixo separam e QUAL REGRA encerrou cada posicao — e de que documento ela vem.

| Encerrado por | Fonte da regra | Trades | P&L |
|---|---|---:|---:|
| QUADRANT (saiu do quadrante) | **WCE 2014, literal** | 894 | $-257.81 |

**Nenhum trade dependeu de stop nem de take profit.** Todos os 894 foram encerrados pela regra literal do PDF (sair do quadrante) ou por fim de janela — P&L $-257.81. Este e o numero mais proximo do artigo possivel neste pipeline.

## Resumo

| Metrica | Valor |
|---------|-------|
| Total de trades | 894 |
| Win rate | 44.4% |
| Profit factor | 0.89 |
| Max drawdown | 3.59% |
| Sharpe ratio | -1.70 |
| Sortino ratio | -1.80 |
| P&L total | $-257.81 |

## Balanco

- Inicial: $10000.00
- Final:   $9742.19
- Retorno: -2.58%

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
