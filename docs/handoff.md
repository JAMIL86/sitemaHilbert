# HILBERTI — Handoff e Estado de Arquitetura do Projeto

> **Data de Atualização:** 2026-09-26  
> **Sistema:** Hilberti (HFT XAU/USD & XAG/USD)  
> **Motor de Decisão:** Python (sole decision engine)  
> **Broker de Execução:** MetaTrader 5 (execution only)  
> **Versão Operacional:** V26 Precision Accumulation Breakout + WCE 2014 Shadow  
> **Status Global:** Etapas 1 a 8 concluídas. **Etapa 9 FASE 1 concluída** — backtest funcional, 90 testes verdes (a única falha, `test_mt5_headway_connection`, é ambiental: exige o terminal Headway aberto). FASE 2 (validação anti-overfitting) é a próxima.

---

## Skills Disponíveis (Etapa 9)

| Skill | Path | Uso Etapa 9 |
|---|---|---|
| `cost-mode` | `~/.claude/skills/cost-mode/` | ✅ Ativo |
| `backtest-expert` | `~/.claude/skills/backtest-expert/` | ✅ Walk-forward, out-of-sample, Monte Carlo |
| `edge-strategy-reviewer` | `~/.claude/skills/edge-strategy-reviewer/` | ✅ Veredicto PASS/REVISE/REJECT |
| `tdd` | `~/.agents/skills/tdd/` | ✅ Testes disciplinares |
| `dataviz` | bundled | ✅ Equity curve (paleta validada) |
| `code-review` | `~/.agents/skills/code-review/` | ✅ Git disponível (commit bc31b8c) |
| `claude-handoff` | `~/.agents/skills/claude-handoff/` | ✅ Atualização deste arquivo |

**IMPORTANTE:** Todas as skills do mattpocock estão em `~/.agents/skills/`, **NÃO** em `~/.claude/skills/`.

## Etapa 9 — Backtest Histórico

**Status:** FASE 1 concluída. FASE 2 (anti-overfitting) pendente.

**Módulos (todos commitados):**
- `backtest/downloader.py` — download MT5 histórico + validação (gaps, ordem, precos)
- `backtest/engine.py` — execução barra a barra do V26 sem lookahead
- `backtest/metrics.py` — win rate, PF, max DD, Sharpe, Sortino
- `backtest/report.py` — markdown + equity curve (eixo Y único, paleta validada)
- `tests/test_backtest.py` — 23 testes

**Decisões de arquitetura que não são óbvias no código:**

1. **As saídas vêm do V26, não do engine.** `BacktestEngine` não implementa
   take-profit nem stop próprio — delega a `V26Strategy.manage_open_trade()`,
   que aplica breakeven (+500 pts), parciais 30%/30%, trailing AGC e saída por
   inversão de fase 180°. O PDF declara "SEM Take Profit fixo", então não há TP.
   A primeira versão do engine reimplementava as saídas e produzia 23 trades
   com **zero** vencedores; delegar corrigiu para 16/41. Se alguém reintroduzir
   lógica de saída no engine, o resultado volta a distorcer.

2. **Janela de features = `df.iloc[max(0, i-window):i]`.** A barra `i` nunca entra
   na própria decisão. Há um teste que espia `FeatureEngineer.compute()` e
   compara o último timestamp da janela com o da barra corrente.

3. **Sharpe/Sortino anualizam pela densidade real de trades** (`_periods_per_year`).
   Fixar 252×78 (um trade por barra) inflava o Sharpe em ordens de grandeza.

**BUG DO EXIT LOGIC — causa raiz e correção (2026-09-26):**

A primeira versão do engine reimplementava as saídas: SL fixo de 50 pontos +
fechamento por "reversão de sinal". A reversão **nunca disparava** — o V26
reemite a mesma direção enquanto há posição aberta, então só uma mudança real
de lado fecharia o trade, e isso praticamente não acontecia.

Sintoma medido: 23 trades, **0 vencedores**, 100% mortos no stop inicial.

Causa raiz: a engine tratava a estratégia como emissora de *entradas* e
inventava a política de *saída*. A API correta é
`V26Strategy.manage_open_trade()` (`strategy/pdf_strategies.py`), que já
implementa breakeven (+500 pts), parciais 30%/30%, trailing AGC e saída por
inversão de fase 180°.

Correção: o engine passou a delegar. Resultado medido: 41 trades, 16
vencedores, 16 saídas por `TRAIL`. Nenhum take-profit foi inventado — o PDF
declara "SEM Take Profit fixo".

**ACHADO CRÍTICO PARA A AUDITORIA (não resolvido):**

`sl_points` médio = **6,5** (unidades de preço) contra `inp_be_pts = 500`.
A distância entre o breakeven e o stop típico é de ~77×. Consequência
prática: o breakeven e as parciais **nunca disparam** em M5, e toda saída
lucrativa depende exclusivamente do trailing stop.

Hipóteses a verificar antes de qualquer ajuste (NÃO ajustar sem confirmar):
(a) o PDF pode expressar "pontos" em unidades diferentes das que o MT5 usa
para XAUUSD-VIP; (b) `inp_be_pts=500` pode ser um valor herdado de outro
instrumento; (c) pode estar correto e o SL de ~6,5 é que está errado.

**O BACKTEST ATUAL NÃO É CONCLUSIVO:**

Rodou sobre **1 200 barras sintéticas** (`tests/test_backtest.py::_synthetic`,
`rng = default_rng(7)`, vol 2,5 em torno de 2350). Resultado: PF 0.532,
P&L −30,24 USD, win rate 39,0%, 41 trades.

Esses números **não dizem nada sobre a borda da estratégia** — são
artefatos de um processo aleatório sem estrutura de mercado (sem vol
clustering, sem gaps de sessão, sem tendência persistente). FASE 2
(walk-forward, out-of-sample, Monte Carlo) sobre dados sintéticos seria
desperdício: mediria a consistência de um gerador de números, não do V26.

**Próximo passo obrigatório:** baixar dados reais do MT5 (XAUUSD-VIP M5,
6 meses), rodar o engine, e só então avaliar FASE 2.

**Configuração GitHub (pendente):**
- User: JAMIL86
- Email: veloxbrcaldas@gmail.com
- Repo: https://github.com/JAMIL86/sitemaHilbert.git

**Flags de segurança (inalteradas em toda a Etapa 9):**
```
dry_run = True
live_trading = False
```

**Git:** commit `01bc865` | branch: main | `Executor` nunca importado por `backtest/`

---

## 1. Estado Atual do Projeto

| Etapa | Descrição | Status | Detalhes |
|---|---|---|---|
| **Etapa 1** | Leitura dos PDFs e extração de regras | **100% Concluída** | `docs/modelos_extraidos.md` gerado |
| **Etapa 2** | Estrutura de arquivos e dependências | **100% Concluída** | `requirements.txt` instalado, esqueleto completo montado |
| **Etapa 3** | Parser de PDF automatizado com JSON | **100% Concluída** | `ai/pdf_extractor.py` gerou `docs/modelos_extraidos.json` (27 parâmetros validados) |
| **Etapa 4** | Funções DSP isoladas e testes matemáticos | **100% Concluída** | `ai/feature_engineer.py` e `tests/test_features.py` (10/10 testes matemáticos verdes) |
| **Etapa 5** | Motores de Estratégia V26 + WCE Shadow | **100% Concluída** | `strategy/pdf_strategies.py` e `tests/test_strategy.py` (12/12 testes operacionais verdes) |
| **Etapa 6** | Integração MT5 e Coleta de Market Data | **Próxima Etapa** | `core/mt5_connector.py`, `core/market_data.py`, `core/executor.py` |
| **Etapa 7** | IA/ML e Shadow Logging (ISOM + Gating) | *Pendente* | `ai/pattern_detector.py`, `ai/model_trainer.py` |
| **Etapa 8** | Dashboard Web Interativo (Streamlit) | *Pendente* | `web/dashboard.py`, visualização em tempo real |
| **Etapa 9** | Loop Principal e Testes de Conexão ao Vivo | *Pendente* | `main.py`, dry-run live test |

---

## 2. Resultado Detalhado dos 25 Testes Unitários Aprovados (Pytest 100% Verde)

