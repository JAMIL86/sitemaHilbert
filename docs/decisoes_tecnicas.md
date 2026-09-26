# Decisões técnicas e armadilhas conhecidas

Achados que custaram tempo para descobrir e que o código sozinho não
explica. Cada um com a evidência que o sustenta.

---

## 1. `mt5.initialize()` falha com `server=` num terminal já autenticado

**Sintoma.** `HistoricalDataDownloader.download_range()` retornava DataFrame
vazio com `(-2, 'Terminal: Invalid params')`, três vezes seguidas.

**Causa.** `MT5Connector.connect()` monta os kwargs a partir do `.env`,
incluindo `server=VTMarkets-Demo`. Quando o `terminal64.exe` **já está
aberto e autenticado**, passar `server=` faz o `initialize()` recusar.

**Isolamento (A/B controlado contra o terminal vivo).**

```
mt5.initialize(path=P, timeout=30000)                     -> True (1, 'Success')
                                                            account 1045989
mt5.initialize(path=P, password=..., server=...)          -> False (-2, 'Invalid params')
kwargs passados: ['password', 'path', 'server']   (sem 'login' — mt5_login é None)
```

`tasklist` confirmou `terminal64.exe` PID 4772 já em execução.

**Solução.** `backtest/downloader.py#HistoricalDataDownloader._connect` não usa
`MT5Connector`. Chama `mt5.initialize(path=..., timeout=30000)` sem
`server=`, e só injeta `login`/`password`/`server` se `mt5_login` estiver
definido — o que também satisfaz a trava de segurança da Etapa 6 (conta deve
ser 1045989).

**Armadilha adjacente.** `mt5_login` usa `alias="MT5_LOGIN"` no
pydantic-settings, e o model_config é `extra="ignore"`. Passar `mt5_login=...`
por kwargs de campo **é descartado silenciosamente**. Use a variável de
ambiente, não o nome do campo.

**Confiança:** verificada (A/B reproduzido, depois corrigido e re-executado —
35 359 barras baixadas).

**Escopo:** projeto Hilberti. **Invalidada por:** a MetaTrader5 mudar a
semântica de `initialize()` num terminal pré-autenticado.

---

## 2. O `MT5Connector` é inadequado para leitura de histórico

Consequência do item 1. O conector foi desenhado para * trading* (onde faz
sentido forçar servidor explícito), não para *ler barras* num terminal que o
usuário já abriu. **Regra:** leitura de histórico abre o terminal do jeito mais
pouco invasivo possível; `MT5Connector` fica reservado para o loop de trading,
onde a sessão é gerida por ele.

---

## 3. XAUUSD-VIP não opera 24h — validar "gap > 10 min" rejeita dado íntegro

**Sintoma.** `validate()` reprovava a série com `129 gaps > 10 min detectados`.

**O que os gaps realmente eram.** Medidos:

| Tipo | Quantidade | Duração |
|---|---|---|
| Fechamento diário | 104 | 65 min (23:55 → 01:00 UTC) |
| Fim de semana | 25 | 2 945–4 385 min |
| **Buraco real** | **1** | 15 min (3 barras, 2026-08-28 17:25→17:40) |

Sessão medida: **01:00–23:55 UTC, todos os dias**. 129 gaps, **zero** barras
faltando.

**Solução.** `downloader.py#HistoricalDataDownloader._internal_gaps` conta
só o buraco que **não cruza a fronteira de sessão** (reabertura ≤ 01:00 UTC,
ou anterior ≥ 23:55, ou delta > 24 h). Reprova acima de 30 min; abaixo disso
registra warning com o número de barras perdidas — dado imperfeito declarado é
melhor que dado perfeito inventado.

**Armadilha generalization.** "Gap" só significa "dado faltando" depois que
você conhece o horário do ativo. Antes disso, um limiar fixo de 10 min é um
chute que reprova série boa e aprova série ruim.

**Confiança:** verificada (distribuição de gaps medida nas 35 359 barras).

**Escopo:** projeto Hilberti; a generalize para qualquer ativo de sessão
limitada. **Invalidada por:** o `XAUUSD-VIP` mudar de sessão.

---

## 4. Bug de unidade no V26: "pts" do PDF vs delta de preço no código

**Medido no terminal real** (conta 1045989, `XAUUSD-VIP`):

```
digits=2   point=0.01   trade_tick_value=1.00 USD   contract_size=100 oz
```

Logo **1 ponto MT5 = $0,01 de preço**.

