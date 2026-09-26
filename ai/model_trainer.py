"""Treino dos modelos com base nas features dos PDFs - Etapa 7.

Cabeça 3 (ISOM-ML) e Cabeça 4 (Gating) ficam em shadow na v1:
calculam e logam, não filtram entrada (decisão Etapa 1 #7).

Características:
- ML clássico apenas (RandomForest)
- Split temporal OBRIGATÓRIO (nunca aleatório - evita lookahead bias)
- Salva modelo em ai/models/pattern_v1.pkl
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
from loguru import logger

try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

try:
    import joblib
    JOBLIB_AVAILABLE = True
except ImportError:
    JOBLIB_AVAILABLE = False

from config.settings import Settings, get_settings

MODELS_DIR = Path("ai/models")


class ModelTrainer:
    """Treinador de modelos ML com split temporal (sem lookahead bias)."""

    def __init__(
        self,
        settings: Settings | None = None,
        models_dir: Path = MODELS_DIR,
    ) -> None:
        self.settings = settings or get_settings()
        self.models_dir = Path(models_dir)
        self.models_dir.mkdir(parents=True, exist_ok=True)

        self.model: Any = None
        self.scaler: Any = None
        self.metrics: dict[str, Any] = {}

    def train(
        self,
        features: pd.DataFrame,
        labels: pd.Series,
        test_size: float = 0.2,
    ) -> dict[str, Any]:
        """Treina modelo com split temporal (sem lookahead bias).

        Args:
            features: DataFrame com features (index temporal)
            labels: Series com labels (index temporal)
            test_size: Proporção para validação (final da série)

        Returns:
            Dict com métricas e status do treinamento
        """
        if not SKLEARN_AVAILABLE:
            logger.warning("scikit-learn não disponível - treinamento abortado")
            return {"trained": False, "reason": "scikit-learn not available"}

        if features.empty or labels.empty:
            logger.warning("Features ou labels vazios - treinamento abortado")
            return {"trained": False, "reason": "empty data"}

        # Split TEMPORAL (nunca aleatório)
        n_samples = len(features)
        n_train = int(n_samples * (1 - test_size))

        X_train = features.iloc[:n_train]
        X_val = features.iloc[n_train:]
        y_train = labels.iloc[:n_train]
        y_val = labels.iloc[n_train:]

        logger.info(
            "Split temporal: {} treino | {} validação ({}% test)",
            len(X_train),
            len(X_val),
            test_size * 100,
        )

        # Normalização
        self.scaler = StandardScaler()
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_val_scaled = self.scaler.transform(X_val)

        # Treina RandomForest
        self.model = RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            random_state=42,
            n_jobs=-1,
        )

        self.model.fit(X_train_scaled, y_train)

        # Predição e métricas
        y_pred = self.model.predict(X_val_scaled)

        self.metrics = {
            "accuracy": round(accuracy_score(y_val, y_pred), 4),
            "precision": round(precision_score(y_val, y_pred, average="weighted", zero_division=0), 4),
            "recall": round(recall_score(y_val, y_pred, average="weighted", zero_division=0), 4),
            "f1": round(f1_score(y_val, y_pred, average="weighted", zero_division=0), 4),
            "train_size": len(X_train),
            "val_size": len(X_val),
            "n_features": features.shape[1],
        }

        logger.info(
            "Modelo treinado: Accuracy={:.2f}% | F1={:.4f}",
            self.metrics["accuracy"] * 100,
            self.metrics["f1"],
        )

        # Salva modelo
        if JOBLIB_AVAILABLE:
            model_path = self.models_dir / "pattern_v1.pkl"
            try:
                joblib.dump(
                    {"model": self.model, "scaler": self.scaler, "metrics": self.metrics},
                    model_path,
                )
                logger.info("Modelo salvo em {}", model_path)
            except Exception as e:
                logger.warning("Falha ao salvar modelo: {}", e)

        return {
            "trained": True,
            "shadow": True,  # Sempre True na v1
            **self.metrics,
        }

    def predict_shadow(self, features: pd.DataFrame) -> dict[str, Any]:
        """ISOM-ML + Gating: resultado só para log, nunca para filtrar ordem.

        Args:
            features: DataFrame com features

        Returns:
            Dict com predição (sempre shadow=True, filters_entry=False)
        """
        if self.model is None or self.scaler is None:
            logger.debug("Modelo não treinado - retornando predição nula")
            return {
                "regime": None,
                "confidence": None,
                "signal_strength": None,
                "shadow": True,
                "filters_entry": False,
            }

        if features.empty:
            return {
                "regime": None,
                "confidence": None,
                "signal_strength": None,
                "shadow": True,
                "filters_entry": False,
            }

        try:
            X = self.scaler.transform(features)
            prediction = self.model.predict(X)
            probabilities = self.model.predict_proba(X)

            confidence = float(np.max(probabilities[-1]))
            signal_strength = abs(confidence - 0.5) * 2  # 0 a 1

            return {
                "regime": int(prediction[-1]),
                "confidence": round(confidence, 4),
                "signal_strength": round(signal_strength, 4),
                "shadow": True,
                "filters_entry": False,  # NUNCA filtra entrada na v1
            }
        except Exception as e:
            logger.warning("Falha na predição: {}", e)
            return {
                "regime": None,
                "confidence": None,
                "signal_strength": None,
                "shadow": True,
                "filters_entry": False,
            }
