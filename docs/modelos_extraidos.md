# Modelos extraídos dos PDFs

Fonte: extração literal com `pdfplumber` a partir de `./pdfs/`.
Data da extração: 2026-09-24.

Arquivos lidos:

| Arquivo | Páginas | Papel no projeto |
|---|---|---|
| `pdfs/Hilbert_Chimera_Dashboard_V26.pdf` | 19 | Modelo operacional V26 (Hilbert Cycle + Chimera SSM) |
| `pdfs/WCE2014_pp927-933.pdf` | 7 | Artigo acadêmico WCE 2014 — base matemática do ciclo de Hilbert + ISOM |

**Regra desta extração:** só entram fórmulas, gatilhos e parâmetros que aparecem no texto dos PDFs. Ambiguidades e lacunas estão listadas no final de cada modelo e **não** foram preenchidas.

---

## Modelo 1 — Hilbert Cycle + Chimera SSM V26 (Precision Accumulation Breakout)

### Identificação

| Campo | Valor extraído |
|---|---|
| Nome | Hilbert Cycle + Chimera SSM — Dashboard de Análise Matemática Avançada |
| Versão | V26 |
| Subtítulo operacional | Precision Accumulation Breakout |
| Cabeças | 4 (`CHilbertEngine`, `CHoloHilbert`, `CISOMEngine`, `GatingLayer`) |
| Ativos | XAU/USD e XAG/USD |
| Plataforma original | MQL5 / MT5 |
| Ano do documento | 2026 |
| Origem | Chimera Quant Engineering — Advanced Mathematics Edition (confidencial) |

### Timeframe(s)

- Backtest reportado (seção 08): **M5**, 12 meses (Jan–Dez 2025).
- Implementação MQL5 (seção 9.3): cálculo de EMD **apenas em nova barra** (não a cada tick); Roofing / EBSW / AGC são O(1) por barra e adequados a `OnTick`.
- Buffer circular: `MAX_WINDOW = 1000` barras.
- Cooldown: `InpCooldownBars` mínimo **3 barras** entre entradas consecutivas.

O PDF **não** declara um timeframe de execução exclusivo além do M5 usado no backtest. O artigo WCE 2014 (base citada na seção 01) usa dados de **5 minutos**.

### Indicadores / condições usadas

Pipeline declarado no PDF (seções 01–06):

1. **Suavização ponderada**
   - XAU/USD: WMA-4  
     `P_smooth(t) = [4·close(t) + 3·close(t-1) + 2·close(t-2) + 1·close(t-3)] / 10`
   - XAG/USD: WMA-5 com pesos `[5, 4, 3, 2, 1] / 15`
2. **Detrender**  
   `detrender(i) = 0.25·smooth(i) + 0.75·smooth(i-2) − 0.25·smooth(i-4) − 0.75·smooth(i-6)`
3. **Hilbert truncada (FIR, atraso 3 barras, n=3 no pseudo-código operacional)**  
   `Q1(i) = 0.25·det(i) + 0.75·det(i-2) − 0.25·det(i-4) − 0.75·det(i-6)`  
   `I1(i) = detrender(i-3)`
4. **Fase, amplitude, período**  
   `φ_k(t) = atan2(Q_k(t), I_k(t))`  
   `A_k(t) = sqrt(I_k² + Q_k²)`  
   `T_k(t) = 2π / ω_k(t)`
5. **Homodyne Discriminator**  
   `Δφ(t) = unwrap(atan2(Q/I)(t) − atan2(Q/I)(t-1))`  
   `T_homodyne(t) = 2π / Δφ(t)`  
   `T_smooth(t) = 0.5·T(t) + 0.5·T_smooth(t-1)` (EMA α=0.5)  
   `T_clamp(t) = min(max(T_smooth(t), T_min), T_max)`
6. **ISOM** — contagem de Directional Changes (DC) por bin horário. DC ocorre quando o preço reverte **≥ dx%** a partir de um extremo local. Filtro: operar só em bins de alta contagem DC.
7. **Roofing Filter** (substitui SuperSmoother isolado)  
   `HP(t) = (1−α)·(price(t) − price(t-1)) + α·HP(t-1)`  
   `Roofing(t) = SuperSmoother2P(HP(t), α_smoother)`  
   `α ≈ 0.707` (corte em 0.5 × período mínimo)