```text
============================= test session starts =============================
platform win32 -- Python 3.11.7, pytest-8.3.4, pluggy-1.5.0
rootdir: C:\Users\Jamil_treder\OneDrive\Documentos\Meu_Projetos\Hilberti
collected 25 items

tests/test_extractor.py::test_pdf_extractor_rules_structure PASSED       [  4%]
tests/test_extractor.py::test_pdf_extractor_key_numbers_validation PASSED [  8%]
tests/test_extractor.py::test_json_persisted_file_matches_rules PASSED   [ 12%]
tests/test_features.py::test_wma_known_weights PASSED                    [ 16%]
tests/test_features.py::test_detrender_fir_linear_rejection PASSED       [ 20%]
tests/test_features.py::test_hilbert_fir_quadrature_90_degrees PASSED    [ 24%]
tests/test_features.py::test_cycle_mode_threshold_activation PASSED      [ 28%]
tests/test_features.py::test_ebsw_amplitude_bounded_between_minus_one_and_plus_one PASSED [ 32%]
tests/test_features.py::test_homodyne_discriminator_cycle_recovery PASSED [ 36%]
tests/test_features.py::test_roofing_filter_and_supersmoother PASSED     [ 40%]
tests/test_features.py::test_agc_normalization PASSED                    [ 44%]
tests/test_features.py::test_atr14_calculation PASSED                    [ 48%]
tests/test_features.py::test_feature_engineer_pipeline_complete PASSED   [ 52%]
tests/test_strategy.py::test_v26_quadrant_detection PASSED               [ 56%]
tests/test_strategy.py::test_v26_accumulation_detection PASSED           [ 60%]
tests/test_strategy.py::test_v26_breakout_latch PASSED                   [ 64%]
tests/test_strategy.py::test_v26_spread_filter PASSED                    [ 68%]
tests/test_strategy.py::test_v26_initial_structural_sl PASSED            [ 72%]
tests/test_strategy.py::test_v26_buy_and_sell_signals PASSED             [ 76%]
tests/test_strategy.py::test_v26_cooldown_rejection PASSED               [ 80%]
tests/test_strategy.py::test_v26_trade_management_breakeven PASSED       [ 84%]
tests/test_strategy.py::test_v26_trade_management_partials PASSED        [ 88%]
tests/test_strategy.py::test_v26_trade_management_trailing_and_phase_reversal PASSED [ 92%]
tests/test_wce2014_shadow_signals PASSED                                 [ 96%]
tests/test_strategy_router_integration PASSED                           [100%]

============================= 25 passed in 1.58s ==============================
```

### Detalhamento por Módulo

1. **`tests/test_extractor.py` (3 testes - Etapa 3):**
   - `test_pdf_extractor_rules_structure`: Valida integridade da árvore de regras extraídas dos PDFs.
   - `test_pdf_extractor_key_numbers_validation`: Valida os 27 parâmetros críticos numéricos com tolerância zero.
   - `test_json_persisted_file_matches_rules`: Valida o arquivo persistido `docs/modelos_extraidos.json`.

2. **`tests/test_features.py` (10 testes - Etapa 4):**
   - `test_wma_known_weights`: Valida filtros WMA-4 (XAU) e WMA-5 (XAG).
   - `test_detrender_fir_linear_rejection`: Valida rejeição DC e tendências lineares do FIR de 7 barras.
   - `test_hilbert_fir_quadrature_90_degrees`: Valida quadratura I/Q (~90°) e ortogonalidade sobre onda senoidal pura.
   - `test_cycle_mode_threshold_activation`: Valida ativação/desativação do CycleMode no limiar de amplitude $|\sin| > 0.85$.
   - `test_ebsw_amplitude_bounded_between_minus_one_and_plus_one`: Valida limitação estrita de amplitude da EBSW em $[-1.0, +1.0]$.
   - `test_homodyne_discriminator_cycle_recovery`: Valida recuperação do período de ciclo dominante via discriminador homódino.
   - `test_roofing_filter_and_supersmoother`: Valida atenuação de ruído de alta frequência e remoção de drift DC.
   - `test_agc_normalization`: Valida normalização adaptativa de amplitude em torno de 1.0.
   - `test_atr14_calculation`: Valida cálculo exato do True Range e Wilder RMA ATR14.
   - `test_feature_engineer_pipeline_complete`: Valida pipeline ponta a ponta gerando `DSPFeatures`.

3. **`tests/test_strategy.py` (12 testes - Etapa 5):**
   - `test_v26_quadrant_detection`: Valida classificação dos 4 quadrantes analíticos no plano complexo I/Q.
   - `test_v26_accumulation_detection`: Valida regras da Head 2 (energia Roofing baixa, EIT flat e CycleMode ativo).
   - `test_v26_breakout_latch`: Valida rompimento de alta/baixa além da Instantaneous Trendline com margem ATR.
   - `test_v26_spread_filter`: Valida limite de spread dinâmico ($\le 0.10 \cdot \text{ATR}$ para XAU e $\le 0.20 \cdot \text{ATR}$ para XAG).
   - `test_v26_initial_structural_sl`: Valida fórmula do Stop Loss $\text{ATR14} \cdot \min(2.0, T/10.0)$.
   - `test_v26_buy_and_sell_signals`: Valida geração e validação de sinais completos de BUY ($Q_4 \to Q_1$) e SELL ($Q_2 \to Q_3$).
   - `test_v26_cooldown_rejection`: Valida bloqueio estrito de reentradas com menos de 3 barras.
   - `test_v26_trade_management_breakeven`: Valida acionamento de Breakeven em $+500.0$ pontos com proteção de $+10.0$ pontos.
   - `test_v26_trade_management_partials`: Valida execução de Parcial 1 ($30\%$) em $+500$ pts e Parcial 2 ($30\%$) em $+1000$ pts.
   - `test_v26_trade_management_trailing_and_phase_reversal`: Valida trailing stop monotônico adaptativo (AGC + Ciclo) e aperto de stop em $180^\circ$ de reversão de fase.
   - `test_wce2014_shadow_signals`: Valida geração paralela de sinais shadow do modelo WCE 2014 em Q1 e Q3.
   - `test_strategy_router_integration`: Valida orquestração unificada de decisão executiva, logs de shadow WCE e shadow ML.

---

## 3. Decisões Arquiteturais e Flags de Segurança Confirmadas

1. **Invariante Fundamental:**  
   O Python é o **único motor de inteligência e tomada de decisão**. O MetaTrader 5 atua estritamente como broker de execução (envio de ordens `BUY`/`SELL`/`MODIFY_SL`/`PARTIAL_CLOSE`/`CLOSE`). Nenhuma lógica ou cálculo indicador reside no terminal MT5.
2. **Flags de Segurança Operacional:**  
   - `dry_run = True` (Default de fábrica; impede envio de ordens reais ao MT5 até liberação explícita).  
   - `magic_number = 20250924` (Isolamento total de ordens do robô contra operações manuais ou de outros robôs).  
   - `risk_percent_per_trade = 1.0%` (Dimensionamento de lote restrito a 1% do saldo líquido por operação).  
   - `daily_stop_percent = 3.0%` (Circuit breaker diário automático com bloqueio de novas operações ao atingir 3% de drawdown).  
   - `spread_default = 0.15` (Fator de ATR de fallback; em live lê o spread real em tempo real do MT5).  
3. **Timeframe Operacional:**  
   $M5$ (barras de 5 minutos) para ouro (`XAUUSD`) e prata (`XAGUSD`).
4. **Papel dos Modelos dos PDFs:**  
   - **Modelo V26 (*Hilbert Cycle + Chimera SSM*):** Motor de execução ativo (Active Decision Engine).  
   - **Modelo WCE 2014 (*Hilbert Transform + Directional Changes ISOM*):** Execução paralela em modo sombra (*Shadow Mode*), gerando telemetria comparativa.  
   - **Heads 3 (ISOM) e 4 (Gating):** Modo sombra (*Shadow Mode*) na v1 para coleta de dados durante 2 a 3 semanas antes de ativação de filtros restritivos.

---

## 4. Parâmetros em `TODO` (Não Inventar — Calibrar via Backtest)

Mantidos explicitamente em `config/settings.py` como `None` (ou com fallbacks documentados), sem valores arbitrários:

