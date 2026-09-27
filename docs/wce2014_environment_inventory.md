# WCE 2014 — Environment Inventory
> **Data:** 2026-09-27  
> **Projeto:** Hilberti WCE 2014 Research & Implementation  
> **Status:** FASE 0 — Descoberta

---

## 1. Skills Disponíveis

| Skill | Path | Relevância | Uso Previsto |
|---|---|---|---|
| `backtest-expert` | `~/.claude/skills/backtest-expert/` | ✅ ALTA | Walk-forward, out-of-sample, Monte Carlo, validação temporal |
| `edge-strategy-reviewer` | `~/.claude/skills/edge-strategy-reviewer/` | ✅ ALTA | Auditoria final, veredicto PASS/REVISE/REJECT, análise de overfitting |
| `quant-feature-engineer` | `~/.claude/skills/quant-feature-engineer/` | ✅ MÉDIA | Feature engineering DSP, validação matemática |
| `cost-mode` | `~/.claude/skills/cost-mode/` | ✅ BAIXA | Otimização de tokens (já ativo) |
| `signal-postmortem` | `~/.claude/skills/signal-postmortem/` | ⚠️ BAIXA | Post-mortem de sinais (uso posterior) |
| `strategy-pivot-designer` | `~/.claude/skills/strategy-pivot-designer/` | ⚠️ BAIXA | Pivots estratégicos (não aplicável à reprodução fiel) |

**Ausentes:** `tdd` skill não encontrada em `~/.agents/skills/` nem `~/.claude/skills/`.

---

## 2. MCPs Disponíveis

| MCP | Status | Relevância | Uso Previsto |
|---|---|---|---|
| `kairogen` | ✅ Disponível | ❌ NULA | Geração de imagem/vídeo (não aplicável) |
| `pinescript` | ✅ Disponível | ❌ NULA | Pine Script (não aplicável) |
| `local-rag` | ✅ Disponível | ⚠️ MÉDIA | Indexação de PDFs e pesquisa semântica |
| `playwright` | ✅ Disponível | ❌ NULA | Browser automation (não aplicável) |
| `sequential-thinking` | ✅ Disponível | ⚠️ BAIXA | Reasoning step-by-step (uso eventual) |

**Limitação:** `filesystem` MCP não identificado como servidor separado — operações de arquivo via ferramentas nativas.

---

## 3. Ferramentas de Backtest

| Módulo | Path | Status | Capacidade |
|---|---|---|---|
| `downloader.py` | `backtest/downloader.py` | ✅ Existente | Download MT5, validação de gaps, CSV |
| `engine.py` | `backtest/engine.py` | ✅ Existente | Execução barra a barra, delegação ao V26/WCE |
| `metrics.py` | `backtest/metrics.py` | ✅ Existente | Win rate, PF, Sharpe, Sortino, MaxDD |
| `report.py` | `backtest/report.py` | ✅ Existente | Markdown + equity curve + custos |

**Comandos disponíveis:**
```bash
python -m backtest.downloader --symbol XAUUSD-VIP --timeframe M5
python -m backtest.engine --model wce --with-costs
```

---

## 4. Estratégias Existentes

| Estratégia | Path | Status | Descrição |
|---|---|---|---|
| `V26Strategy` | `strategy/pdf_strategies.py` | ✅ Implementada | Hilbert Cycle + Chimera SSM (ativo) |
| `WCE2014Strategy` | `strategy/pdf_strategies.py` | ✅ Implementada | Hilbert Transform + Q1/Q3 (shadow mode) |
| `StrategyRouter` | `strategy/pdf_strategies.py` | ✅ Implementada | Orquestração de modelos via `active_model` |

**Achado crítico:** `WCE2014Strategy` já existe, mas segundo `docs/handoff.md` §13, foi **rebaixada** (PF 0,879, veredito REVISE). ISOM ausente como pré-condicionamento.

---

## 5. PDF Original

| Item | Valor |
|---|---|
| **Path** | `pdfs/WCE2014_pp927-933.pdf` |
| **Tamanho** | 1,2 MB |
| **Status** | ✅ Legível, já extraído em `_extract/WCE2014_pp927-933.txt` |
| **Páginas** | 7 (pp. 927–933) |
| **Tipo** | Paper acadêmico, Kablan & Falzon, WCE 2014 |

**Extração anterior:** `_extract/WCE2014_pp927-933.txt` existe desde Etapa 1 (não reprocessar).

---

## 6. Dados Históricos

| Item | Valor |
|---|---|
| **Fonte** | MT5 Headway, VTMarkets-Demo, conta 1045989 |
| **Símbolo** | XAUUSD-VIP M5 |
| **Período disponível** | 2026-03-30 a 2026-09-25 (6 meses, 35 359 barras) |
| **Arquivo** | `backtest/data/XAUUSD-VIP_M5_2026-03-30_2026-09-25.csv` (2,4 MB) |
| **Qualidade** | ✅ Validado (1 gap real de 3 barras, sessão 01:00–23:55 UTC) |

---

## 7. Testes

| Módulo | Tests | Status |
|---|---|---|
| `tests/test_features.py` | 10 testes DSP | ✅ 100% verdes |
| `tests/test_strategy.py` | 12 testes V26/WCE/Router | ✅ 100% verdes |
| `tests/test_backtest.py` | 23 testes | ✅ 22/23 verdes (1 falha ambiental) |
| `tests/test_dashboard.py` | 25 testes | ✅ 100% verdes |

**Infraestrutura de testes:** pytest funcional, TDD possível.

---

## 8. Limitações Identificadas

1. **Skills ausentes:** `tdd` não encontrada (usar pytest direto).
2. **RAG:** `local-rag` MCP disponível mas não indexado ainda — considerar para scan de papers externos.
3. **ISOM:** Implementação WCE existente **não tem ISOM como pré-condicionamento** (lacuna #4 do §13.2).
4. **Walk-forward:** Não executado ainda — depende de `backtest-expert`.
5. **Monte Carlo:** Não executado ainda.

---

## 9. Pipeline de Execução

Recursos suficientes para executar:

1. ✅ Scan completo do PDF (já lido, extração anterior em `_extract/`)
2. ✅ Verificação de fórmulas (comparar com implementação existente)
3. ✅ Reconstrução do algoritmo (já parcialmente feito, validar contra PDF)
4. ✅ Pesquisa web (WebSearch/WebFetch disponíveis)
5. ✅ Implementação original vs advanced (arquitetura a definir)
6. ✅ Testes matemáticos (pytest + fixtures existentes)
7. ✅ Backtest (engine funcional, dados reais disponíveis)
8. ✅ Walk-forward (via `backtest-expert`)
9. ✅ Auditoria (via `edge-strategy-reviewer`)

---

## 10. Próxima Fase

**FASE 1 — SCAN COMPLETO DO PDF**

Ler `pdfs/WCE2014_pp927-933.pdf` página a página:
- Extrair todas as fórmulas
- Identificar pseudocódigo/algoritmo
- Tabelas de resultados
- Figuras (I-Q plane, transições)
- Verificar se `_extract/WCE2014_pp927-933.txt` contém tudo

**Não avançar para implementação sem validar o PDF como fonte primária.**