8. **EIT — Instantaneous Trendline**  
   `IT(t) = [3·Roofing(t) + 2·Roofing(t-1) + Roofing(t-2)] / 6`  
   Acumulação (slope): `|IT(t) − IT(t-1)| < 0.0005 · price(t)`
9. **EBSW — Even Better Sine Wave (lead 45°)**  
   `Sine(t) = sin(φ(t) + π/4)`  
   `LeadSine(t) = sin(φ(t) + 3π/4)`
10. **CycleMode**  
    `CycleMode = 1` se `|sin(φ+π/4)| > 0.85` **ou** `|sin(φ+3π/4)| > 0.85`  
    `CycleMode = 0` → modo tendência — **não operar por ciclo**
11. **AGC**  
    `AmplitudeNorm(t) = amplitude(t) / SMA(amplitude, 50)`
12. **HHT / EMD + Hilbert via FFT** sobre cada IMF; IMF dominante `k* = argmax E_k(t)`.
13. **HHSA** — EMD aninhado no envelope `A(t) = |z_k(t)|`; `AME(t) = A(t)²`.  
    AME baixo + energia principal baixa = compressão/acumulação. AME crescente após compressão = início de breakout.
14. **Entropia espectral** `H = −Σ p_k · log(p_k)` e sincronização de fase `γ₁₂` entre IMF1 e IMF2.
15. **Chimera SSM 2D** (NeurIPS 2024, citado) — estados ocultos `h⁽¹⁾` (tempo) e `h⁽²⁾` (cruzado XAU/XAG). Cabeças originais: tendência, sazonalidade, gating SwiGLU. V26 expande para 4 cabeças (abaixo).
16. **ATR14** — usado em SL, spread máximo e lote.

### As 4 cabeças (seção 06)

| Cabeça | Módulo | Função | Output |
|---|---|---|---|
| 1 | `CHilbertEngine` | Ciclo + fase + EBSW | `buySignal` / `sellSignal` |
| 2 | `CHoloHilbert` | Acumulação + ruptura | `isAccumulating` / `breakout` |
| 3 | `CISOMEngine` | Regime ML + score hora | `regime` / `confidence` |
| 4 | `GatingLayer` | Fusão adaptativa | `signalStrength ∈ [0,1]` |

Cabeça 3 (ML): regressão logística One-vs-Rest, classes `{Normal, High, Extreme}`.

```
features = [E_inst, AME, H_espectral, P_alta_freq, P_baixa_freq]
scores_c = bias_c + Σ_f w_{c,f} · feature_f
probs = Softmax(scores)
```

Aprendizado online SGD após cada trade, “buscando 58% win rate”. Score por hora do dia = frequência DC + win rate histórico (ISOM evoluído). Treino offline + update online a cada N trades, `lr = 0.001` (seção 9.3).

Cabeça 4:

```
g_t = σ(W_g · h_t + b_g)
y_t = g_t ⊙ MLP1(h_t) + (1−g_t) ⊙ MLP2(h_t)
```

MLP1 = seguir tendência; MLP2 = reverter à média.

### Gatilhos de entrada

Há **dois conjuntos** no mesmo PDF. O operacional V26 (seções 03–04) é o mais restritivo e é o que o documento chama de “coração do sistema”.

#### A) Lógica Hilbert clássica no plano I-Q (seção 01 / página 3)

Herdada do WCE 2014:

- **COMPRA:** Q1 (`I>0` e `Q>0`) — início do ciclo de alta.
- **VENDA:** Q3 (`I<0` e `Q<0`) — início do ciclo de baixa.
- Filtro ISOM ativo: só em bins de alta contagem DC.

#### B) Lógica V26 — Precision Accumulation Breakout (seções 03–04) — **regra operacional principal**

**Acumulação confirmada** (os 3 critérios simultâneos):

```
Acumulação = [1] AND [2] AND [3]
[1] Roofing_energy < 0.5 × SMA(energy, N) por N barras consecutivas
[2] |IT(t) − IT(t-1)| < 0.0005 × price(t)
[3] CycleMode = 1
```