| Parâmetro | Campo no Settings | Significado | Tratamento no Código |
|---|---|---|---|
| $T_{\min}$ | `t_min` | Período mínimo do ciclo homódino | Fallback seguro: `6.0` barras |
| $T_{\max}$ | `t_max` | Período máximo do ciclo homódino | Fallback seguro: `50.0` barras |
| $dx\%$ | `isom_dx_percent` | Limiar percentual de Directional Changes (WCE) | `None` (`# TODO: calibrar via backtest`) |
| $N$ | `accumulation_energy_n` | Janela de barras para SMA da energia de acumulação | `None` / default `20` barras |
| $\text{Threshold}_{\text{ATR}}$ | `breakout_threshold_atr` | Margem de rompimento da Linha de Tendência (EIT) | `None` / default `0.5 * ATR14` |

---

## 5. Regra Operacional Exata do Modelo V26

### 5.1 Pipeline de DSP
1. **Suavização WMA Especializada:**  
   - XAUUSD: WMA-4 com pesos $[4, 3, 2, 1] / 10.0$.  
   - XAGUSD: WMA-5 com pesos $[5, 4, 3, 2, 1] / 15.0$.
2. **Detrender FIR de 7 Barras:**  
   $\text{det}(i) = 0.25 \cdot c(i) + 0.75 \cdot c(i-2) - 0.25 \cdot c(i-4) - 0.75 \cdot c(i-6)$
3. **Transformada Discreta de Hilbert FIR ($n=3$):**  
   $Q_1(i) = 0.25 \cdot \text{det}(i) + 0.75 \cdot \text{det}(i-2) - 0.25 \cdot \text{det}(i-4) - 0.75 \cdot \text{det}(i-6)$  
   $I_1(i) = \text{det}(i-3)$
4. **Fase Instantânea e Discriminador Homódino:**  
   $\Delta\phi = |\text{atan2}(I_{t-1} Q_t - I_t Q_{t-1}, I_t I_{t-1} + Q_t Q_{t-1})|$  
   $T(t) = \text{EMA}_{0.5}(2\pi / \Delta\phi)$ limitado em $[T_{\min}, T_{\max}]$.
5. **Roofing Filter & Linha de Tendência Instantânea (EIT):**  
   $\text{HP}(t) = (1 - \alpha)(p_t - p_{t-1}) + \alpha \text{HP}_{t-1}$, com $\alpha = 0.707$.  
   $\text{Roofing}(t) = \text{SuperSmoother2P}(\text{HP}(t), \text{cutoff}=10)$.  
   $\text{IT}(t) = [3 \cdot \text{Roofing}(t) + 2 \cdot \text{Roofing}(t-1) + \text{Roofing}(t-2)] / 6.0$.
6. **Even Better Sine Wave (EBSW):**  
   $\text{Sine}(t) = \sin(\phi_t + \pi/4)$ (avanço de 45°).  
   $\text{LeadSine}(t) = \sin(\phi_t + 3\pi/4)$ (avanço de 135°).
7. **Regime Filter (CycleMode):**  
   $\text{CycleMode} = 1$ se $|\text{Sine}| > 0.85$ ou $|\text{LeadSine}| > 0.85$; caso contrário $0$.
8. **Controle Automático de Ganho (AGC):**  
   $\text{AmplitudeNorm}(t) = \text{Amp}(t) / \text{SMA}_{50}(\text{Amp})$.

### 5.2 Gatilhos de Entrada
- **COMPRA (`BUY`):**
  1. Transição de Fase: $Q_4 \to Q_1$ ($\text{Sine}$ cruza acima de $\text{LeadSine}$ no Quadrante 4).
  2. Filtro de Regime: $\text{CycleMode} == 1$.
  3. Acumulação Prévia: $\text{Roofing\_Energy} < 0.5 \cdot \text{SMA}(\text{Roofing\_Energy}, N)$ E $|\text{IT}(t) - \text{IT}(t-1)| < 0.0005 \cdot \text{price}$.
  4. Rompimento de Alta: $\text{Price} > \text{IT} + \text{Threshold}_{\text{ATR}}$.
  5. Cooldown: Mínimo de 3 barras desde a última entrada.
  6. Spread Máximo: Spread real $\le 0.10 \cdot \text{ATR14}$ (XAU) ou $\le 0.20 \cdot \text{ATR14}$ (XAG).

- **VENDA (`SELL`):**
  1. Transição de Fase: $Q_2 \to Q_3$ ($\text{Sine}$ cruza abaixo de $\text{LeadSine}$ no Quadrante 2).
  2. Filtro de Regime: $\text{CycleMode} == 1$.
  3. Acumulação Prévia: $\text{Roofing\_Energy} < 0.5 \cdot \text{SMA}(\text{Roofing\_Energy}, N)$ E $|\text{IT}(t) - \text{IT}(t-1)| < 0.0005 \cdot \text{price}$.
  4. Rompimento de Baixa: $\text{Price} < \text{IT} - \text{Threshold}_{\text{ATR}}$.
  5. Cooldown: Mínimo de 3 barras desde a última entrada.
  6. Spread Máximo: Spread real $\le 0.10 \cdot \text{ATR14}$ (XAU) ou $\le 0.20 \cdot \text{ATR14}$ (XAG).

### 5.3 Regras de Saída e Gestão de Posição
- **Stop Loss Estrutural Inicial:**  
  $\text{SL}_{\text{pontos}} = \text{ATR14} \cdot \min(2.0, T_{\text{final}} / 10.0)$.
- **Take Profit Fixo:**  
  **Nenhum TP Fixo.** Saídas orientadas a ciclo e volatilidade.
- **Breakeven:**  
  Ao atingir $+500.0$ pontos de lucro, mover SL para o preço de entrada $+ 10.0$ pontos de proteção.
- **Parciais Automáticas:**  
  - Parcial 1: Encerra $30.0\%$ do lote no primeiro alvo dinâmico ($+500$ pts ou $\text{EBSW}$ cross).  
  - Parcial 2: Encerra $30.0\%$ do lote no segundo alvo ($+1000$ pts).  
  - Lote Remanescente ($40\%$): Segue no trailing stop.
- **Trailing Stop Adaptativo (AGC + Ciclo):**  
  $\text{TrailPoints} = \text{AmplitudeNorm} \cdot \text{InpTrailBasePct} \cdot \text{CycleStrength}$  
  $\text{CycleStrength} = 1.0$ se $\text{CycleMode} == 1$; $\text{CycleStrength} = 0.6$ se $\text{CycleMode} == 0$.  
  Ajuste monotônico (nunca afasta o SL).
- **Saída por Inversão de Fase (Phase Reversal 180°):**  
  Quando a variação acumulada de fase atinge $180^\circ$ ($\pi$ radianos) contra a direção da ordem: aperta o trailing stop para $0.5 \cdot \text{TrailPoints}$ para saída suave.

---

## 6. Inventário Completo dos Arquivos Criados

