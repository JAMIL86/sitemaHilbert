# Métricas de Performance dos Modelos - Etapa 7

## Model Trainer - RandomForest

**Modelo**: `ai/models/pattern_v1.pkl`  
**Tipo**: RandomForestClassifier (100 trees, max_depth=10)  
**Split**: Temporal (80% treino / 20% validação)

### Parâmetros
- n_estimators: 100
- max_depth: 10
- random_state: 42
- Features: roofing_energy, quadrant, cycle_mode, instant_trend, ebsw_sine, amplitude_norm, atr14

### Métricas de Validação

| Métrica | Valor |
|---------|-------|
| Accuracy | A ser calibrado em backtest |
| Precision | A ser calibrado em backtest |
| Recall | A ser calibrado em backtest |
| F1-Score | A ser calibrado em backtest |

**Observação**: O modelo está em **modo shadow** na v1. Cabeças 3 e 4 (ISOM-ML + Gating) apenas logam telemetria, **nunca filtram entrada**.

## Pattern Detector

**Status**: Implementado com heurísticas + ML opcional  
**Modo**: Heurístico (fallback quando modelo não disponível)

### Padrões Detectados
1. **Acumulação**: Baixa energia Roofing + IT flat
2. **Ruptura**: Preço rompe IT ± (threshold × ATR)
3. **Quadrantes**: Q4→Q1 (BUY) / Q2→Q3 (SELL)

## Shadow Logger

**Status**: Implementado e validado  
**Formato**: JSON Lines (1 registro/linha)  
**Rotação**: Diária automática (shadow_YYYYMMDD.jsonl)  
**Localização**: `logs/`

### Campos Gravados
- timestamp (ISO 8601)
- model (WCE2014 / Head3_ISOM / Head4_Gating)
- signal (BUY / SELL / HOLD)
- confidence (0.0 a 1.0)
- features_snapshot (dict)
- would_have_entered (bool)

**Trava de Segurança**: ShadowLogger **NÃO** tem referência ao executor. Modo shadow é apenas telemetria.

## Próximos Passos (Backtest)

1. Coletar dados históricos (MT5 ou CSV)
2. Calibrar parâmetros em `config/settings.py`:
   - `t_min` / `t_max` (ciclo homódino)
   - `isom_dx_percent` (WCE 2014)
   - `accumulation_energy_n`
   - `breakout_threshold_atr`
3. Treinar modelo final com dados reais
4. Atualizar métricas neste documento
5. Validar WCE 2014 em shadow (2-3 semanas)
6. Decidir ativação de Cabeças 3/4
