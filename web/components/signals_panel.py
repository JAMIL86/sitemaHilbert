"""Painel de sinais em tempo real (V26 / WCE shadow / Cabeças 3-4) — Etapa 8.

Funções puras para teste + renderização Streamlit.
"""

from __future__ import annotations

from typing import Any, Optional

# Paleta acessível (colorblind-safe): verde/vermelho distinguidos por shape e
# label, nunca só por cor. Usada também no chart_plotly.
COLOR_HOLD = "#6B7280"  # cinza
COLOR_BUY = "#0F766E"  # teal escuro
COLOR_SELL = "#B91C1C"  # vermelho escuro
COLOR_SHADOW = "#4338CA"  # indigo
COLOR_MUTED = "#9CA3AF"

SIGNAL_ICON = {"BUY": "▲", "SELL": "▼", "HOLD": "■"}


def normalize_v26(decision: Any) -> dict[str, Any]:
    """Normaliza um SignalDecision do V26Strategy em dict para exibição."""
    if decision is None:
        return {"signal": "HOLD", "confidence": None, "reasons": [], "metadata": {}}

    signal = getattr(decision, "signal", "HOLD")
    reasons = getattr(decision, "reasons", []) or []
    metadata = getattr(decision, "metadata", {}) or {}

    confidence = None
    for key in ("confidence", "cycle_mode", "quadrant"):
        if key in metadata:
            confidence = metadata[key]
            break

    return {
        "signal": signal,
        "confidence": confidence,
        "reasons": list(reasons),
        "metadata": dict(metadata),
    }


def normalize_wce(signal: Any) -> dict[str, Any]:
    """Normaliza o retorno do WCE2014Strategy (tupla ou Signal) em dict."""
    if signal is None:
        return {"signal": "HOLD", "confidence": None, "shadow": True}

    if isinstance(signal, tuple):
        sig = signal[0] if len(signal) > 0 else "HOLD"
        conf = signal[1] if len(signal) > 1 else None
        return {"signal": sig, "confidence": conf, "shadow": True}

    return {
        "signal": getattr(signal, "signal", "HOLD"),
        "confidence": getattr(signal, "confidence", None),
        "shadow": True,
    }


def heads_status(
    head3_shadow: bool = True,
    head4_shadow: bool = True,
    prediction: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Retorna o estado das Cabeças 3 (ISOM) e 4 (Gating) — sempre shadow na v1."""
    prediction = prediction or {}
    return {
        "head3": "Ativo (shadow)" if head3_shadow else "Desligado",
        "head4": "Ativo (shadow)" if head4_shadow else "Desligado",
        "confidence": prediction.get("confidence"),
        "regime": prediction.get("regime"),
        # Invariante da v1: nunca filtram entrada
        "filters_entry": False,
    }


def render_signals(
    v26: dict[str, Any],
    wce: dict[str, Any],
    heads: dict[str, Any],
) -> None:
    """Renderiza as 3 colunas de sinais: V26 | WCE shadow | Cabeças 3/4."""
    import streamlit as st

    col_v26, col_wce, col_heads = st.columns(3)

    with col_v26:
        sig = v26.get("signal", "HOLD")
        st.markdown("#### V26 — Motor Ativo")
        color = {"BUY": COLOR_BUY, "SELL": COLOR_SELL}.get(sig, COLOR_HOLD)
        icon = SIGNAL_ICON.get(sig, "■")
        st.markdown(
            f"<div style='font-size:2rem;font-weight:700;color:{color}'>"
            f"{icon} {sig}</div>",
            unsafe_allow_html=True,
        )
        conf = v26.get("confidence")
        st.caption(f"Confiança: {conf if conf is not None else '—'}")
        if v26.get("reasons"):
            with st.expander("Motivos", expanded=False):
                for reason in v26["reasons"]:
                    st.text(f"• {reason}")

    with col_wce:
        sig = wce.get("signal", "HOLD")
        st.markdown("#### WCE 2014 — Shadow")
        color = {"BUY": COLOR_BUY, "SELL": COLOR_SELL}.get(sig, COLOR_SHADOW)
        icon = SIGNAL_ICON.get(sig, "■")
        st.markdown(
            f"<div style='font-size:2rem;font-weight:700;color:{color}'>"
            f"{icon} {sig}</div>",
            unsafe_allow_html=True,
        )
        conf = wce.get("confidence")
        st.caption(f"Confiança: {conf if conf is not None else '—'}")
        st.caption("⚠️ Shadow — não executa")

    with col_heads:
        st.markdown("#### Cabeças 3/4 — Shadow")
        st.markdown(f"**Head 3 (ISOM):** {heads.get('head3', '—')}")
        st.markdown(f"**Head 4 (Gating):** {heads.get('head4', '—')}")
        conf = heads.get("confidence")
        st.caption(f"Confiança: {conf if conf is not None else '—'}")
        st.caption("⚠️ Shadow — não filtra entrada")