**Ruptura latched:**

```
Ruptura_Latched = HighEnergy AND DirecaoBreakout AND QuadranteOK
DirecaoBreakout_Alta  : price > IT + threshold_atr
DirecaoBreakout_Baixa : price < IT − threshold_atr
```

**Entrada — tripla confirmação:**

```
COMPRA = Ruptura_Latched AND CycleMode=1 AND buySignal(Q4→Q1)
VENDA  = Ruptura_Latched AND CycleMode=1 AND sellSignal(Q2→Q3)
```

Onde `buySignal` / `sellSignal` vêm do EBSW (seção 3.3):

- Compra: Sine cruza **acima** de LeadSine no Q4 (transição Q4→Q1).
- Venda: Sine cruza **abaixo** de LeadSine no Q2 (transição Q2→Q3).

Filtros adicionais de entrada:

- `CycleMode = 1` obrigatório — “zero entradas em lateralização pura / trending sem ciclo identificável”.
- Spread: `MaxSpread(t) = min(ATR14(t) × fator, SpreadLimitManual)`  
  fator **0.10** para XAU/USD; **0.20** para XAG/USD (a fórmula genérica no texto usa 0.15; ver ambiguidades).
- Cooldown mínimo de **3 barras** (`InpCooldownBars`).
- Cabeça 3: score de hora / regime (Normal/High/Extreme) — o PDF **não** escreve o limiar numérico de `confidence` que bloqueia a entrada.

### Regras de saída (SL, TP, trailing, parciais)

Gestão hierárquica (seção 07). Cada camada é modulada por `CycleStrength` e `AmplitudeNorm`.

| Evento | Ação | Default extraído |
|---|---|---|
| `+InpBE_Pts` | Break-even | `InpBE_Pts = 500 pts` |
| `+InpParcial1_Pts` | Fecha `Parcial1_Pct%` do lote | `InpParcial1_Pct = 30%` |
| `+InpParcial2_Pts` | Fecha `Parcial2_Pct%` do lote | `InpParcial2_Pct = 30%` |
| `+InpTrailStart` | Trailing adaptativo ativo | `AmpNorm × InpTrailBasePct × CycleStrength` |
| Ciclo 180° | Trailing apertado (saída suave) | `0.5 × TrailPoints` |
| Fundo/topo confirmado | SL estrutural move para extremo do ciclo | — |

**Stop loss estrutural dinâmico (entrada):**

```
SL_pts = ATR14(t) × min(2.0, T_final(t) / 10)
```

Cabeça 1 também descreve: “fundo/topo confirmado de ciclo vira stop”.

**Break-even:**

```
BE_ativo = (lucro_atual_pts >= InpBE_Pts)
Novo_SL  = preço_entrada + InpBE_Spread
```

**Trailing adaptativo monotônico:**

```
CycleStrength = 1.0 se CycleMode=1 | 0.6 se CycleMode=0
TrailPoints_V26 = AmplitudeNorm × InpTrailBasePct × CycleStrength
peak     = max(peak, price_atual)   # nunca recua
SL_trail = peak − TrailPoints_V26
```

Em ciclo forte o trailing é descrito como **66% mais apertado** que em ciclo fraco (1.0 vs 0.6).

**Saída por fase 180°:**

```
Saída_fase = (φ(t) − φ_entrada) ≥ π
```

Quando o ciclo completa meia volta desde a entrada, trailing cai para 50% do valor normal.

**Saída Hilbert clássica (seção 01):** “saída do quadrante ativo: fechar posição correspondente”.

**Take profit:** a seção 07 **não** define um TP operacional da V26. O backtest da seção 08 usa `TP=1500 pts` e `SL=400 pts` como **parâmetros do relatório de performance**, não como regra da gestão inteligente. Ver ambiguidades.

### Gestão de risco

- **Lote dinâmico:**  
  `Lot(t) = Equity × RiskPercent/100 / (ATR14(t) × TickValue × 10)`  
  `Lot = clamp(Lot, MinLot, MaxLot)`
- Modo alternativo: lote fixo `InpLotFix`.
- Backtest (seção 08): “lote dinâmico (**risco 1%**)”.
- O PDF **não** declara stop diário de 3%. Esse número está nas regras técnicas do projeto (`CLAUDE.md`), não neste PDF.

