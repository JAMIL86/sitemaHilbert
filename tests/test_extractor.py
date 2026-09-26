"""Testes unitários para o módulo de extração e validação dos PDFs de especificação."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from ai.pdf_extractor import PDFExtractor, JSON_OUTPUT_PATH, MD_OUTPUT_PATH


def test_pdf_extractor_rules_structure():
    """Valida que o extrator gera a árvore completa com os 2 modelos e regras de plataforma."""
    extractor = PDFExtractor(pdf_dir=Path("pdfs"))
    rules = extractor.build_structured_rules()

    assert "meta" in rules
    assert "platform_rules" in rules
    assert "model_v26" in rules
    assert "model_wce2014" in rules

    assert rules["meta"]["timeframe"] == "M5"
    assert "XAUUSD" in rules["meta"]["target_assets"]
    assert rules["meta"]["execution_broker"] == "MetaTrader 5 (execution only)"


def test_pdf_extractor_key_numbers_validation():
    """Valida que todos os 27 parâmetros críticos passam na verificação estrita."""
    extractor = PDFExtractor(pdf_dir=Path("pdfs"))
    rules = extractor.build_structured_rules()
    assert extractor.validate_key_numbers(rules) is True


def test_json_persisted_file_matches_rules():
    """Valida que o arquivo docs/modelos_extraidos.json existe e é válido."""
    assert JSON_OUTPUT_PATH.exists()
    assert JSON_OUTPUT_PATH.stat().st_size > 0

    with open(JSON_OUTPUT_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["platform_rules"]["magic_number"] == 20250924
    assert data["model_v26"]["exit_rules"]["breakeven_pts"] == 500.0
    assert data["model_v26"]["exit_rules"]["partial_1_pct"] == 30.0
    assert data["model_v26"]["exit_rules"]["partial_2_pct"] == 30.0
    assert data["model_v26"]["dsp_pipeline"]["atr_period"] == 14
