"""Sistema de logging para modo shadow (Etapa 7).

Responsabilidades:
- Registra sinais WCE 2014 (shadow) em logs/shadow_wce.jsonl
- Registra sinais das cabeças 3/4 em shadow
- NUNCA chama executor — apenas loga
- Rotação diária automática (1 arquivo/dia)
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from loguru import logger


class ShadowLogger:
    """Logger para sinais em modo shadow (apenas telemetria, sem execução)."""

    def __init__(
        self,
        log_dir: str = "logs",
        prefix: str = "shadow",
        executor: Any = None,  # Explicitamente None — nunca deve ter executor
    ) -> None:
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.prefix = prefix
        self.executor = executor  # Deve ser sempre None

        if self.executor is not None:
            raise ValueError(
                "ShadowLogger NÃO deve ter referência ao executor! "
                "Modo shadow é apenas telemetria, nunca execução."
            )

    def _get_log_path(self) -> Path:
        """Retorna path do arquivo de log para hoje (rotação diária)."""
        date_str = datetime.now().strftime("%Y%m%d")
        return self.log_dir / f"{self.prefix}_{date_str}.jsonl"

    def log_signal(
        self,
        model: str,
        signal: str,
        confidence: float,
        features_snapshot: dict[str, Any],
        would_have_entered: bool,
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        """Registra sinal shadow em arquivo JSONL.

        Args:
            model: Nome do modelo (ex: "WCE2014", "Head3_ISOM", "Head4_Gating")
            signal: Sinal gerado ("BUY", "SELL", "HOLD")
            confidence: Confiança do modelo (0.0 a 1.0)
            features_snapshot: Snapshot das features no momento do sinal
            would_have_entered: Se o sinal teria gerado entrada (se não fosse shadow)
            extra: Campos adicionais (opcional)
        """
        record = {
            "timestamp": datetime.now().isoformat(),
            "model": model,
            "signal": signal,
            "confidence": round(confidence, 4),
            "features_snapshot": features_snapshot,
            "would_have_entered": would_have_entered,
        }

        if extra:
            record.update(extra)

        log_path = self._get_log_path()

        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

            logger.debug(
                "ShadowLogger: {} signal={} confidence={:.2f} logged to {}",
                model,
                signal,
                confidence,
                log_path.name,
            )
        except Exception as e:
            logger.warning("Falha ao gravar log shadow: {}", e)

    def get_today_signals(self) -> list[dict[str, Any]]:
        """Lê todos os sinais gravados hoje."""
        log_path = self._get_log_path()

        if not log_path.exists():
            return []

        signals = []
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        signals.append(json.loads(line))
        except Exception as e:
            logger.warning("Falha ao ler log shadow: {}", e)

        return signals

    def count_signals_today(self, model: Optional[str] = None) -> int:
        """Conta sinais gravados hoje (opcionalmente filtrados por modelo)."""
        signals = self.get_today_signals()

        if model:
            return sum(1 for s in signals if s.get("model") == model)

        return len(signals)