### Performance reportada (não é regra — só contexto)

Backtest 12 meses 2025, M5, risco 1%, TP=1500 pts, SL=400 pts, 4 cabeças ativas.

| Métrica | XAU/USD V26 | XAG/USD V26 |
|---|---|---|
| Trades | 280 | 310 |
| Win rate | 72.9% | 69.7% |
| Profit factor | 2.34 | 2.15 |
| Sharpe | 2.18 | 1.97 |
| Max DD | 8.3% | 10.4% |
| Retorno anual | 92.4% | 77.1% |

### Ambiguidades / lacunas do Modelo 1 (NÃO assumidas)

1. **Valor numérico de `N`** em `SMA(energy, N)` e “N barras consecutivas” — não aparece.
2. **`HighEnergy`**: limiar absoluto ou relativo não definido (só “energia rompe limiar após acumulação”).
3. **`threshold_atr`** da ruptura: o PDF não dá o multiplicador de ATR.
4. **`QuadranteOK`**: não formalizado além das transições Q4→Q1 / Q2→Q3.
5. **`T_min` e `T_max`** do clamp do período — não numéricos.
6. **`InpTrailBasePct`, `InpTrailStart`, `InpParcial1_Pts`, `InpParcial2_Pts`, `InpBE_Spread`, `SpreadLimitManual`, `RiskPercent` operacional** — só `InpBE_Pts=500`, parciais 30%/30% e risco 1% no backtest.
7. **Spread XAU 0.10 vs fórmula genérica 0.15** — o texto diz `ATR14 × 0.15` e, na frase seguinte, “XAU fator 0.10; XAG fator 0.20”.
8. **TP operacional vs TP de backtest (1500 pts)** — a gestão V26 é BE + parciais + trailing + 180°; 1500/400 aparecem só no relatório.
9. **Conflito Q1/Q3 (WCE) vs Q4→Q1 / Q2→Q3 (EBSW V26)** — o PDF apresenta os dois. A tripla confirmação da seção 04 usa as transições EBSW.
10. **`dx%` do ISOM** — não numérico neste PDF.
11. **Como a Cabeça 4 (`signalStrength`) e a Cabeça 3 (`confidence` / regime Extreme) bloqueiam ou autorizam a ordem** — não há limiar escrito.
12. **Unidade de “pts”** no XAU (pip/point MT5) — não definida.
13. **SSM 2D**: a equação de saída `y(t,v) =` está truncada no PDF (página 4). Coeficientes `k1, k2, α, λ1≈0.95, λ2≈0.5` são ilustrativos, não calibrados.
14. **Timeframe de live trading** — só M5 no backtest.

---

## Modelo 2 — Hilbert Transform + ISOM (WCE 2014)

### Identificação

| Campo | Valor extraído |
|---|---|
| Nome | High Frequency Trading for Gold and Silver Using the Hilbert Transform and Event Driven Volatility Modelling |
| Autores | Abdalla Kablan, Joseph Falzon (University of Malta) |
| Publicação | Proceedings of the World Congress on Engineering 2014 Vol II, London, 2–4 Jul 2014 |
| Páginas | 927–933 |
| Ativos | XAUUSD e XAGUSD (também testado em “various currencies”) |
| Papel | Base matemática citada pelo Modelo 1 (seção 01 do V26) |

### Timeframe(s)

- Dados principais: **high frequency, 5 minute, intraday**.
- Amostra Hilbert: XAUUSD e XAGUSD de **01/01/2010 a 15/02/2013**.
- Rolling window de avaliação: dataset **04/04/2004 a 04/04/2008**, janela de **6 meses**, deslocamento de **2 meses** → 20 simulações por par.
- Log de exemplo (Table 1, XAGUSD): horários no formato HH:MM (ex.: 09:05–10:15), consistente com barras de 5 minutos.

Não há M1, M15 ou outro TF declarado para a estratégia.

### Indicadores / condições usadas

Pipeline do Listing 1 (pseudo-código, n=3):

