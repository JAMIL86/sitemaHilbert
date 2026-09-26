"""Leitor de logs shadow JSONL para o dashboard (Etapa 8).

Separado em funções puras (testáveis sem Streamlit) e renderização visual.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Campos na ordem de exibição da tabela
DISPLAY_COLUMNS = [
    "timestamp",
    "model",
    "signal",
    "confidence",
    "would_have_entered",
]


def read_shadow_logs(
    logs_dir: str | Path = "logs",
    model_filter: Optional[str] = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Lê as últimas entradas dos arquivos logs/shadow_*.jsonl.

    Retorna lista vazia (nunca levanta) se o diretório ou os arquivos não existirem.

    Args:
        logs_dir: Diretório contendo shadow_*.jsonl
        model_filter: Filtro opcional por nome do modelo (ex: "WCE2014")
        limit: Número máximo de entradas mais recentes

    Returns:
        Lista de dicts ordenada do mais recente para o mais antigo.
    """
    directory = Path(logs_dir)
    if not directory.exists():
        return []

    try:
        files = sorted(directory.glob("shadow_*.jsonl"), reverse=True)
    except OSError:
        return []

    records: list[dict[str, Any]] = []
    for file_path in files:
        if len(records) >= limit:
            break
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if model_filter and record.get("model") != model_filter:
                        continue
                    records.append(record)
        except OSError:
            continue

    # Mais recentes primeiro
    records.sort(key=lambda r: str(r.get("timestamp", "")), reverse=True)
    return records[:limit]


def available_models(logs_dir: str | Path = "logs") -> list[str]:
    """Retorna lista de modelos distintos presentes nos logs shadow."""
    models = {str(r.get("model")) for r in read_shadow_logs(logs_dir, limit=10_000)}
    models.discard("None")
    return sorted(models)


def render_shadow_logs(logs_dir: str | Path = "logs", limit: int = 20) -> None:
    """Renderiza a tabela de logs shadow com filtro por modelo."""
    import streamlit as st

    models = available_models(logs_dir)
    options = ["Todos"] + models

    col_filter, col_count, _ = st.columns([2, 1, 3])
    with col_filter:
        selected = st.selectbox(
            "Filtrar por modelo",
            options=options,
            key="shadow_model_filter",
        )
    with col_count:
        st.metric("Entradas", len(read_shadow_logs(logs_dir, limit=10_000)))

    model_filter = None if selected == "Todos" else selected
    records = read_shadow_logs(logs_dir, model_filter=model_filter, limit=limit)

    if not records:
        st.info(
            "Nenhum sinal shadow registrado ainda. "
            "Os logs aparecem em `logs/shadow_YYYYMMDD.jsonl` assim que a "
            "primeira barra for processada em modo shadow."
        )
        return

    rows = []
    for record in records:
        rows.append(
            {
                "timestamp": str(record.get("timestamp", ""))[:19].replace("T", " "),
                "model": record.get("model", "—"),
                "signal": record.get("signal", "—"),
                "confidence": record.get("confidence", "—"),
                "would_have_entered": record.get("would_have_entered", "—"),
            }
        )

    with st.expander(f"Últimas {len(rows)} entradas shadow", expanded=True):
        st.dataframe(rows, use_container_width=True, hide_index=True)


def prune_old_logs(logs_dir: str | Path = "logs", keep_days: int = 30) -> int:
    """Remove arquivos shadow com mais de keep_days. Retorna quantos removeu."""
    directory = Path(logs_dir)
    if not directory.exists():
        return 0

    cutoff = datetime.now().timestamp() - (keep_days * 86_400)
    removed = 0
    for file_path in directory.glob("shadow_*.jsonl"):
        try:
            if file_path.stat().st_mtime < cutoff:
                file_path.unlink()
                removed += 1
        except OSError:
            continue
    return removed
