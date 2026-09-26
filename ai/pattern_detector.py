"""Detecção de padrões (ciclo, acumulação, ruptura, EBSW) - Etapa 7.

Usa ML clássico (RandomForest) para detectar padrões dos PDFs:
- Acumulação (baixa energia Roofing N barras)
- Ruptura Latched (preço rompe IT + threshold)
- Transições Q4→Q1 / Q2→Q3

Features: apenas as já validadas em ai/feature_engineer.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
from loguru import logger

try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

from config.settings import Settings, get_settings

MODELS_DIR = Path("ai/models")


class PatternDetector:
    """Detector de padrões com ML clássico (RandomForest)."""

    def __init__(
        self,
        settings: Settings | None = None,
        model_path: Optional[Path] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.model_path = model_path or MODELS_DIR / "pattern_v1.pkl"
        self.model: Any = None
        self.scaler: Any = None
        self._load_model()

    def _load_model(self) -> None:
        """Carrega modelo treinado se existir."""
        if not SKLEARN_AVAILABLE:
            logger.warning("scikit-learn não disponível - PatternDetector em modo heurístico")
            return

        if self.model_path.exists():
            try:
                import joblib
                data = joblib.load(self.model_path)
                self.model = data.get("model")
                self.scaler = data.get("scaler")
                logger.info("Modelo carregado de {}", self.model_path)
            except Exception as e:
                logger.warning("Falha ao carregar modelo: {}", e)

    def _extract_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extrai features relevantes do DataFrame de features do FeatureEngineer.

        Usa apenas features já validadas em ai/feature_engineer.py:
        - roofing_energy: energia do Roofing Filter
        - quadrant: quadrante atual (1-4)
        - cycle_mode: regime de ciclo (0 ou 1)
        - instant_trend: linha de tendência instantânea
        - ebsw_sine: Even Better Sine Wave
        - amplitude_norm: amplitude normalizada (AGC)
        - atr14: ATR de 14 períodos
        """
        feature_cols = [
            "roofing_energy",
            "quadrant",
            "cycle_mode",
            "instant_trend",
            "ebsw_sine",
            "amplitude_norm",
            "atr14",
        ]

        # Filtra apenas colunas que existem
        available_cols = [col for col in feature_cols if col in df.columns]

        if not available_cols:
            logger.warning("Nenhuma feature disponível para detecção")
            return pd.DataFrame()

        return df[available_cols].fillna(0)

    def _detect_accumulation_heuristic(self, df: pd.DataFrame) -> bool:
        """Detecta acumulação via heurística: baixa energia Roofing + IT flat."""
        if "roofing_energy" not in df.columns or "instant_trend" not in df.columns:
            return False

        # Últimas N barras
        n = min(self.settings.accumulation_energy_n or 20, len(df))
        recent = df.tail(n)

        # Energia média baixa
        energy_mean = recent["roofing_energy"].mean()
        energy_threshold = energy_mean * self.settings.accumulation_energy_factor

        # IT flat (variação pequena)
        it_variation = abs(recent["instant_trend"].iloc[-1] - recent["instant_trend"].iloc[0])
        price_mean = recent["instant_trend"].mean()
        flat_threshold = self.settings.eit_flat_factor * price_mean if price_mean > 0 else 0.01

        return energy_mean < energy_threshold and it_variation < flat_threshold

    def _detect_breakout_heuristic(self, df: pd.DataFrame) -> dict[str, Any]:
        """Detecta ruptura via heurística: preço rompe IT + threshold ATR."""
        result = {"detected": False, "direction": None, "magnitude": 0.0}

        if "instant_trend" not in df.columns or "close" not in df.columns:
            return result

        if "atr14" not in df.columns:
            return result

        close = df["close"].iloc[-1]
        it = df["instant_trend"].iloc[-1]
        atr = df["atr14"].iloc[-1]

        threshold = self.settings.breakout_threshold_atr or 0.5
        breakout_distance = atr * threshold

        # Ruptura de alta
        if close > it + breakout_distance:
            result = {
                "detected": True,
                "direction": "UP",
                "magnitude": close - it,
            }
        # Ruptura de baixa
        elif close < it - breakout_distance:
            result = {
                "detected": True,
                "direction": "DOWN",
                "magnitude": it - close,
            }

        return result

    def detect(self, features: pd.DataFrame) -> dict[str, Any]:
        """Detecta padrões em features calculadas pelo FeatureEngineer.

        Args:
            features: DataFrame com features do FeatureEngineer

        Returns:
            Dict com padrões detectados:
            - cycle_mode: regime de ciclo (0 ou 1)
            - quadrant: quadrante atual (1-4)
            - is_accumulating: se está em fase de acumulação
            - breakout: dict com info de ruptura
            - buy_signal: sinal de compra
            - sell_signal: sinal de venda
        """
        if features.empty:
            logger.warning("Features vazias - retornando padrões nulos")
            return {
                "cycle_mode": None,
                "quadrant": None,
                "is_accumulating": None,
                "breakout": None,
                "buy_signal": False,
                "sell_signal": False,
            }

        # Extrai última barra
        last = features.iloc[-1]

        # Valores básicos
        cycle_mode = int(last.get("cycle_mode", 0)) if "cycle_mode" in features.columns else None
        quadrant = int(last.get("quadrant", 0)) if "quadrant" in features.columns else None

        # Detecção heurística de acumulação
        is_accumulating = self._detect_accumulation_heuristic(features)

        # Detecção heurística de ruptura
        breakout = self._detect_breakout_heuristic(features)

        # Detecção ML (se modelo disponível)
        if self.model is not None and SKLEARN_AVAILABLE:
            X = self._extract_features(features)
            if not X.empty:
                try:
                    X_last = X.iloc[[-1]]
                    if self.scaler is not None:
                        X_last = self.scaler.transform(X_last)
                    prediction = self.model.predict(X_last)[0]
                    # TODO: usar prediction para ajustar confiança
                except Exception as e:
                    logger.warning("Falha na predição ML: {}", e)

        # Sinais de compra/venda (Q4→Q1 ou Q2→Q3 com cycle_mode=1)
        buy_signal = False
        sell_signal = False

        if cycle_mode == 1 and len(features) >= 2:
            prev_quadrant = features["quadrant"].iloc[-2] if "quadrant" in features.columns else None

            # Q4→Q1: BUY
            if prev_quadrant == 4 and quadrant == 1:
                buy_signal = True
            # Q2→Q3: SELL
            elif prev_quadrant == 2 and quadrant == 3:
                sell_signal = True

        return {
            "cycle_mode": cycle_mode,
            "quadrant": quadrant,
            "is_accumulating": is_accumulating,
            "breakout": breakout,
            "buy_signal": buy_signal,
            "sell_signal": sell_signal,
        }
