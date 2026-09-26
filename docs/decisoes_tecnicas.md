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

---

## 7. O PDF WCE 2014 não é implementável sozinho — três lacunas

Antes de "ativar WCE 2014" como modelo primário, a leitura literal das
pp. 927–933 mostrou que **três decisões necessárias não estão no artigo**. Cada
uma é um ponto onde é fácil inventar regra sem perceber.

**7.1 Não existe `I>0, Q>0 = Quarter 1` no WCE.**

O artigo define os quadrantes **geometricamente** (Figuras 5 e 7, eixos I vs
Q). A frase literal é sobre cruzamento de quadrante, não sobre sinal de eixo:

> "whenever the signal crosses Quarter 1, the price is likely to rise
> afterwards, until it exits from Quarter 1 to any other quarter."

O mapeamento algébrico `Q1 = {I>0, Q>0}` e `Q3 = {I<0, Q<0}` vem do **PDF
V26 (p. 3)**, que interpreta o WCE. É geometricamente correto para o eixo I no
horizontal e Q no vertical — mas a fonte é outro PDF. Implementar a partir do
WCE sem registrar isso é atribuir ao artigo uma regra que ele não escreve.

**7.2 O ISOM não tem threshold. Não há `dx(%)` em lugar nenhum.**

O artigo diz, literalmente:

> "the ISOM is a model that takes into consideration a certain threshold
> dx(%) and will observe the timings where the directional changes dc occur."

e no Listing 1:

> "Filter out data with low numbers of directional changes"

O símbolo `dx(%)` aparece, o **valor não**. "low numbers" também é qualitativo.
Logo **o filtro ISOM não é implementável a partir deste PDF** — qualquer valor
de corte seria inventado. Decisão: filtro **desativado com warning explícito**,
não um threshold chutado.

**7.3 WCE não tem stop loss. Nenhum.**

A única regra de saída escrita é fechar ao sair do quadrante:

> "…which is closed when the signal exits the quarter."

Não há SL, TP, trailing, break-even, parciais nem management de risco em lugar
nenhum do artigo ("Gestão de risco: não especificada"). Sem SL, um trade pode
ficar aberto atravessando o ciclo inteiro do Hilbert, e o Max DD do backtest
fica sem teto. **Decisão:** usar o `calculate_initial_sl` do V26
(`ATR14 × min(2.0, T_final/10)`, `pdf_strategies.py:256`) como guardrail de
projeto, registrado como **guardrail, não regra do PDF**. Sem isso o backtest
mede uma estratégia sem controle de risco e produz DD irreal.

**Confiança:** verificada nas citações (grep no `_extract/WCE2014_pp927-933.txt`,
linhas 512–525 e 371–440) — o que o PDF **não** contém é conclusão negativa,
mais frágil, mas sustentada por leitura completa do texto extraído.
**Escopo:** projeto Hilberti; a generalize a "ativar um paper acadêmico como
modelo primário" — sempreseparar o que o paper diz do que a implementação
precisa e não tem.
**Invalidada por:** o PDF completo (não só pp. 927–933) declarar o valor de
`dx%` ou o mapeamento algébrico dos quadrantes.

---

## 8. O `_extract/` já existe — não reprocessar o PDF

`pdfs/WCE2014_pp927-933.pdf` já foi extraído para
`_extract/WCE2014_pp927-933.txt` e `.json` (Etapa 1). Rodar `pdfplumber` de novo
custa tempo e produz o mesmo resultado.

**Ressalva de qualidade:** o `.txt` tem as **duas colunas da página
entrelaçadas** (padrão do pdfplumber em layout de duas colunas). As frases
ficam intercaladas com texto da coluna vizinha, e o encoding das fontes quebra
símbolos — `dx(%)` aparece como `dx(cid:1856)(cid:1876)%(cid:4667)`, e o sinal
de menos renderiza como `−` (U+2212) ou `−` ilegível. Ler o `.txt` sem saber
disso produz citação errado. Ao extrair regra de paper de duas colunas,
**reconstruir a ordem de leitura** e marcar o que foi reconstruído.

---

## 9. WCE 2014 ativado: o que é regra do PDF e o que é guardrail

Decisões do responsável, 2026-09-26. Registradas aqui porque a implementação
e o artigo divergem em dois pontos, e nenhum dos dois se deduz do texto.

### 9.1 Q1={I>0, Q>0} — fonte: V26 p.3, não o WCE

O WCE define os quadrantes **geometricamente** (Fig. 5 e 7, eixos I vs Q). O
mapeamento algébrico vem do **V26 p.3, seção Hilbert Transform**, que
interpreta o WCE. Autorizado explicitamente pelo responsável.

Consequência de código: `WCE2014Strategy.quadrant()` retorna `None` no eixo
exato (I ou Q == 0). Sem sinal, "estar em Q1" seria uma afirmação que o PDF
não faz — e dispararia entrada.

### 9.2 ISOM sem `dx(%)`: filtro DESATIVADO, não calibrado

