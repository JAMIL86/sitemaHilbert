"""Gráfico de candles M5 com EMA 9/21 e Bollinger Bands (Etapa 8).

Plotly para interatividade (crosshair + tooltip nativo). Paleta validada com
o validador do skill `dataviz` (lightness band, chroma floor, separação CVD,
piso de visão normal e contraste — os seis checks, ambos os modos).
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

# --- Paleta validada (dataviz validate_palette.js) -------------------------
# Light:  #1D4ED8, #B45309, #7C3AED  → 6/6 PASS
# Dark:   #3B82F6, #D97706, #8B5CF6  → 6/6 PASS
PALETTE_LIGHT = {
    "ema9": "#1D4ED8",
    "ema21": "#B45309",
    "bb": "#7C3AED",
    "grid": "#E5E7EB",
}
PALETTE_DARK = {
    "ema9": "#3B82F6",
    "ema21": "#D97706",
    "bb": "#8B5CF6",
    "grid": "#374151",
}

UP_COLOR = "#0F766E"  # candle alta
DOWN_COLOR = "#B91C1C"  # candle baixa

# Shape + label acompanha a cor (identidade nunca é só cor)
CANDLE_INCREASING = dict(line=dict(color=UP_COLOR, width=1), fillcolor=UP_COLOR)
CANDLE_DECREASING = dict(line=dict(color=DOWN_COLOR, width=1), fillcolor=DOWN_COLOR)

BB_PERIOD = 20
BB_STD = 2.0
MIN_BARS_FOR_BB = 25


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Adiciona EMA 9, EMA 21 e Bollinger Bands (20, 2.0) ao DataFrame.

    Função pura e testável — não importa Streamlit.
    """
    if df is None or df.empty or "close" not in df.columns:
        return df

    out = df.copy()
    out["ema9"] = out["close"].ewm(span=9, adjust=False).mean()
    out["ema21"] = out["close"].ewm(span=21, adjust=False).mean()

    if len(out) >= MIN_BARS_FOR_BB:
        sma20 = out["close"].rolling(window=BB_PERIOD).mean()
        std20 = out["close"].rolling(window=BB_PERIOD).std()
        out["bb_upper"] = sma20 + (BB_STD * std20)
        out["bb_lower"] = sma20 - (BB_STD * std20)
    else:
        out["bb_upper"] = pd.NA
        out["bb_lower"] = pd.NA

    return out


def build_figure(
    df: pd.DataFrame,
    symbol: str = "XAUUSD-VIP",
    dark_mode: bool = False,
) -> Any:
    """Monta a figura Plotly: candlestick + EMA 9/21 + Bollinger Bands.

    Um único eixo Y (preço) — nunca dois eixos de escala diferente.
    """
    import plotly.graph_objects as go

    colors = PALETTE_DARK if dark_mode else PALETTE_LIGHT
    enriched = add_indicators(df)

    figure = go.Figure()

    figure.add_trace(
        go.Candlestick(
            x=enriched["time"],
            open=enriched["open"],
            high=enriched["high"],
            low=enriched["low"],
            close=enriched["close"],
            name=symbol,
            increasing=CANDLE_INCREASING,
            decreasing=CANDLE_DECREASING,
        )
    )

    # EMA 9 — 2px linha
    figure.add_trace(
        go.Scatter(
            x=enriched["time"],
            y=enriched["ema9"],
            name="EMA 9",
            mode="lines",
            line=dict(color=colors["ema9"], width=2),
        )
    )

    # EMA 21
    figure.add_trace(
        go.Scatter(
            x=enriched["time"],
            y=enriched["ema21"],
            name="EMA 21",
            mode="lines",
            line=dict(color=colors["ema21"], width=2),
        )
    )

    # Bollinger — traceiras 2px, sem preenchimento para não esconder o preço
    if "bb_upper" in enriched.columns and enriched["bb_upper"].notna().any():
        figure.add_trace(
            go.Scatter(
                x=enriched["time"],
                y=enriched["bb_upper"],
                name="BB superior (20, 2.0)",
                mode="lines",
                line=dict(color=colors["bb"], width=2, dash="dot"),
            )
        )
        figure.add_trace(
            go.Scatter(
                x=enriched["time"],
                y=enriched["bb_lower"],
                name="BB inferior (20, 2.0)",
                mode="lines",
                line=dict(color=colors["bb"], width=2, dash="dot"),
            )
        )

    figure.update_layout(
        title=f"{symbol} — M5",
        xaxis_title="Tempo",
        yaxis_title="Preço",
        template="plotly_dark" if dark_mode else "plotly_white",
        hovermode="x unified",  # crosshair + tooltip
        xaxis_rangeslider_visible=False,  # espaço para o gráfico
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=0, r=0, t=40, b=0),
        height=520,
    )
    figure.update_xaxes(gridcolor=colors["grid"], showspikes=True, spikemode="across")
    figure.update_yaxes(gridcolor=colors["grid"], side="right")

    return figure


def render_chart(
    df: pd.DataFrame,
    symbol: str = "XAUUSD-VIP",
    dark_mode: bool = False,
) -> None:
    """Renderiza o gráfico, ou uma mensagem amigável se os dados faltarem."""
    import streamlit as st

    if df is None or df.empty:
        st.info("Sem dados de mercado disponíveis. Conecte o MT5 para exibir o gráfico.")
        return

    if len(df) < MIN_BARS_FOR_BB:
        st.warning(
            f"⚠️ **Aguardando mais barras** — {len(df)}/{MIN_BARS_FOR_BB}. "
            "As Bollinger Bands (20 períodos) aparecem a partir da 25ª barra."
        )

    st.plotly_chart(
        build_figure(df, symbol=symbol, dark_mode=dark_mode),
        use_container_width=True,
        config={"displayModeBar": False},
    )
