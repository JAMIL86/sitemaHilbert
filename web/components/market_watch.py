"""Painel de cotação de mercados relacionados (BTCUSD) — somente leitura.

INVARIANTE DE TRADING: este módulo é um widget de preço. Ele NÃO:
- instancia nem chama `V26Strategy` / `WCE2014Strategy`
- chama `ai.shadow_logger.ShadowLogger`
- toca `core.executor`
- altera `dry_run` ou `live_trading`

O BTCUSD é apenas exibido (gráfico + cotação). A estratégia continua
exclusiva para `settings.symbol_xau`.
"""

from __future__ import annotations

from typing import Any, Optional

# Símbolos de observação — deliberadamente fora de `settings.allowed_symbols`,
# que é a allowlist do Executor. Um símbolo aqui NUNCA pode ser executado.
WATCH_SYMBOLS: tuple[str, ...] = ("BTCUSD",)

# Rótulo explícito: identidade visual de que não há trading envolvido.
NO_TRADING_LABEL = "Monitoramento apenas — sem sinais"


def is_tradable_symbol(settings: Any, symbol: str) -> bool:
    """True somente se o símbolo for executável. Widgets de watch nunca são.

    allowlist do Executor: `allowed_symbols` + bases XAUUSD/XAGUSD e sufixos
    de corretora (ex: XAUUSD-VIP). BTCUSD não bate em nenhum critério.
    """
    clean = symbol.upper().strip()
    bases = ("XAUUSD", "XAGUSD")
    return (
        clean in tuple(settings.allowed_symbols)
        or clean in bases
        or any(clean.startswith(base) for base in bases)
    )


def get_quote(
    md: Any,
    symbol: str,
) -> dict[str, Optional[float]]:
    """Cotação atual (preço + spread) como dicionário. Nunca levanta."""
    quote: dict[str, Optional[float]] = {
        "symbol": symbol,  # type: ignore[dict-item]
        "price": None,
        "spread": None,
        "bid": None,
        "ask": None,
    }
    try:
        quote["price"] = md.get_latest_price(symbol)
        quote["spread"] = md.current_spread(symbol)
    except Exception:
        pass

    try:
        import MetaTrader5 as mt5

        tick = mt5.symbol_info_tick(symbol)
        if tick is not None:
            quote["bid"] = float(tick.bid)
            quote["ask"] = float(tick.ask)
    except Exception:
        pass

    return quote


def render_market_watch(
    df: Any,
    quote: dict[str, Optional[float]],
    symbol: str = "BTCUSD",
) -> None:
    """Renderiza o widget: rótulo de não-trading, cotação e gráfico.

    Reusa `chart_plotly.render_chart` — nenhum componente de gráfico duplicado.
    """
    import streamlit as st

    from web.components.chart_plotly import render_chart

    st.caption(f"ⓘ {NO_TRADING_LABEL} — apenas gráfico e cotação, fora da allowlist do Executor.")

    price = quote.get("price")
    if price is None:
        st.warning(
            f"{symbol}: sem cotação disponível. O símbolo pode não existir "
            f"neste terminal da corretora."
        )
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric(f"{symbol} — Preço", f"{price:,.2f}")
        spread = quote.get("spread")
        c2.metric("Spread", f"{spread:,.5f}" if spread is not None else "—")
        c3.metric("Magic do robô", "— (nenhum)")

    render_chart(df, symbol=symbol, dark_mode=False)
