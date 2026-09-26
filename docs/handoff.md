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

## 8. Próxima Etapa

A definir após confirmação explícita. Nenhuma etapa avança sem aval do responsável.