O artigo nomeia o threshold e não dá o valor (ver §7.2). `isom_allows(None)`
retorna `True` para toda barra e emite um WARNING único. A alternativa —
escolher um `dx%` plausível — produziria um backtest com um número que parece
do artigo e não é. Aqui, o comportamento é declaradamente ausente.

### 9.3 Stop loss: guardrail de projeto, rotulado como tal

O WCE não define SL (§7.3). Autorizado usar `V26Strategy.calculate_initial_sl`
(ATR14 × min(2.0, T/10)) como guardrail. Marcado em três lugares para não
poder ser lido como regra do artigo:

- `WCE2014Strategy.SL_GUARDRAIL_PROJETO = True`
- `SignalDecision.metadata["guardrail_projeto"]`
- docstring de `initial_sl` e do relatório de backtest

Sem ele o trade atravessa o ciclo inteiro do Hilbert e o Max DD sai sem teto —
o backtest mediria uma estratégia sem controle de risco.

### 9.4 Entrada por TRAVESSIA, não por nível

O PDF diz "whenever the signal **crosses** Quarter 1". Implementar por nível
(entrar sempre que `I>0 and Q>0`) reentra **toda barra** dentro do quadrante.
A versão shadow anterior fazia exatamente isso — e por isso não é a mesma
estratégia que o artigo descreve. Só contam as travessias Q4→Q1 (BUY) e
Q2→Q3 (SELL).

Isto mudou `tests/test_strategy.py::test_wce2014_shadow_signals`, que fixava o
comportamento por nível. O teste foi reescrito para a travessia, com o motivo
registrado na docstring — não é um teste "ajustado até passar".

### 9.5 Custos: default ligado

`--with-costs` default `True`. Um backtest que não cobra spread produz PF que
não se reproduz ao vivo. `load_spread()` devolve `None` (não `0.0`) quando o
MT5 não responde: zero seria afirmar que o ativo é grátis. O relatório registra
se o spread veio do terminal ou do fallback de 0,15.

### 9.6 A quarta lacuna — o ISOM é ENTRADA do Hilbert, não filtro

Descoberta em 2026-09-26 pelo `edge-strategy-reviewer`, e maior que as três de
§7. Literal do PDF (`_extract/WCE2014_pp927-933.txt:254`):

> "apply the ISOM model on high frequency data, then determine the times of day
> with highest levels of intraday observations i.e. higher intraday event driven
> volatility, **and use that as an input for the Hilbert transform** to trade
> only on times of day where volatility is at a high peak. This will in turn
> overcome the problems presented by [3], where the Hilbert transform rotation
> goes out of bounds at periods of low volatility."

O WCE **não** usa ISOM como filtro de um sinal Hilbert já calculado. Ele usa
ISOM para escolher as horas do dia, e só então aplica o Hilbert transform
**naquelas horas**. `ai/feature_engineer.py:115-122` calcula `i1`/`q1` sobre
preço bruto, sem o condicionamento.

Por isso §9.2 está incompleto como está escrito. O filtro `dx(%)` desligado
não torna o resultado "o artigo com o filtro off" — o que falta é uma **etapa
anterior do pipeline**. O objeto medido é: artigo − condicionamento de horário
+ stop do V26. É um híbrido que não aparece em nenhum dos dois papers.

O rodapé no relatório (`backtest/report.py`, bloco `model == "wce"`) diz isso
com o literal do PDF, para que o número não seja lido como replicação.

### 9.7 Rebaixamento do WCE e correção do `active_model` no caminho vivo

Duas decisões do responsável em 2026-09-26, depois do veredito **REVISE**:

**(a) `active_model` era no-op no caminho vivo.** `StrategyRouter.decide()` tinha
`execute = v26_decision.signal in ("BUY", "SELL")` fixo e ignorava
`settings.active_model`. Com o default virado para `"wce"`, o sistema passava a
*dizer* que executava o WCE e *executava* o V26 — o commit mudava o backtest, o
log do `main.py` e a docstring, e nada mais. O default voltou para `"v26"`, e o
`decide()` passou a despachar de verdade, expondo `modelo_ativo` na decisão.
Coberto por `test_active_model_governs_execution_in_the_live_path`, que
exercita os dois lados do interruptor.

**(b) WCE rebaixado de primário para sombra.** O WCE é materialmente melhor que
o V26 nos mesmos dados (PF 0,879 vs 0,795 com custos; DD 2,96% vs 9,66%), mas
isso não justifica promoção: o artigo reporta **PF 1,0**, ou seja, break-even
pelos próprios autores, e o que medimos é o híbrido de §9.6, sobre 6 meses e
um único regime, sem out-of-sample. Promover com edge não medido seria confundir
"implementação fiel" — que o WCE é — com "estratégia lucrativa", que não está
estabelecido. `wce_shadow` voltou a `True`.

Nada foi removido: `python -m backtest.engine --model wce` reproduz a
medição, e `ACTIVE_MODEL=wce` ainda é selecionável. Gates de re-promoção em
`docs/handoff.md` §13.