- `config/settings.py`: Classe Pydantic `Settings` com leitura de `.env`, credenciais do MT5, flags de segurança (`dry_run=True`), regras DSP e parâmetros V26.
- `ai/pdf_extractor.py`: Extrator de PDFs com `pdfplumber`, gerador estruturado de `modelos_extraidos.json` e validador estrito de 27 números-chave.
- `ai/feature_engineer.py`: Módulo matemático DSP contendo funções isoladas de John Ehlers (WMA, Detrender, Hilbert FIR, Homódino, Roofing, EBSW, AGC, ATR) e classe `FeatureEngineer`.
- `strategy/pdf_strategies.py`: Motores de estratégia `V26Strategy` (ativo com gestão completa de trades), `WCE2014Strategy` (shadow mode) e `StrategyRouter`.
- `docs/modelos_extraidos.md`: Documentação completa em Markdown dos modelos V26 e WCE 2014 extraídos dos PDFs.
- `docs/modelos_extraidos.json`: Estrutura JSON com todos os parâmetros, filtros e fórmulas dos modelos extraídos.
- `docs/handoff.md`: Registro vivo de continuidade arquitetural, inventário e estado de validação do projeto.
- `tests/test_extractor.py`: Testes unitários para integridade da extração de regras e dos 27 parâmetros-chave dos PDFs.
- `tests/test_features.py`: 10 testes unitários matemáticos para todas as funções DSP (senóides conhecidas, quadratura 90°, CycleMode, EBSW bounded $[-1, 1]$, AGC, ATR).
- `tests/test_strategy.py`: 12 testes unitários para a estratégia V26 (quadrantes, acumulação, breakout, spread, SL, BE, parciais, trailing, fase 180°), WCE Shadow e Router.
- `requirements.txt`: Dependências fixadas e instaladas no ambiente (numpy, pandas, scipy, loguru, pydantic-settings, pdfplumber, MetaTrader5, streamlit, pytest).
- `.env.example`: Modelo de configuração de variáveis de ambiente e credenciais MT5.
- `.gitignore`: Configuração de exclusão de artefatos temporários, caches, logs e credenciais.
- `core/mt5_connector.py`: Esqueleto inicial para conexão resiliente, autenticação e heartbeat com o terminal MetaTrader 5.
- `core/market_data.py`: Esqueleto inicial para coleta e streaming de dados de mercado (OHLCV M5 e ticks).
- `core/executor.py`: Esqueleto inicial para gestão de execução de ordens, dimensionamento de risco e compliance com `dry_run`.
- `ai/pattern_detector.py`: Detecção de padrões com RandomForest sobre features do `FeatureEngineer`; heurísticas de acumulação e breakout. Sempre retorna `filters_entry=False` (shadow).
- `ai/shadow_logger.py`: Log de sinais em JSONL com rotação diária (`logs/shadow_YYYYMMDD.jsonl`). **Nunca chama o `Executor`** — levanta `ValueError` se receber um executor.
- `ai/model_trainer.py`: Treinamento com **split temporal obrigatório** (nunca aleatório — evita lookahead bias), StandardScaler + RandomForest, persistência em `ai/models/pattern_v1.pkl`.
- `docs/model_performance.md`: Métricas do modelo e próximos passos de calibração.
- `tests/test_ai.py`: 7 testes de IA/ML (acumulação, breakout, série aleatória, escrita JSONL, `executor=None`, split temporal, salvamento do modelo).
- `tests/test_mt5_connection.py`: Teste de conexão MT5 **ao vivo**. Exige o terminal Headway aberto; fora da suíte padrão.
- `test_mt5_manual.py`: Script manual de verificação de conexão com o terminal.
- `web/dashboard.py`: Dashboard Streamlit somente leitura. Cache `@st.cache_data(ttl=5)` para o fetch e `@st.cache_resource` para o conector. Único botão de dado: **Reconectar**; único botão de controle: **Forçar refresh**. Nenhum botão de envio de ordem. Seções empilhadas: header → gráfico → sinais → **mercados relacionados (BTCUSD, monitoramento visual apenas, zero trading)** → posições → últimas ordens (`mt5.history_orders_get`, leitura) → logs shadow.
- `web/components/market_watch.py`: Widget de preço para símbolos **fora da allowlist do Executor** (BTCUSD). Não instancia estratégias, não chama shadow_logger, não toca executor. Rótulo explícito: "Monitoramento apenas — sem sinais".
- `web/components/chart_plotly.py`: Candles M5 + EMA 9/21 + Bollinger (20, 2.0) via Plotly. Um único eixo Y. Paleta validada pelo validador do skill `dataviz` (6/6 PASS em light e dark). Reusado para XAUUSD e BTCUSD.
- `web/components/signals_panel.py`: Três colunas — V26 (ativo) | WCE 2014 (shadow) | Cabeças 3/4 (shadow). Identidade de sinal por ícone + rótulo, nunca só por cor.
- `web/components/logs_viewer.py`: Leitura dos `shadow_*.jsonl` com filtro por modelo, tolerância a linha corrompida e rotação (`prune_old_logs`).
- `tests/test_dashboard.py`: 25 testes do dashboard (import, fetch com MT5 mockado, banner de modo com `dry_run`, logs ausentes/vazios/corrompidos, ausência de `order_send`, filtro por magic number em posições e ordens, eixos únicos, **isolamento do BTCUSD: V26 nunca recebe BTCUSD, BTCUSD fora da allowlist, market_watch sem importações de trading/logging, BTCUSD nunca hardcoded no dashboard, dry_run/live_trading inalterados**).
- `main.py`: Esqueleto inicial para o loop principal assíncrono de execução do Hilberti.

---

## 7. Etapas Concluídas

- **Etapas 1–5:** extração dos PDFs, DSP, estratégias V26/WCE, testes.
- **Etapa 6 — MT5:** `mt5.initialize()` travado no path do Headway
  (`C:\Program Files\Headway MT5 Terminal\terminal64.exe`) e **recusa de conexão se
  `account_info().login != 1045989`**. Símbolo corrigido para `XAUUSD-VIP`.
- **Etapa 7 — IA/ML + Shadow Logging:** ver inventário acima. Split temporal obrigatório.
- **Etapa 8 — Dashboard Streamlit:** ver inventário acima. Somente leitura, sem mutação de `strategy/`, `ai/` ou `core/`.
- **Etapa 9 FASE 1 — Backtest:** 4 módulos (`downloader`, `engine`, `metrics`,
  `report`) + 24 testes. Ver seção 9 abaixo.

---

## 9. Etapa 9 — Backtest com dados REAIS (2026-09-26, commit `b5656cf`)

O backtest anterior rodou em dados SINTÉTICOS (`default_rng(7)`) e **não era
conclusivo**. Este é o primeiro resultado sobre dado real.

### Dados

| Item | Valor |
|---|---|
| Fonte | MT5 Headway, conta 1045989, VTMarkets-Demo |
| Símbolo | XAUUSD-VIP M5 |
| Período | 2026-03-30 08:15 UTC a 2026-09-25 23:55 UTC |
| Barras | 35 359 |
| Arquivo | `backtest/data/XAUUSD-VIP_M5_2026-03-30_2026-09-25.csv` (2,4 MB) |

Sessão do ativo: **01:00–23:55 UTC, todo dia** (fecha 65 min/dia + fim de
semana). Os 129 "gaps" brutos da série são fechamentos, **não** barras
faltando. Lacuna real: 1 (3 barras, 2026-08-28).

### Resultado real (6 meses, 35 159 barras processadas, 0 puladas)

| Métrica | Sintético | **Real** |
|---|---|---|
| Trades | 41 | **1 746** |
| Win rate | 39,0% | **40,3%** |
| Profit factor | 0,532 | **0,929** |
| P&L | −30,24 USD | **−280,51 USD** |
| Max drawdown | — | **3,87%** |
| Sharpe | −17,70 | **−1,441** |
| SL médio | 6,5 | **8,64** (min 1,92, max 31,58) |
| Saídas | 16 SL / 16 TRAIL | **1 043 SL / 703 TRAIL** |

O Sharpe melhorou 12× porque agora reflete densidade real de trades
(1 746 trades / 179 dias), não ruído sintético.

### Veredito: **PF 0,929 < 1,0 → NÃO autorizar FASE 2**

Pela regra do responsável (PF > 1,3 autoriza; PF < 1 discutimos REVISE), o
resultado cai na faixa de **REVISE**. FASE 2 (walk-forward, out-of-sample,
Monte Carlo) **não deve rodar** até a causa ser entendida — fazer Monte Carlo
de um edge negativo só produziria bandas de confiança em torno de uma perda.

### AUDITORIA DO PARÂMETRO BE=500 — É BUG DE UNIDADE. NADA AJUSTADO.

Documentado em `docs/modelos_extraidos.md` §"Unidade de pontos — RESOLVIDO".

**Medido no terminal real:** `point = 0,01`, `tick_value = 1,00 USD`,
contract 100 oz. Logo 1 ponto MT5 = $0,01 de preço.

**O que o código faz:** `Position.get_profit_points()` (`pdf_strategies.py:70`)
retorna delta bruto de preço, e `manage_open_trade()` (linha 438) o compara
com `inp_be_pts = 500.0`. **BE só dispara em +$5,00 de preço.**

**Números medidos no dado real:** ATR14 médio = **5,198 USD** (519,8 pts
MT5). SL médio = 8,64 USD. `inp_be_pts=500` em delta de preço = **96 ATR**.

