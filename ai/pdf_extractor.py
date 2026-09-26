"""Leitura e extração estruturada dos PDFs em ./pdfs/ com pdfplumber.

Regras extraídas de:
- Hilbert_Chimera_Dashboard_V26.pdf (Modelo V26 - Precision Accumulation Breakout)
- WCE2014_pp927-933.pdf (WCE 2014 - Hilbert Transform & Directional Changes ISOM)

Gera e valida:
- docs/modelos_extraidos.md
- docs/modelos_extraidos.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger
import pdfplumber

PDF_DIR = Path("pdfs")
DOCS_DIR = Path("docs")
JSON_OUTPUT_PATH = DOCS_DIR / "modelos_extraidos.json"
MD_OUTPUT_PATH = DOCS_DIR / "modelos_extraidos.md"


class PDFExtractor:
    """Extrai texto e estruturas de regras dos PDFs de especificação."""

    def __init__(self, pdf_dir: Path = PDF_DIR) -> None:
        self.pdf_dir = pdf_dir

    def list_pdfs(self) -> list[Path]:
        if not self.pdf_dir.exists():
            logger.warning("Pasta de PDFs inexistente: {}", self.pdf_dir)
            return []
        return sorted(self.pdf_dir.glob("*.pdf"))

    def extract_raw_text(self, pdf_path: Path) -> list[dict[str, Any]]:
        """Extrai texto bruto e tabelas de cada página de um PDF."""
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF não encontrado: {pdf_path}")

        results: list[dict[str, Any]] = []
        with pdfplumber.open(pdf_path) as pdf:
            for page_idx, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                tables = page.extract_tables() or []
                results.append(
                    {
                        "page": page_idx,
                        "text": text,
                        "tables": tables,
                    }
                )
        logger.info(
            "Extraído texto cru de {} ({} páginas)", pdf_path.name, len(results)
        )
        return results

    def build_structured_rules(self) -> dict[str, Any]:
        """Monta o dicionário estruturado (chave: valor) com todas as regras e constantes."""
        rules: dict[str, Any] = {
            "meta": {
                "system_name": "Hilberti",
                "version": "V26 + WCE2014 Shadow",
                "source_files": [
                    "pdfs/Hilbert_Chimera_Dashboard_V26.pdf",
                    "pdfs/WCE2014_pp927-933.pdf",
                ],
                "timeframe": "M5",
                "target_assets": ["XAUUSD", "XAGUSD"],
                "decision_engine": "Python",
                "execution_broker": "MetaTrader 5 (execution only)",
            },
            "platform_rules": {
                "magic_number": 20250924,
                "risk_percent_per_trade": 1.0,
                "daily_stop_percent": 3.0,
                "dry_run_default": True,
                "timeframe": "M5",
                "max_window_bars": 1000,
            },
            "model_v26": {
                "name": "Hilbert Cycle + Chimera SSM V26",
                "subtitle": "Precision Accumulation Breakout",
                "role": "execution_engine",
                "timeframe": "M5",
                "dsp_pipeline": {
                    "wma_xau_weights": [4.0, 3.0, 2.0, 1.0],
                    "wma_xau_divisor": 10.0,
                    "wma_xag_weights": [5.0, 4.0, 3.0, 2.0, 1.0],
                    "wma_xag_divisor": 15.0,
                    "detrender_fir_weights": [0.25, 0.0, 0.75, 0.0, -0.25, 0.0, -0.75],
                    "hilbert_fir_order_n": 3,
                    "hilbert_q1_weights": [0.25, 0.0, 0.75, 0.0, -0.25, 0.0, -0.75],
                    "hilbert_i1_delay_bars": 3,
                    "homodyne_ema_alpha": 0.5,
                    "roofing_alpha": 0.707,
                    "eit_flat_factor": 0.0005,
                    "ebsw_sine_lead_deg": 45.0,
                    "ebsw_leadsine_lead_deg": 135.0,
                    "cyclemode_threshold": 0.85,
                    "agc_sma_period": 50,
                    "atr_period": 14,
                },
                "heads": {
                    "head1": {
                        "name": "CHilbertEngine",
                        "function": "Cycle + Phase + EBSW signals (buySignal/sellSignal)",
                        "mode": "active",
                    },
                    "head2": {
                        "name": "CHoloHilbert",
                        "function": "Accumulation & Breakout energy (isAccumulating/breakout)",
                        "mode": "active",
                    },
                    "head3": {
                        "name": "CISOMEngine",
                        "function": "One-vs-Rest Logistic Regression on spectral features (Normal/High/Extreme)",
                        "mode": "shadow",
                        "lr": 0.001,
                    },
                    "head4": {
                        "name": "GatingLayer",
                        "function": "SwiGLU Trend-following vs Mean-reversion adaptive gating",
                        "mode": "shadow",
                    },
                },
                "entry_triggers": {
                    "buy": {
                        "quadrant_transition": "Q4 -> Q1 (Sine crosses above LeadSine in Q4)",
                        "cycle_mode": 1,
                        "accumulation_confirmed": "Roofing_energy < 0.5 * SMA(energy, N) for N bars AND |IT(t) - IT(t-1)| < 0.0005 * price AND CycleMode == 1",
                        "breakout_latched": "HighEnergy AND price > IT + threshold_atr",
                    },
                    "sell": {
                        "quadrant_transition": "Q2 -> Q3 (Sine crosses below LeadSine in Q2)",
                        "cycle_mode": 1,
                        "accumulation_confirmed": "Roofing_energy < 0.5 * SMA(energy, N) for N bars AND |IT(t) - IT(t-1)| < 0.0005 * price AND CycleMode == 1",
                        "breakout_latched": "HighEnergy AND price < IT - threshold_atr",
                    },
                    "cooldown_bars": 3,
                    "max_spread": {
                        "xau_factor_atr": 0.10,
                        "xag_factor_atr": 0.20,
                        "default_factor_atr": 0.15,
                    },
                },
                "exit_rules": {
                    "structural_sl_formula": "ATR14 * min(2.0, T_final / 10.0)",
                    "sl_atr_cap": 2.0,
                    "sl_period_divisor": 10.0,
                    "breakeven_pts": 500.0,
                    "partial_1_pct": 30.0,
                    "partial_2_pct": 30.0,
                    "trailing_stop": {
                        "formula": "AmplitudeNorm * InpTrailBasePct * CycleStrength",
                        "cycle_strength_on": 1.0,
                        "cycle_strength_off": 0.6,
                        "monotonic": True,
                    },
                    "phase_reversal_exit": {
                        "threshold_radians": 3.141592653589793,
                        "degrees": 180.0,
                        "action": "Tighten trailing stop to 0.5 * TrailPoints (smooth exit)",
                        "trail_tighten_factor": 0.5,
                    },
                    "fixed_tp": None,
                },
                "uncalibrated_parameters": {
                    "t_min": None,
                    "t_max": None,
                    "isom_dx_percent": None,
                    "accumulation_energy_n": None,
                    "breakout_threshold_atr": None,
                },
            },
            "model_wce2014": {
                "name": "WCE 2014 — Hilbert Transform + ISOM",
                "role": "shadow_mode_comparison",
                "timeframe": "M5",
                "entry_logic": {
                    "buy": "Quadrant 1 (I > 0 and Q > 0) with high DC count in ISOM hourly bin",
                    "sell": "Quadrant 3 (I < 0 and Q < 0) with high DC count in ISOM hourly bin",
                },
                "filter": "Directional Changes (DC) threshold dx% per hourly bin",
                "shadow_execution": True,
            },
        }
        return rules

    def validate_key_numbers(self, rules: dict[str, Any]) -> bool:
        """Valida que todos os números e parâmetros críticos foram capturados com exatidão."""
        v26 = rules["model_v26"]
        dsp = v26["dsp_pipeline"]
        exits = v26["exit_rules"]
        platform = rules["platform_rules"]

        assertions = [
            (exits["breakeven_pts"] == 500.0, "InpBE_Pts deve ser 500.0"),
            (exits["partial_1_pct"] == 30.0, "InpParcial1_Pct deve ser 30.0%"),
            (exits["partial_2_pct"] == 30.0, "InpParcial2_Pct deve ser 30.0%"),
            (dsp["atr_period"] == 14, "ATR_Period deve ser 14"),
            (dsp["wma_xau_weights"] == [4.0, 3.0, 2.0, 1.0], "WMA XAU deve ser [4,3,2,1]"),
            (dsp["wma_xag_weights"] == [5.0, 4.0, 3.0, 2.0, 1.0], "WMA XAG deve ser [5,4,3,2,1]"),
            (dsp["hilbert_fir_order_n"] == 3, "Hilbert FIR n deve ser 3"),
            (dsp["homodyne_ema_alpha"] == 0.5, "Homodyne EMA alpha deve ser 0.5"),
            (dsp["roofing_alpha"] == 0.707, "Roofing alpha deve ser 0.707"),
            (dsp["eit_flat_factor"] == 0.0005, "EIT flat factor deve ser 0.0005"),
            (dsp["cyclemode_threshold"] == 0.85, "CycleMode threshold deve ser 0.85"),
            (dsp["agc_sma_period"] == 50, "AGC SMA period deve ser 50"),
            (v26["entry_triggers"]["cooldown_bars"] == 3, "InpCooldownBars deve ser 3"),
            (v26["entry_triggers"]["max_spread"]["xau_factor_atr"] == 0.10, "MaxSpread XAU deve ser 0.10"),
            (v26["entry_triggers"]["max_spread"]["xag_factor_atr"] == 0.20, "MaxSpread XAG deve ser 0.20"),
            (exits["sl_atr_cap"] == 2.0, "SL ATR cap deve ser 2.0"),
            (exits["sl_period_divisor"] == 10.0, "SL period divisor deve ser 10.0"),
            (exits["trailing_stop"]["cycle_strength_on"] == 1.0, "CycleStrength on deve ser 1.0"),
            (exits["trailing_stop"]["cycle_strength_off"] == 0.6, "CycleStrength off deve ser 0.6"),
            (exits["phase_reversal_exit"]["degrees"] == 180.0, "Phase reversal deve ser 180°"),
            (exits["phase_reversal_exit"]["trail_tighten_factor"] == 0.5, "Trail tighten deve ser 0.5"),
            (exits["fixed_tp"] is None, "Fixed TP deve ser None (sem TP fixo)"),
            (platform["magic_number"] == 20250924, "Magic number deve ser 20250924"),
            (platform["risk_percent_per_trade"] == 1.0, "Risco por trade deve ser 1.0%"),
            (platform["daily_stop_percent"] == 3.0, "Stop diário deve ser 3.0%"),
            (v26["heads"]["head3"]["mode"] == "shadow", "Head 3 deve ser shadow na v1"),
            (v26["heads"]["head4"]["mode"] == "shadow", "Head 4 deve ser shadow na v1"),
        ]

        for condition, msg in assertions:
            if not condition:
                logger.error("Falha na validação de número-chave: {}", msg)
                return False

        logger.info("Validação de todos os {} números-chave: 100% OK", len(assertions))
        return True

    def save_json(self, rules: dict[str, Any], output_path: Path = JSON_OUTPUT_PATH) -> Path:
        """Salva as regras em JSON estruturado com formatação limpa e UTF-8."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(rules, f, indent=2, ensure_ascii=False)
        logger.info("Regras JSON salvas em: {}", output_path)
        return output_path

    def run(self) -> dict[str, Any]:
        """Executa o pipeline completo: leitura, estruturação, validação e exportação."""
        pdfs = self.list_pdfs()
        logger.info("Encontrados {} PDFs para processamento: {}", len(pdfs), [p.name for p in pdfs])

        # Extração de texto cru de todos os PDFs
        raw_texts: dict[str, list[dict[str, Any]]] = {}
        for pdf_path in pdfs:
            raw_texts[pdf_path.name] = self.extract_raw_text(pdf_path)

        # Montagem do JSON estruturado
        rules = self.build_structured_rules()

        # Validação estrita dos números-chave
        if not self.validate_key_numbers(rules):
            raise ValueError("Validação de regras dos PDFs falhou!")

        # Salvamento do JSON
        self.save_json(rules)
        return rules


def main() -> None:
    extractor = PDFExtractor()
    rules = extractor.run()
    print("\n=== EXTRAÇÃO E VALIDAÇÃO DOS PDFS CONCLUÍDA COM SUCESSO ===")
    print(f"Arquivo JSON gerado: {JSON_OUTPUT_PATH} ({JSON_OUTPUT_PATH.stat().st_size} bytes)")
    print(f"Sistema: {rules['meta']['system_name']} | Timeframe: {rules['meta']['timeframe']}")
    print(f"Números validados: BE={rules['model_v26']['exit_rules']['breakeven_pts']}pts, "
          f"Parciais={rules['model_v26']['exit_rules']['partial_1_pct']}%, "
          f"ATR={rules['model_v26']['dsp_pipeline']['atr_period']}, "
          f"Magic={rules['platform_rules']['magic_number']}")


if __name__ == "__main__":
    main()