1. **ISOM** — para cada limiar `dx(%)`, conta Directional Changes `dc` por bin de horário `t` ao longo de `n` dias:  
   `ISOM(t | dx) = Σ N(dc | t ∈ t_bin)`  
   Um DC é reversão de preço ≥ `dx%` a partir de um extremo, decomponível em directional-change + overshoot (cita [6]).
2. **Filtro de sazonalidade:** “Filter out data with low numbers of directional changes”. Opera só nos horários de alta volatilidade dirigida — para evitar que a rotação de Hilbert “saia dos limites” em baixa volatilidade (problema citado de [3]).
3. **Smooth (WMA-4):**  
   `smooth(i) = (4*price(i) + 3*price(i-1) + 2*price(i-2) + price(i-3)) / 10`
4. **Detrender:**  
   `detrender(i) = 0.25*smooth(i) + 0.75*smooth(i-2) − 0.25*smooth(i-4) − 0.75*smooth(i-6)`
5. **Quadratura e in-phase (n=3):**  
   `Q1(i) = 0.25*detrender(i) + 0.75*detrender(i-2) − 0.25*detrender(i-4) − 0.75*detrender(i-6)`  
   `I1(i) = detrender(i-3)`
6. Truncamento teórico do FIR de Hilbert: o artigo discute `n=5` e `n=7`; o **código operacional usa n=3**. Coeficientes ideais: `C_n = (2/(π n)) · sin²(π n / 2)` para `n ≠ 0`, `C_0 = 0`.
7. Limitação declarada: Hilbert / frequência instantânea só é válida para sinal **monocomponente / narrow-band** (Huang 1998). O mercado é tratado como tendo um ciclo dominante “em frações significativas do tempo”.

O artigo **não** usa Roofing, EIT, EBSW, CycleMode, ATR, SSM, EMD/HHSA nem as 4 cabeças — isso é exclusivo do V26.

### Gatilhos de entrada (compra e venda)

Regra explícita (páginas 6–7, Figure 7):

- O plano I-Q é dividido em **4 quadrantes**.
- **BUY:** quando o sinal rotacional **entra no Quarter 1**. Mantém compra enquanto permanece em Q1.
- **SELL:** quando o sinal rotacional **entra no Quarter 3**. Mantém venda enquanto permanece em Q3.
- “The system is either on buy mode or on sell mode.”

O artigo **não** escreve `I>0, Q>0` / `I<0, Q<0`. Essa formalização dos sinais dos eixos é do PDF V26 (página 3), que interpreta o WCE 2014. No artigo original, a definição geométrica de Quarter 1 e Quarter 3 depende da Figure 5/7 (eixos I vs Q), cujo texto não rotula numericamente os sinais.

Filtro obrigatório: ISOM deve ter filtrado os horários de baixa contagem DC **antes** de aplicar Hilbert.

### Regras de saída (SL, TP, trailing)

- **Única regra de saída escrita:** fechar a posição quando o sinal **sai do quadrante ativo** (sai de Q1 para qualquer outro no caso de compra; sai de Q3 para qualquer outro no caso de venda).
- Table 1 mostra pares open/close com timestamps; não há SL, TP, trailing, break-even nem parciais.
- Não há menção a ATR, stop estrutural, ou take-profit fixo.

### Gestão de risco

- **Não especificada** no artigo (sem % de risco, sem lote, sem stop diário, sem magic number).
- Métricas de avaliação: Profit Factor, ROI, Sharpe, Sortino. Sharpe usa o retorno médio do subconjunto de treino como substituto da taxa livre de risco (não existe Rf intraday).

Resultados médios reportados (Table 2, “Hilbert ISOM strategy”):

| Par | Profit Factor | ROI | Sharpe | Sortino |
|---|---|---|---|---|
| XAUUSD | 1.0 | 0.19 | 0.21 | 0.10 |
| XAGUSD | 1.0 | 0.12 | 0.19 | 0.01 |

Conclusão dos autores: a estratégia é viável, mas ouro e prata têm componentes de volatilidade diferentes (liquidez). O Hilbert prático exige truncamento severo, o que introduz correções de lag.

### Ambiguidades / lacunas do Modelo 2 (NÃO assumidas)