O BE está **96× mais longe que o SL inicial** — inalcançável, por isso as
parciais 30%/30% nunca disparam em M5. Confirmado pelo backtest: **zero
parciais**, e 1 043 das 1 746 saídas foram no stop inicial.

**Duas leituras possíveis, o PDF não decide:** (1) "pts" = pontos MT5, e o bug
é a conversão ausente em `get_profit_points()`; (2) "pts" = dollars de preço, e
500 é nominalmente implausível. A leitura 1 é a coerente — 500 pts MT5 ≈ 1 ATR.

**Correção proposta (NÃO APLICADA — aguarda aprovação):** converter
`get_profit_points()` para pontos MT5 (dividir por `point`) e ajustar
`calculate_initial_sl()` e `inp_be_pts` para a mesma unidade. Isso muda a
estratégia e precisa de aval explícito.

### Bugs corrigidos nesta rodada

1. **`mt5.initialize()` retornava `(-2, 'Invalid params')`** — o `MT5Connector`
   injeta `server=` do `.env` (VTMarkets-Demo) e num terminal já autenticado
   isso falha. `downloader._connect()` agora usa `mt5.initialize(path=)` sem
   `server=`; credenciais só entram se `mt5_login` estiver definido.
2. **Validação de gaps rejeitava dado íntegro** — contava fechamento de
   mercado como corrupção (129 gaps). Agora só conta buraco que não cruza a
   fronteira de sessão.
3. **`python -m backtest.downloader` / `.engine` não existiam** — sem bloco
   `__main__`. Adicionados.
4. **`KeyError: 'time'` no report** — `to_dict()` achata a equity numa Series;
   o report exigia `.columns` e `'time'`. Só aparecia **depois** de 12 min de
   backtest. Corrigido + teste de regressão.

## 10. Próxima Etapa

**Aguardando decisão do responsável sobre a unidade de BE.** O backtest real
está reprovado (PF 0,93). Não avançar para FASE 2 sem resolver a unidade e
re-rodar.

## 12. DECISÃO DO RESPONSÁVEL (2026-09-26) — ativar WCE 2014

**V26 reprovado no backtest real: PF 0,929** (6 meses, 35 359 barras,
1 746 trades, P&L −280,51 USD). Decisão: **ativar WCE 2014** como modelo
primário, V26 permanece disponível como comparação (não removido).

**Regras do WCE 2014** (citação literal em `docs/modelos_extraidos.md` §
"Modelo 2 — regras operacionais", extraídas de
`pdfs/WCE2014_pp927-933.pdf`, Figura 1 plano I-Q e Figura 5 transições):

| Regra | Regra |
|---|---|
| BUY | entrada no **Q1** (I > 0 e Q > 0); saída ao **deixar o Q1** |
| SELL | entrada no **Q3** (I < 0 e Q < 0); saída ao **deixar o Q3** |
| Filtro | ISOM pinpointa horários de alta volatilidade; sem `dx%` numérico no PDF, o filtro fica **desativado com warning** — nenhum threshold inventado |

**Referência:** `pdfs/WCE2014_pp927-933.pdf` — Figura 1 (resposta em
frequência do Hilbert transform), Figura 5 (princípio de rotação nos
componentes em fase/quadratura), Figura 7 (aplicação em estratégia).

### FASE 1 (WCE) — CONCLUÍDA: citações literais extraídas

Citações em `docs/modelos_extraidos.md` §"Gatilhos de entrada — CITAÇÕES
LITERAIS (2026-09-26)", extraídas de `_extract/WCE2014_pp927-933.txt`.
**O PDF não foi reprocessado** — `_extract/` já existia da Etapa 1.

Ressalva de extração: o pdfplumber **entrelaça as duas colunas** da página e
quebra o encoding das fontes (`dx(%)` sai como `dx(cid:1856)(cid:1876)%`).
As citações foram reconstruídas na ordem de leitura da coluna esquerda, e
isso está marcado no documento.

### 3 lacunas do PDF + decisões aprovadas

| # | Lacuna | Decisão do responsável |
|---|---|---|
| 1 | `Q1={I>0,Q>0}` **não está no WCE** — o artigo define Q1/Q3 geometricamente (Fig. 5/7). O mapeamento algébrico vem do **V26 p.3, seção Hilbert Transform** | ✅ **Autorizado**, documentado com a fonte |
| 2 | ISOM: o símbolo `dx(%)` aparece, o **valor numérico não existe** no artigo. "low numbers of directional changes" é qualitativo | ✅ Filtro **desativado com WARNING**, nenhum threshold inventado |
| 3 | WCE **não tem SL nenhum** — única regra escrita é "closed when the signal exits the quarter" | ✅ `calculate_initial_sl` do V26 (1,66 × ATR) como **guardrail de projeto**, rotulado `guardrail_projeto=True` e "não é regra do PDF" |

Detalhamento e citações que provam cada lacuna: `docs/decisoes_tecnicas.md` §7.

### Bug V26 CONFIRMADO no dado real

`losing_trades = 1043` e saídas `SL = 1043` — **coincidem exatamente**. Toda
saída de stop é perda e todo lucro vem do trailing (703 `TRAIL`). Nenhum trade
vencedor foi fechado no stop. Combinado com o BE inalcançável (§9), o V26
está operando como "corta-perda em 1,66 × ATR, sem nenhuma regra de
realização de lucro ativa".

## 11. Armadilhas conhecidas

Ver **`docs/decisoes_tecnicas.md`** — cada uma com a evidência que a sustenta:

1. `mt5.initialize()` com `server=` falha em terminal já autenticado → bypass
   do `MT5Connector` na leitura de histórico.
2. `mt5_login` é alias (`MT5_LOGIN`); passar por kwargs de campo é descartado
   silenciosamente por `extra="ignore"`.
3. "Gap > 10 min" rejeita dado íntegro em ativo de sessão limitada.
4. Bug de unidade BE=500 (diagnóstico, não corrigido).
5. `to_dict()` achata a equity — o report quebra no payload real, não na
   fixture do teste. Coberto por teste de regressão.
6. Backtest real PF 0,929 → faixa REVISE. Custos (spread/comissão) ainda não
   modelados.


---

## 12. Code review 1.0 do WCE 2014 — 3 hard violations, corrigir ANTES do backtest

Code review de standards contra `b4f6465` (FASE 2/3, ativação do WCE 2014 como
modelo primário). A spec tem 5 regras não-negociáveis; 4 passam, e há
**3 violações duras de padrão documentado** que bloqueiam o backtest do WCE.

### 1. CRÍTICO — `backtest_XAUUSD_VIP.md` sobrescreveu o baseline real do V26

O relatório versionado em `backtest/reports/` foi regenerado sobre **3 trades
sintéticos** (2026-01-05, PF 2.11, Sharpe 35.92), apagando o backtest real de
**1 746 trades** (PF 0.929, MaxDD 3.87%, Sharpe −1.44) que sustenta
`decisoes_tecnicas.md` §6.

Causa: `save_report` nomeia o arquivo só pelo **símbolo**
(`f"backtest_{result.get('symbol','xau')...}"`), sem modelo nem janela. Com
`active_model="wce"`, rodar o WCE no mesmo símbolo escreve por cima do V26.
O mesmo arquivo `_equity.html` segue o mesmo caminho.

Isto é exatamente a armadilha que §5 já documentou para o `to_dict()`: um
artefato formatado por caminho estável, sem identidade do run. E o §6 diz
que PF 0.929 é a **fonte da decisão de fase** — perdê-la não é perder
conveniência, é perder a baseline.

### 2. Guardrail de SL ausente no relatório

`decisoes_tecnicas.md` §9.3 exige o rótulo de guardrail em **três lugares**,
sendo o terceiro "docstring de `initial_sl` **e do relatório de backtest**".
O código cumpre os dois primeiros (`SL_GUARDRAIL_PROJETO`,
`metadata["guardrail_projeto"]`), mas `backtest/report.py` não foi tocado:
`build_markdown_report` não renderiza `model` nem `cost_model_desc`, que já
chegam prontos em `BacktestResult.to_dict()`. `grep -c guardrail` no `.md`
versionado = **0**. Um relatório do WCE mostra saídas `SL` sem dizer, uma vez,
que o artigo não define stop nenhum.

