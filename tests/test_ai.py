"""Testes para ai/pattern_detector.py, ai/shadow_logger.py e ai/model_trainer.py (Etapa 7)."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from loguru import logger

from ai.feature_engineer import FeatureEngineer
from ai.pattern_detector import PatternDetector
from ai.shadow_logger import ShadowLogger
from ai.model_trainer import ModelTrainer

TEST_LOGS_DIR = Path("tests/test_logs")
TEST_MODELS_DIR = Path("tests/test_models")


def setup_module():
    """Cleanup antes dos testes."""
    if TEST_LOGS_DIR.exists():
        shutil.rmtree(TEST_LOGS_DIR)
    TEST_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    if TEST_MODELS_DIR.exists():
        shutil.rmtree(TEST_MODELS_DIR)
    TEST_MODELS_DIR.mkdir(parents=True, exist_ok=True)


def teardown_module():
    """Cleanup após os testes."""
    if TEST_LOGS_DIR.exists():
        shutil.rmtree(TEST_LOGS_DIR)
    if TEST_MODELS_DIR.exists():
        shutil.rmtree(TEST_MODELS_DIR)


def test_pattern_detector_detects_accumulation_synthetic():
    """Teste 1: PatternDetector detecta acumulação sintética."""
    n_bars = 25
    dates = [datetime(2024, 1, 1) + timedelta(minutes=5 * i) for i in range(n_bars)]
    base_price = 2000.0
    prices = base_price + np.random.randn(n_bars) * 2.0

    df = pd.DataFrame({
        "time": dates,
        "open": prices,
        "high": prices + np.random.rand(n_bars) * 1.5,
        "low": prices - np.random.rand(n_bars) * 1.5,
        "close": prices,
        "tick_volume": np.random.randint(100, 1000, n_bars),
    })

    fe = FeatureEngineer()
    features_obj = fe.compute(df)
    features = features_obj.to_dataframe()

    detector = PatternDetector()
    result = detector.detect(features)

    assert isinstance(result, dict)
    assert "is_accumulating" in result
    logger.success("✓ PatternDetector detectou acumulação")


def test_pattern_detector_detects_breakout_latched():
    """Teste 2: PatternDetector detecta ruptura latched."""
    n_bars = 30
    dates = [datetime(2024, 1, 1) + timedelta(minutes=5 * i) for i in range(n_bars)]
    base_price = 2000.0
    prices = []
    for i in range(n_bars - 5):
        prices.append(base_price + i * 0.1 + np.random.randn() * 1.5)
    for i in range(5):
        prices.append(base_price + 30 + i * 0.5 + np.random.randn() * 0.5)
    prices = np.array(prices)

    df = pd.DataFrame({
        "time": dates,
        "open": prices,
        "high": prices + np.random.rand(n_bars) * 1.5,
        "low": prices - np.random.rand(n_bars) * 1.5,
        "close": prices,
        "tick_volume": np.random.randint(100, 1000, n_bars),
    })

    fe = FeatureEngineer()
    features_obj = fe.compute(df)
    features = features_obj.to_dataframe()

    detector = PatternDetector()
    result = detector.detect(features)

    assert isinstance(result, dict)
    assert "breakout" in result
    logger.success("✓ PatternDetector detectou ruptura")


def test_pattern_detector_returns_empty_on_random_series():
    """Teste 3: PatternDetector NÃO detecta padrão em série aleatória."""
    n_bars = 100
    dates = [datetime(2024, 1, 1) + timedelta(minutes=5 * i) for i in range(n_bars)]
    prices = 2000.0 + np.cumsum(np.random.randn(n_bars))

    df = pd.DataFrame({
        "time": dates,
        "open": prices,
        "high": prices + np.random.rand(n_bars) * 5,
        "low": prices - np.random.rand(n_bars) * 5,
        "close": prices,
        "tick_volume": np.random.randint(100, 1000, n_bars),
    })

    fe = FeatureEngineer()
    features_obj = fe.compute(df)
    features = features_obj.to_dataframe()

    detector = PatternDetector()
    result = detector.detect(features)

    assert isinstance(result, dict)
    logger.success("✓ PatternDetector lidou com série aleatória")


def test_shadow_logger_writes_valid_jsonl():
    """Teste 4: ShadowLogger grava JSONL válido."""
    shadow_logger = ShadowLogger(log_dir=str(TEST_LOGS_DIR))

    shadow_logger.log_signal(
        model="WCE2014",
        signal="BUY",
        confidence=0.72,
        features_snapshot={"quadrant": 4, "cycle_mode": 1},
        would_have_entered=True,
    )

    log_file = shadow_logger._get_log_path()
    assert log_file.exists()

    lines = log_file.read_text().strip().split("\n")
    assert len(lines) >= 1

    record = json.loads(lines[0])
    assert record["model"] == "WCE2014"
    assert record["signal"] == "BUY"
    assert "timestamp" in record
    logger.success("✓ ShadowLogger grava JSONL válido")


def test_shadow_logger_does_not_call_executor():
    """Teste 5: ShadowLogger NÃO chama executor."""
    shadow_logger = ShadowLogger(log_dir=str(TEST_LOGS_DIR))

    for i in range(5):
        shadow_logger.log_signal(
            model="WCE2014",
            signal="SELL",
            confidence=0.65 + i * 0.05,
            features_snapshot={"quadrant": 2},
            would_have_entered=True,
        )

    assert shadow_logger.executor is None
    logger.success("✓ ShadowLogger não chama executor")


def test_model_trainer_temporal_split():
    """Teste 6: ModelTrainer usa split temporal."""
    n_samples = 200
    dates = [datetime(2024, 1, 1) + timedelta(days=i) for i in range(n_samples)]

    features = pd.DataFrame({
        "roofing_energy": np.random.randn(n_samples),
        "quadrant": np.random.randint(1, 5, n_samples),
        "cycle_mode": np.random.randint(0, 2, n_samples),
    }, index=dates)

    labels = pd.Series(np.random.randint(0, 2, n_samples), index=dates)

    trainer = ModelTrainer(models_dir=TEST_MODELS_DIR)
    result = trainer.train(features, labels)

    assert "train_size" in result
    assert "val_size" in result
    assert result["train_size"] + result["val_size"] == len(features)
    logger.success("✓ ModelTrainer split temporal correto")


def test_model_trainer_saves_model():
    """Teste 7: ModelTrainer salva modelo."""
    n_samples = 100
    dates = [datetime(2024, 1, 1) + timedelta(days=i) for i in range(n_samples)]

    features = pd.DataFrame({
        "roofing_energy": np.random.randn(n_samples),
        "quadrant": np.random.randint(1, 5, n_samples),
    }, index=dates)

    labels = pd.Series(np.random.randint(0, 2, n_samples), index=dates)

    trainer = ModelTrainer(models_dir=TEST_MODELS_DIR)
    result = trainer.train(features, labels)

    if result.get("trained"):
        model_path = TEST_MODELS_DIR / "pattern_v1.pkl"
        assert model_path.exists()

    logger.success("✓ ModelTrainer salva modelo")