**O que o código faz.** `strategy/pdf_strategies.py#Position.get_profit_points`
retorna `current_price - open_price` — delta bruto de preço, **não** pontos
MT5. `manage_open_trade` (linha 438) compara esse valor com
`inp_be_pts = 500.0`. **BE só dispara em +$5,00 de preço.**

`calculate_initial_sl` (linha 256) usa a mesma convenção:
`sl_points = atr14 × min(2.0, T_final/10.0)`, com `atr14` em USD.

**Números medidos no dado real** (XAUUSD-VIP M5, 6 meses, 35 359 barras):

| Grandeza | Valor | Em ATR14 |
|---|---|---|
| ATR14 médio | 5,198 USD (519,8 pts MT5) | 1,00 |
| SL médio observado | 8,64 USD | 1,66 |
| `inp_be_pts = 500` (lido como preço) | 500 USD | **96,2** |

Razão BE/SL = **57,9×**. **Inalcançável na prática** — confirmado pelo
backtest real: **zero parciais** em 1 746 trades, 1 043 das 1 746 saídas no
stop inicial.

**Por que o PDF não decide.** "pts" pode ser ponto MT5 (leitura 1: 500 pts ≈
1 ATR, gatilho de gestão plausível) ou dollar de preço (leitura 2: 500 USD ≈
96 ATR, implausível). A leitura 1 é a coerente, **mas a escolha é do
responsável, não do código** — por isso nada foi ajustado.

**Correção proposta, NÃO APLICADA:** converter `get_profit_points()` para
pontos MT5 (dividir por `point`) e pôr `calculate_initial_sl` e `inp_be_pts`
na mesma unidade. Muda a estratégia — exige aval explícito.

**Confiança:** verificada na medição; **speculativa** na escolha da leitura
correta (o PDF não arbitra). **Escopo:** projeto Hilberti.
**Invalidada por:** o PDF original declarar a unidade explicitamente.

---

## 5. `to_dict()` achata a equity e o report quebra 12 minutos depois

**Sintoma.** `python -m backtest.engine` completava o backtest e morria em
`KeyError: 'time'` dentro de `save_report` — **após 12 min de computação**,
com todo o resultado já em memória.

**Causa.** `BacktestResult.to_dict()` converte a curva de equity para
`equity_curve["equity"]` — uma **Series**, sem coluna `'time'` e sem atributo
`.columns`. `build_equity_figure()` acessava os dois.

**Correção.** `backtest/report.py#build_equity_figure` discrimina
`isinstance(equity_curve, pd.DataFrame)`: com `'time'`, usa a coluna; senão usa
o índice (que é a ordem cronológica das barras).

**Armadilha geral.** Validar o report só com a fixture do teste esconde isto:
`test_equity_figure_uses_single_y_axis` passa um **DataFrame** com `'time'`, o
caminho que funcionava. O bug só aparece com o payload real de produção.

**Regra derivada:** todo formatador de saída precisa de um teste que rode
sobre o payload **real** que o chamador de produção passa — não sobre uma
fixture mais conveniente. Regressão coberta por
`tests/test_backtest.py::test_save_report_handles_the_flattened_equity_series`.

**Confiança:** verificada (bug reproduzido, corrigido, teste vermelho→verde).

**Escopo:** projeto Hilberti; a generalize a qualquer `to_dict()` que achate
um DataFrame temporal.

---

## 6. Resultado do backtest real: PF 0,929 — faixa REVISE

Primeiro backtest sobre dado real (o anterior era `default_rng(7)`).

| Métrica | Sintético | Real |
|---|---|---|
| Trades | 41 | 1 746 |
| Win rate | 39,0% | 40,3% |
| Profit factor | 0,532 | **0,929** |
| Sharpe | −17,70 | −1,441 |

Regra do responsável: PF > 1,3 autoriza FASE 2; PF < 1 discutimos REVISE.
**PF 0,929 < 1,0 → FASE 2 não autorizada.** Monte Carlo sobre edge negativo
produziria bandas de confiança em torno de uma perda.

**Ressalvas honestas, ainda não modeladas:**
- O engine **não** cobra spread, comissão nem slippage. O PF real é **pior**
  que 0,929.
- 1 746 trades em 179 dias ≈ 10/dia ≈ 1 por hora de mercado. Frequência
  altíssima para M5 — sugere reentrada agressiva, e é a variável a auditar
  antes de culpar a lógica de sinal.

**Confiança:** verificada (números do backtest real, commit `b5656cf`).
**Escopo:** projeto Hilberti. **Invalidada por:** inclusão de custos, correção
da unidade de BE, ou mudança nos parâmetros do V26.