### 3. `slippage_pts=1.0` sem fonte, sob um docstring que nega chutes

`CostModel` afirma: *"Nenhum destes números é um chute"*. Mas dos quatro
campos, só `spread` e `point_size` têm fonte (medição no terminal, §9.5 e
`decisoes_tecnicas.md` §4). `slippage_pts = 1.0` é um número escolhido por
conveniência, e §9.5 só autoriza explicitamente o **fallback de spread 0.15**.
O docstring também é factualmente torto ao dizer que `commission=0` "não é
hipótese" enquanto afirma o oposto dos outros campos.

### Situação atual

Corrigido nesta sessão: baseline V26 restaurado a partir de `git show
b4f6465:backtest/reports/backtest_XAUUSD_VIP.md`; `build_markdown_report`
passa a renderizar modelo, custos e o aviso de guardrail; `CostModel` deixa de
negar chutes e rotula `slippage_pts` como hipótese declarada;
`save_report` inclui modelo e janela no nome do arquivo para que dois
modelos no mesmo símbolo não voltem a se sobrescrever.

**Pendente de decisão do responsável:** a escolha entre (a) remover
`slippage_pts` e deixar o spread 0.15 cobrir o custo, ou (b) manter 1.0
rotulado como hipótese. A instrução recebida cortou no ponto da escolha. A
recomendação é **(a)**: o spread de 0.15 USD já é ~0.03×ATR, e um slippage
adicional de 0.01 USD só distorce o PF de um modelo que ainda nem foi
medido — e some como diferença irrelevante ao lado do spread.

**Ainda não rodar o backtest do WCE** até (a) ou (b) estar decidido, e
qualquer backtest novo deve ir para `--model wce` com nome de arquivo
distinto, nunca para `backtest_XAUUSD_VIP.md`.

## 13. WCE 2014 medido, veredito REVISE, rebaixado de primário (2026-09-26)

### 13.1 O que foi medido

Mesmo dado, mesma janela, mesmos custos dos dois modelos. Custos: spread 0,34
lido do MT5 ao vivo, slippage 1 pt/trade (HIPÓTESE declarada, não medição da
corretora), comissão 0 (conta VIP).

| | V26 | WCE 2014 | Artigo (Tab. 1) |
|---|---:|---:|---:|
| Trades | 1746 (9,72/dia) | 894 (4,98/dia) | — |
| Win rate | 37,7% | 42,6% | — |
| Profit factor | 0,795 (0,929 s/ custos) | 0,879 | 1,0 |
| P&L | -891,61 USD | -268,10 USD | ROI 0,19% |
| Max DD | 9,66% | 2,96% | — |
| Sharpe | -4,579 | -1,952 | 0,21 |
| Custo total | 611,10 USD | 312,90 USD | não declarado |
| Saídas | SL 1043 / TRAIL 703 | SL 165 / QUADRANT 729 | — |

O WCE ganha do V26 em tudo que é medido. **Nenhum dos dois é lucrativo.** E o
PF do artigo é 1,0 — pelos próprios autores, break-even, com ROI 0,19% contra
0,20 de Buy-and-Hold. "Superar o artigo" aqui significa superar o zero.

### 13.2 Veredito: REVISE

`edge-strategy-reviewer`, mais duas achadas que mudam o enquadramento:

**`active_model` não fazia nada no caminho vivo.** `StrategyRouter.decide()`
tinha `execute = v26_decision.signal in ("BUY","SELL")` fixo. O default "wce"
mudava o backtest, o log do `main.py` e a docstring — e a execução seguia no
V26. O sistema dizia uma coisa e fazia outra. Corrigido: `decide()` despacha
por `settings.active_model` e expõe `modelo_ativo` na decisão.

**O ISOM é ENTRADA do Hilbert, não filtro** — quarta lacuna, maior que as três
de §7. Detalhe e literal em `decisoes_tecnicas.md` §9.6. Consequência: o WCE
medido é o artigo **menos o condicionamento de horário**, mais um stop de outra
fonte. Um híbrido que não está em nenhum dos dois papers.

### 13.3 Decisões do responsável

1. `active_model` corrigido no caminho vivo **e** default revertido para `"v26"`.
2. `wce_shadow = True` de novo. O WCE fica em sombra até os gates abaixo.
3. Nada removido: `--model wce` e `ACTIVE_MODEL=wce` continuam funcionando.

### 13.4 Gates para re-promover o WCE

- [ ] ISOM-tempo implementado como **pré-condicionamento** do `i1`/`q1`, ou
      retirada do enquadramento como "replicação"
- [ ] ≥ 2 anos de XAUUSD cobrindo mais de um regime
- [ ] XAGUSD ou outro ativo, para não ser um resultado de um só instrumento
- [ ] Janela out-of-sample, separada do ajuste
- [ ] PF > 1 **com custos**, não comparável a um PF provavelmente bruto do artigo
- [ ] `sl_points` da fórmula do V26 conferido em unidades de MT5
      (ver `decisoes_tecnicas.md` §4 — correção de `inp_be_pts=500` ainda não
      aplicada)

### 13.5 Pendências abertas

- **Correção de unidade do BE (500 pts)**: proposta e documentada em §4, nunca
  aplicada. Continua pendente de decisão.
- **Slippage de 1 pt**: permanece HIPÓTESE declarada no docstring do `CostModel`.
  Medir na corretora é a única forma de promoted a medição.

### 13.6 Auditoria do guardrail (FASE 4) — o número que mais importa

O relatório do WCE separa **qual regra** encerrou cada posição:

| Encerrado por | Fonte da regra | Trades | P&L |
|---|---|---:|---:|
| SL (stop guardrail) | **V26, não o PDF** | 165 (18,5%) | −1221,62 USD |
| QUADRANT | **WCE 2014, literal** | 729 (81,5%) | +953,52 USD |

A lógica que é realmente do artigo (+953,52) é **menor em magnitude** que a
perda produzida pelo stop emprestado do V26 (−1221,62). O total de −268,10 é a
diferença entre as duas. Numa variante do WCE **sem** guardrail o resultado
seria materialmente diferente — e unknowable, porque o artigo não diz o que
fazer quando o preço se move contra a entrada dentro do quadrante.

Este é o número a ler antes de qualquer promoção: não é "18,5% dos trades
dependem do stop", é "o stop de outra fonte perde mais dinheiro do que a regra
do artigo ganha".

### 13.7 Custos: a contabilidade fecha

V26 sem custos −280,51 → com custos −891,61. Diferença 611,10 = exatamente o
`total_costs` medido. Os dois relatórios com custos estão em diretórios
próprios (`backtest/reports/v26_custos/`, `wce_custos/`) e a baseline
`backtest_XAUUSD_VIP.md` segue intacta com 1746 trades / PF 0,93.

Com spread medido de 0,34 (não o fallback de 0,15) o V26 cai de PF 0,929 para
0,795. Qualquer conclusão anterior que cite 0,929 **não inclui custos** e
precisa ser lida assim.

---

## 14. Variantes WCE medidas — o "+$953,52" era survivorship bias (2026-09-27)

### 14.1 O achado anterior estava errado

`docs/wce2014_source_of_truth.md` §3.2 e §5 afirmavam que "sem o guardrail o
WCE original seria lucrativo (+$953,52)". **Isso não se sustenta.** O número
foi obtido *filtrando* os trades perdedores do stop (165 SL, −1.221,62) dos 729
restantes (+953,52) e somando os sobreviventes — preservando a ordem temporal,
mas com a decisão de manter o trade tomada *depois* de ver o resultado. Isso é
survivorship bias: não é uma estratégia executável, é uma seleção sobre uma
série já fechada.

A variante A real (`--model wce_quadrant`, sem SL e sem TP, saída só por
travessia de quadrante) foi rodada sobre os mesmos 35.359 barras, com custos:

| Métrica | A: Quadrant (puro) | `wce` (com guardrail) |
|---|---:|---:|
| Trades | 894 | 894 |
| Win rate | 44,4% | 42,6% |
| Profit factor | **0,887** | 0,88 |
| P&L | **−257,81** | −268,10 |
| Max drawdown | 3,59% | 2,96% |
| Sharpe | **−1,699** | −1,95 |