1. **Definição algébrica exata de Quarter 1 e Quarter 3** — só geométrica nas figuras; o mapeamento `I>0,Q>0 = Q1` é do V26, não deste artigo.
2. **Valor de `dx%`** do ISOM — não numérico.
3. **Definição quantitativa de “low numbers of directional changes”** (corte do filtro ISOM).
4. **Largura dos time bins** do ISOM (minuto, 5 min, hora?).
5. **Preço usado:** `price(i)` no pseudo-código; não diz se é close, mid, bid ou ask. Table 1 mostra preços XAG ~18.xx.
6. **n=3 (código) vs n=5 (fórmula Q teórica)** — o artigo apresenta os dois; o Listing 1 é n=3.
7. **Sem SL/TP/risco** — qualquer gestão extra viria do V26 ou das regras do projeto, não deste PDF.
8. Dataset de simulação de performance (2004–2008 “various currencies”) vs amostra Hilbert ouro/prata (2010–2013) — dois períodos distintos.

---

## Relação entre os dois modelos

O V26 **cita** o WCE 2014 como fundamento (WMA, detrender, I/Q, quadrantes, ISOM) e **acrescenta** a camada operacional que o artigo não tem:

```
WCE 2014                         V26
---------                        ----
WMA-4                            WMA-4 (XAU) / WMA-5 (XAG)
Detrender Ehlers                 idem
Hilbert n=3 → I, Q               idem + Homodyne + T_clamp
ISOM como filtro de horário      ISOM + regressão logística (Cabeça 3)
Entrar Q1 / sair Q1              Entrar só na transição EBSW Q4→Q1
Entrar Q3 / sair Q3              Entrar só na transição EBSW Q2→Q3
                                 + Acumulação 3 critérios
                                 + Ruptura latched
                                 + CycleMode=1 obrigatório
Sem SL/TP                        SL ATR adaptativo, BE 500 pts,
                                 parciais 30+30, trailing AGC,
                                 saída 180°
```

Para implementar `strategy/pdf_strategies.py` na etapa seguinte, a regra **operacional completa** é a do V26; o WCE 2014 é o núcleo I-Q/ISOM. Onde o V26 for ambíguo, **não inventar**: perguntar.

---

## Perguntas obrigatórias antes de codar as regras

Não avancei nenhuma destas hipóteses. Preciso da sua decisão:

1. **Timeframe de live:** confirmar **M5** (único TF de backtest nos dois PDFs) ou outro?
2. **Qual conjunto de entrada vale no robô?**
   - (A) só V26 tripla confirmação (acumulação + ruptura + EBSW Q4→Q1 / Q2→Q3);
   - (B) Hilbert puro WCE (entra Q1/Q3, sai do quadrante);
   - (C) os dois como estratégias independentes selecionáveis.
3. **Parâmetros sem número no PDF** — preencher agora ou deixar como `TODO`/input?
   - `N` da energia, `threshold_atr`, `T_min`/`T_max`, `dx%` ISOM, `InpTrailBasePct`, `InpTrailStart`, `InpParcial*_Pts`, `InpBE_Spread`.
4. **TP:** usar os 1500 pts do backtest, ou **não usar TP fixo** (só BE + parciais + trailing + 180°), que é o que a seção 07 descreve?
5. **Spread XAU:** 0.10 (frase específica do ativo) ou 0.15 (fórmula genérica)?
6. **Stop diário 3% e magic 20250924:** entram como regras de plataforma (`CLAUDE.md`), já que **não estão nos PDFs**?
7. **Cabeças 3 e 4:** na primeira versão, filtram o sinal (bloquear se regime Extreme / `signalStrength` baixo) mesmo sem limiar no PDF, ou ficam desligadas até você definir o corte?

---

## Status da Etapa 1

- [x] PDFs movidos para `./pdfs/`
- [x] `pdfplumber` instalado (0.11.10)
- [x] Texto extraído (19 + 7 páginas)
- [x] Resumo estruturado em `./docs/modelos_extraidos.md`
- [ ] Código de trading — **não escrito**, conforme combinado

Aguardo confirmação (e respostas das perguntas 1–7) para a **Etapa 2**: `requirements.txt` + esqueleto dos arquivos, ainda sem lógica de ordem.