Tirar o stop **não** recupera os 953. O total fica praticamente igual (a
diferença de 10,29 é a mudança de uma handful de saídas). O guardrail do V26
**não** estava destruindo o WCE: ele estava apenas rearranjando quem saía
quando. O §13.6 deste arquivo erra ao atribuir a −1.221 ao "stop emprestado" —
esse número é a subtração manual de dois subconjuntos escolhidos a posteriori.

### 14.2 Por que o WCE puro não sobe

O gate `if self.open_trade is None` impede abrir enquanto há posição. Sem
guardrail, cada trade fica aberto até o quadrante virar, o que consome a janela
e suprime entradas seguintes. A sequência de 894 sinais é a mesma com e sem
stop (o guardrail nunca matou uma entrada que a lógica pura não teria tomado),
mas o *caminho* difere.

### 14.3 TP=500 não disparava — e a causa NÃO era geometria (ver §14.6)

`wce_quadrant_tp` (TP fixo de 500 pts) rodou e saiu **byte-idêntico** à
variante A: 894 trades, PF 0,887, −257,81, e `Saidas: {'QUADRANT': 894}` —
**zero** trades encerrados por TP.

**A explicação que escrevi aqui inicialmente estava errada.** Eu havia
concluído que 500 pts era geometricamente inalcançável, e o número que usei
para sustentar isso era a entrada 4617,50 do *primeiro trade* somada a 500.
Um único trade não estabelece uma impossibilidade. Verificado contra o
dataset inteiro: a mediana de close é 4393,66, e 4393,66 + 5,00 USD cabe
folgadamente no máximo de 4889,35. A premissa não se sustentava.

A causa real está em §14.6: era um bug de **unidade**, não de mercado.
A seção fica aqui porque o sintoma (zero TPs) foi o que abriu a
investigação, mas a conclusão correta é a da §14.6.

### 14.4 Próximo passo (executado — ver §14.6)

Reescalar o TP de 500 → **50 pontos** (0,50 USD). Variante C mantém SL fixo de
250 pts (2,50 USD) para isolar o efeito do stop sem confundir com a fórmula
ATR do V26.

Relatórios em `backtest/reports/wce_variants/`.

### 14.5 Estado do mercado nesta janela

V26 e WCE **puros** perdem dinheiro com custos medidos (PF 0,795 e 0,887). Não
há edge no conjunto atual. Qualquer promoção de variante exigiria PF > 1 com
custos, o que nenhuma das três atingiu.


### 14.6 Causa raiz: `*_points` somado ao preço como se fosse USD

**O que estava errado.** O campo se chamava `tp_points`/`sl_points` e a
docstring dizia "1 pt = 0,01 USD no XAUUSD-VIP", mas o código fazia:

```python
tp = price + tp_points      # 50.0 somado a 4617.5 -> alvo a +50,00 USD
```

Sem a conversão. Um "TP de 50 pontos" virava **alvo a +50,00 USD** — 100x
distante do pretendido (0,50 USD) e ~11x a amplitude mediana de uma barra M5
(4,34 USD). Nenhum TP podia disparar. O mesmo valia para o SL: "250 pontos"
virava stop a 250,00 USD.

**Por que enganou durante duas rodadas.** O sintoma (zero TPs) é
*idêntico* ao de um alvo geometricamente distante, e as duas explicações
são ambas plausíveis olhando só o relatório. Cheguei a "TP=500 é
impossível" por uma vía errada: somei 500 à entrada de um trade e comparei
com o máximo do dataset. Um trade não prova impossibilidade — a mediana de
close + 5,00 USD cabe folgadamente. O que quebrou a ambiguidade foi o
`test_tp_de_500...` falhando com o número real ao lado, e depois o smoke
test mostrar **1 TP em 190 trades com alvo de 0,50 USD** — geométrica
impossível não é 1/190.

**Por que a unidade ficou ambígua desde o começo.** O V26 usa o mesmo nome
para a mesma ideia, e também não converte: `calculate_initial_sl` faz
`current_price - sl_points` direto (`strategy/pdf_strategies.py:270`).
Medido: `sl_points` mediano 10,09 com distância real entrada→stop de 3,62
USD. Ou seja, **o `sl_points` do V26 é um delta em USD apesar do nome** —
a unidade "pontos" é uma fantasia que os dois lados herdaram. Não foi
corrigido no V26 (mudaria o comportamento de um sistema já medido); foi
corrigido só nas variantes, que são novas e não têm número publicado.

**Correção.** `POINTS_TO_PRICE = 0.01` em `backtest/engine.py`, aplicado
em `_entry_wce` ao converter `*_points` da variante em preço. Documentado
no `WCEVariant` para que o próximo que mexer aqui não reintroduza.

**Verificado após a correção** (slice real de 5.000 barras, sem custos):

| Variante | Trades | Saídas |
|---|---:|---|
| `wce_quadrant` (A) | 107 | `{'QUADRANT': 107}` |
| `wce_quadrant_tp` (B) | 107 | `{'TP': 98, 'QUADRANT': 9}` |
| `wce_quadrant_tp_sl` (C) | 107 | `{'TP': 55, 'SL': 52}` |

Primeiro trade: entrada 4617,50, TP 4618,00 (+0,50 exato), SL 4615,00
(−2,50 exato).

**Testes.** `tests/test_wce_variants.py`, 9 testes, todos verdes em 7m33s.
Três lições que eles carregam:

1. **Fixture sintetica nao serve para estrategia de quadrante.** Dente-de-serra
   e aleatorio nao produzem travessia de quadrante do Hilbert: as variantes
   devolviam **0 trades** e os testes "passavam" por vacuuo, sem exercitar
   nada. Trocado por slice real de 5.000 barras (~107 entradas, ~15 s por
   engine).
2. **O teste do TP exige que ele DISPARE, nao so que exista.** `assert tp is
   not None` passava com o alvo a +50,00 USD. O que pega a regressão e
   `assert any(t.exit_reason == "TP")` mais a checagem de distância de
   0,50 USD em cada trade.
3. **O teste da unidade foi reescrito com a premissa certa.** O original
   afirmava que 500 pts era inalcançável — e estava errado, do jeito que o
   §14.3 original estava. Agora trava a relação
   `50.0 * POINTS_TO_PRICE == 0.50` e que 0,50 < amplitude mediana < 50,00.

### 14.7 Resultado medido das três variantes (com custos, 35.359 barras)

Todos os relatórios em `backtest/reports/wce_variants/`. As três variantes
têm **exatamente os mesmos 894 trades** — diferem só em como saem. Isso
torna a comparação pareada: a diferença de P&L é atribuível ao parâmetro
de saída, e a nada mais.

| Variante | Trades | WR | PF | P&L | MaxDD | Sharpe | Saídas |
|---|---:|---:|---:|---:|---:|---:|---|
| V26 (baseline) | 1746 | 37,7% | 0,795 | −891,61 | 9,66% | −4,58 | SL/TRAIL |
| `wce` (guardrail) | 894 | 42,6% | 0,880 | −268,10 | 2,96% | −1,95 | QUADRANT+SL |
| **A** artigo puro | 894 | 44,4% | **0,887** | **−257,81** | 3,59% | −1,70 | `{QUADRANT: 894}` |
| **B** +TP 50 | 894 | 89,5% | 0,243 | −374,05 | 3,75% | −8,58 | `{TP: 800, QUADRANT: 94}` |
| **C** +TP 50 +SL 250 | 894 | 60,2% | 0,081 | −916,00 | 9,16% | −30,09 | `{SL: 344, TP: 538, QUADRANT: 12}` |

**Nenhuma atinge PF > 1,0. A melhor é a que não tem nada além do artigo.**

#### Por que o TP de 50 pontos piora (a armadilha do WR alto)

B tem **89,5% de acerto** e PF 0,243. Win rate altíssimo com PF péssimo
significa vencedores minúsculos contra perdedores grandes. A conta:

- custo medido: 0,35 USD/trade (spread 0,34 + slippage 1 pt)
- alvo: 50 pts = 0,50 USD brutos → **0,15 USD líquido por vitória**
- 89,5% de acerto sobre 0,15 USD não cobre nem o custo do que perdeu

Ou seja, **o alvo de 50 pontos é MENOR que o custo de round-trip (0,35 USD)**.
Enquanto TP ≤ 35 pts, acrescentar take profit a esta estratégia é
matematicamente incapaz de produzir lucro, qualquer que seja o win rate.
Não é defeito do WCE nem da implementação: é propriedade do símbolo e do
custo medido.

O efeito mecânico: A não tem alvo, e o quadrant-exit deixava o trade correr
(é por isso que A tem WR de só 44,4% e mesmo assim o melhor PF — assimetria
favorável). Fixar alvo em 0,50 USD **trunca a cauda direita** que fazia A
menos ruim, e converte todo aquele upside em média-zero. O TP funcionou
mecanicamente (800 de 894 encerraram no alvo) — o problema é o nível, não
o mecanismo.

#### Por que o SL de 250 mata C

C é assimétrico na direção errada: risco 2,50 USD contra ganho 0,50 USD, um
ratio de 5:1. Precisaria acertar **83,3%** das vezes para empatar; acerta
**60,2%**. Resultado: PF 0,081 e o pior Sharpe da tabela (−30,09). O SL de
2,50 USD também é comparável ao alcance típico de um ciclo Hilbert, então
mata a posição antes que o quadrante decida — resta 12 saídas por quadrante
contra 894 em A.

#### Leitura

O gradiente é monotônico e na direção esperada: **cada parâmetro acrescentado
piora**. A (PF 0,887) → B (0,243) → C (0,081). Nenhum deles é edge; são três
formas de tornear o mesmo mercado sem braço. A conclusão da §14.5 se
confirma com mais força: nesta janela, com estes custos, não há edge no
conjunto — e o take profit é a mudança que mais destrói valor, porque opera
abaixo do custo de transação.

## 15. VEREDICTO FINAL — nenhum dos dois PDFs tem edge em XAUUSD M5 (2026-09-27)

Encerramento da investigação. Esta seção é o número para levar adiante; as
§9–14 contam como cada número foi medido e quantas vezes foi errado antes de
virar certo.

### 15.1 O veredicto

**Os PDFs (V26 e WCE 2014) NÃO têm edge comprovado em XAUUSD M5** — nenhum,
nesta janela, com estes custos medidos.

Não é "edge fraco". É ausência de edge: as duas estratégias pagam spread e
slippage para entrar e sair mais vezes do que o movimento do preço paga de
volto.

| Modelo | Trades | WR | PF | P&L | MaxDD | Sharpe |
|---|---:|---:|---:|---:|---:|---:|
| V26 (baseline, guardrail ATR) | 1746 | 37,7% | 0,795 | −891,61 | 9,66% | −4,58 |
| WCE com guardrail (`wce`) | 894 | 42,6% | 0,880 | −268,10 | 2,96% | −1,95 |
| **A — artigo puro** | 894 | 44,4% | **0,887** | −257,81 | 3,59% | −1,70 |
| B — A + TP 50 pts | 894 | 89,5% | 0,243 | −374,05 | 3,75% | −8,58 |
| C — B + SL 250 pts | 894 | 60,2% | 0,081 | −916,00 | 9,16% | −30,09 |

Leitura: **nenhum modelo chega a PF 1,0.** O melhor é A (0,887), e A é
exatamente o artigo sem nada acrescentado — ou seja, o WCE 2014 tal como
escrito, neste símbolo, nesta janela, com estes custos.

O paper original (Kablan & Falzon 2014, pp. 927–933) reporta **PF 1,0** —
isto é, o próprio artigo é break-even. Ver §14.1 e o rodapé de fidelidade
§9.6: o ISOM é usado no artigo como *entrada* do transform, e aqui
`i1`/`q1` são calculados sobre preço bruto. Ou seja, estes números são o
artigo **menos** uma etapa do pipeline. A conclusão não depende disso: um
artigo break-even, mesmo replicado perfeitamente, não gera lucro.

### 15.2 Por que nenhum TP mencionado aqui funciona

O take profit de 50 pts (0,50 USD) é **menor que o custo de round-trip
medido (0,35 USD)**. Enquanto o alvo ficar abaixo de ~35 pts, acrescentar TP a
esta estratégia é matematicamente incapaz de produzir lucro, qualquer que seja
o win rate — não é defeito de implementação nem do WCE, é propriedade do
símbolo com o custo medido.

É por isso que B tem 89,5% de acerto e PF 0,243: cada vitória rende 0,15 USD
líquido, e o acerto alto não paga as posições perdedoras. O take profit
truncou a cauda direita que fazia A "só" ruim.

E C (TP 50 / SL 250) é risco 5:1 contra ganho 1:1 em termos de ponto — exige
83,3% de acerto para empatar, tem 60,2%. PF 0,081.

Qualquer TP futuro tem de ser testado **acima de 35 pts** ou não vale a medição.

### 15.3 O que sobrevive: a infraestrutura

Independentemente do resultado, o que foi construído é reutilizável — e foi
construído para ser. **126 testes** (125 verdes; a única falha é o
`test_mt5_headway_connection`, que conecta de fato ao MT5 e falha só porque a
conta é da VT Markets e não da Headway — ver §15.5), dashboard Streamlit
somente-leitura, conector MT5 com 3 tentativas, backtester com modelo de
custos, feature engineering (Hilbert/ATR/ISOM), suíte de variantes e
relatórios com rastreabilidade de qual regra encerrou cada trade.

O dashboard e o backtester foram escritos para *conseguir* mostrar que uma
estratégia não funciona, com a distinção de fonte da regra em cada número. Isso
serviu, e vai servir para a próxima hipótese.

### 15.4 PRÓXIMA SESSÃO — a decisão é do responsável

Três caminhos, nenhum conhecido como certo:

- **(A) Pivotar para outra estratégia.** Abandonar Hilbert/ISOM como eixo e
  procurar uma classe de hipótese diferente. Custa: recomeçar a pesquisa.
- **(B) Calibrar os parâmetros existentes** dentro das famílias que os PDFs já
  descrevem (filtro ISOM com `dx(%)` real, thresholds, variantes de
  dimensionamento). Custa: tempo, e a §14.7 mostra que acrescentar parâmetro
  piorou monotonicamente — calibrar precisa ser *remover* degrees of freedom,
  não adicionar.
- **(C) Abandonar XAUUSD M5** e levar a mesma infraestrutura para outro
  símbolo/timeframe. Custa: nova coleta de dados, mas o pipeline já faz isso
  (`backtest/downloader.py`).

Recomendação honesta: **(A)**. O paper de origem é break-even e a nossa
replicação é pior que break-even; calibrar em torno de um número que já é
1,0 é otimizar sobre ruído. Mas a decisão é do responsável e o dado de apoio
está acima.

### 15.5 Estado da suíte e pendênciasknown

- `python -m pytest tests/ -q --tb=short` → **125 passed, 1 failed (499s)**.
- A falha é `tests/test_mt5_connection.py::test_mt5_headway_connection`:
  `assert "Headway" in acc_info["server"]` contra `VTMarkets-Demo`. A conexão
  MT5 funciona (conta 1045989 DEMO, saldo 19.016,45 USD); falha a asserção
  sobre o nome do broker. **Não corrigida** — requer decisão sobre renomear a
  asserção ou reconectar a uma conta Headway. Fora do escopo do encerramento.
- `docs/wce2014_source_of_truth.md` §3.2 e §5 ainda afirmam o "+$953,52",
  refutado na §14.1. **Não corrigido** — fora do escopo deste encerramento.
- Code review do diff: 7 achados registrados, nenhum corrigido. Os dois de
  dados, se tratados: (1) variante `--no-with-costs` sobrescreve o relatório
  `--with-costs` (mesmo diretório, sem sufixo); (2) dois testes em
  `tests/test_wce_variants.py` passam por vácuo quando a lista de trades vem
  vazia, justamente o defeito que aquele arquivo existe para eliminar.

### 15.6 Invariantes de segurança — inalteradas

`dry_run=True`, `live_trading=False`, `allowed_symbols=('XAUUSD','XAGUSD')`,
`active_model='v26'`. Nenhum arquivo desta investigação tocou `dry_run`,
`core/executor.py` nem `allowed_symbols`. O backtester é simulação pura:
`Executor` nunca importado, `order_send` nunca chamado.
