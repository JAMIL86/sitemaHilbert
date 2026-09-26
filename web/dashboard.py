"""Dashboard web do Hilberti (Etapa 8) — Streamlit.

Reusa core/, strategy/ e ai/ como CONSUMIDOR. Não altera nenhuma lógica
de decisão ou execução: o dashboard é somente leitura e visualização.

Invariantes de segurança mantidas:
- Nenhum botão de envio de ordem (o Executor tem suas próprias travas).
- dry_run é exibido visualmente e nunca alterado por aqui.
- Polling mínimo de 5s (nunca < 3s) para não sobrecarregar o MT5.

Execução:
    streamlit run web/dashboard.py
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any, Optional

import pandas as pd

from ai.feature_engineer import FeatureEngineer
from config.settings import Settings, get_settings
from core.market_data import MarketData
from core.mt5_connector import MT5Connector
from strategy.pdf_strategies import V26Strategy, WCE2014Strategy

from web.components.chart_plotly import render_chart
from web.components.logs_viewer import read_shadow_logs, render_shadow_logs
from web.components.market_watch import (
    WATCH_SYMBOLS,
    get_quote,
    render_market_watch,
)
from web.components.signals_panel import (
    heads_status,
    normalize_v26,
    normalize_wce,
    render_signals,
)

CACHE_TTL_SECONDS = 5
CHART_BARS = 300
WATCH_BARS = 300
MIN_BARS_FOR_FEATURES = 200

# --- Funções puras (testáveis sem Streamlit e sem MT5) ----------------------


def get_mode_banner(settings: Settings) -> tuple[str, str]:
    """Retorna (tipo_banner, mensagem) conforme o modo de execução.

    kind: "simulation" | "real"
    """
    if settings.dry_run:
        return (
            "simulation",
            "🟢 MODO SIMULAÇÃO (DRY-RUN) — nenhuma ordem é enviada ao MT5",
        )
    return (
        "real",
        "🔴 MODO REAL — ordens serão executadas no MT5",
    )


def fetch_market_data(
    md: MarketData,
    symbol: str,
    n_bars: int = CHART_BARS,
) -> pd.DataFrame:
    """Busca as últimas N barras. Retorna DataFrame vazio em falha (não levanta)."""
    try:
        df = md.fetch_ohlcv(symbol=symbol, timeframe="M5", n_bars=n_bars)
    except Exception:
        return pd.DataFrame()
    return df if df is not None else pd.DataFrame()


def compute_features(df: pd.DataFrame) -> Optional[Any]:
    """Calcula features DSP. Retorna None se houver menos barras do que o DSP exige."""
    if df is None or df.empty or len(df) < MIN_BARS_FOR_FEATURES:
        return None
    try:
        return FeatureEngineer().compute(df)
    except Exception:
        return None


def fetch_watch_data(md: MarketData, symbol: str) -> pd.DataFrame:
    """Busca barras de um símbolo de APENAS MONITORAMENTO (ex: BTCUSD).

    Somente leitura. Não alimenta FeatureEngineer, V26 nem o shadow_logger —
    os dados nunca chegam a qualquer caminho de decisão ou execução.
    """
    try:
        df = md.fetch_ohlcv(symbol=symbol, timeframe="M5", n_bars=WATCH_BARS)
    except Exception:
        return pd.DataFrame()
    return df if df is not None else pd.DataFrame()


def get_signals(
    features: Any,
    settings: Settings,
    symbol: str,
    current_price: Optional[float] = None,
    current_spread: Optional[float] = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Executa V26 (ativo) e WCE 2014 (shadow) sobre as mesmas features."""
    v26 = normalize_v26(
        V26Strategy(settings).signal(
            features,
            symbol=symbol,
            current_price=current_price,
            current_spread=current_spread,
        )
    )
    wce = normalize_wce(
        WCE2014Strategy(settings).signal(
            features,
            symbol=symbol,
            current_price=current_price,
        )
    )
    heads = heads_status(
        head3_shadow=settings.head3_shadow,
        head4_shadow=settings.head4_shadow,
    )
    return v26, wce, heads


def get_open_positions_table(connector: MT5Connector, settings: Settings) -> pd.DataFrame:
    """Posições abertas filtradas pelo magic number do robô."""
    if not connector.is_connected():
        return pd.DataFrame()

    try:
        import MetaTrader5 as mt5

        positions = mt5.positions_get(symbol=settings.symbol_xau)
    except Exception:
        return pd.DataFrame()

    if not positions:
        return pd.DataFrame()

    rows = [
        {
            "ticket": p.ticket,
            "side": "BUY" if p.type == 0 else "SELL",
            "volume": p.volume,
            "open": p.price_open,
            "current": p.price_current,
            "profit": round(p.profit, 2),
            "sl": p.sl,
            "tp": p.tp,
        }
        for p in positions
        if getattr(p, "magic", 0) == settings.magic_number
    ]
    return pd.DataFrame(rows)


def account_metrics(acc: Optional[dict[str, Any]]) -> dict[str, float]:
    """Normaliza saldo/equity/P&L para exibição."""
    if not acc:
        return {"balance": 0.0, "equity": 0.0, "profit": 0.0, "currency": "USD"}
    return {
        "balance": float(acc.get("balance", 0.0)),
        "equity": float(acc.get("equity", 0.0)),
        "profit": float(acc.get("profit", 0.0)),
        "currency": acc.get("currency", "USD"),
    }


def get_recent_orders_table(
    connector: MT5Connector,
    settings: Settings,
    limit: int = 10,
) -> pd.DataFrame:
    """Últimas ordens fechadas do robô, filtradas pelo magic number.

    Somente leitura via ``mt5.history_orders_get`` — nenhuma ordem é enviada.
    """
    if not connector.is_connected():
        return pd.DataFrame()

    try:
        import MetaTrader5 as mt5

        orders = mt5.history_orders_get(
            symbol=settings.symbol_xau,
            date_from=datetime.now() - timedelta(days=7),
            date_to=datetime.now(),
        )
    except Exception:
        return pd.DataFrame()

    if not orders:
        return pd.DataFrame()

    rows = [
        {
            "ticket": o.ticket,
            "time": str(getattr(o, "time_done", 0) or getattr(o, "time_setup", 0)),
            "side": "BUY" if o.type == 0 else "SELL",
            "volume": o.volume_current or o.volume_initial,
            "price": o.price_open,
            "sl": o.sl,
            "tp": o.tp,
            "state": _order_state_label(o),
        }
        for o in orders
        if getattr(o, "magic", 0) == settings.magic_number
    ]
    return pd.DataFrame(rows).tail(limit)


def _order_state_label(order: Any) -> str:
    """Traduz o estado numérico da ordem para rótulo legível."""
    state = getattr(order, "state", 0)
    return {
        0: "ativa",
        1: "preenchida",
        2: "cancelada",
        3: "parcial",
        4: "rejeitada",
        5: "expirada",
        6: "requisição",
        7: "modificada",
    }.get(state, "—")


# --- Camada Streamlit -------------------------------------------------------


def _connect() -> MT5Connector:
    """Conexão compartilhada via cache_resource (reusa sessão MT5)."""
    import streamlit as st

    @st.cache_resource(show_spinner=False)
    def _cached() -> MT5Connector:
        connector = MT5Connector(get_settings())
        connector.connect()
        return connector

    return _cached()


def _cached_fetch(ttl: int, symbol: str) -> pd.DataFrame:
    """Fetch de barras com cache de 5s (nunca < 3s)."""
    import streamlit as st

    @st.cache_data(ttl=ttl, show_spinner=False)
    def _inner(_connector: MT5Connector, _settings: Settings, _sym: str) -> pd.DataFrame:
        return fetch_market_data(MarketData(_connector), _sym, CHART_BARS)

    return _inner(_connect(), get_settings(), symbol)


def _clear_cache() -> None:
    import streamlit as st

    st.cache_data.clear()
    st.cache_resource.clear()


def render_header(settings: Settings, connector: MT5Connector) -> None:
    import streamlit as st

    st.title("Hilberti AI Trader")

    kind, message = get_mode_banner(settings)
    if kind == "simulation":
        st.success(message, icon="✅")
    else:
        st.error(message, icon="🚨")

    connected = connector.is_connected()
    acc = connector.get_account_info() if connected else None
    metrics = account_metrics(acc)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Conta MT5", acc.get("login", "—") if acc else "Desconectado")
    c2.metric("Servidor", acc.get("server", "—") if acc else "—")
    c3.metric("Saldo", f"{metrics['balance']:.2f} {metrics['currency']}")
    c4.metric("Equity", f"{metrics['equity']:.2f} {metrics['currency']}")

    if not connected:
        st.warning(
            "⚠️ **MT5 desconectado** — abra o terminal Headway "
            f"(conta 1045989) e clique em **Reconectar** abaixo."
        )
        if st.button("🔄 Reconectar", type="primary"):
            _clear_cache()
            st.rerun()
        st.divider()
        return

    if metrics["profit"]:
        delta = f"{metrics['profit']:+.2f}"
        c1.metric("P&L do dia", delta, delta=delta)


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="Hilberti AI Trader", layout="wide", page_icon="📈")

    settings = get_settings()
    connector = _connect()
    symbol = settings.symbol_xau

    st.sidebar.title("⚙️ Controles")
    st.sidebar.markdown(f"**Símbolo:** `{symbol}`")
    st.sidebar.markdown(f"**Timeframe:** M5")
    st.sidebar.markdown(f"**Magic:** `{settings.magic_number}`")
    st.sidebar.markdown(f"**Risco/trade:** {settings.risk_percent_per_trade}%")
    st.sidebar.markdown(f"**Stop diário:** {settings.daily_stop_percent}%")
    st.sidebar.divider()
    st.sidebar.caption(
        "Dashboard somente leitura. Nenhuma ordem é enviada por aqui — "
        "o envio é responsabilidade do `core/executor.py`, que exige "
        "`dry_run=False` **e** `live_trading=True` **e** "
        "`CONFIRM_LIVE=yes_sou_consciente`."
    )
    if st.sidebar.button("🔄 Forçar refresh"):
        _clear_cache()
        st.rerun()

    render_header(settings, connector)

    if not connector.is_connected():
        st.stop()

    # --- Gráfico ---
    st.subheader("📊 Gráfico de preços")
    df = _cached_fetch(CACHE_TTL_SECONDS, symbol)
    try:
        dark_mode = bool(st.get_option("theme.base") == "dark")
    except Exception:
        dark_mode = False
    render_chart(df, symbol=symbol, dark_mode=dark_mode)

    # --- Sinais ---
    st.subheader("🧠 Sinais em tempo real")
    features = compute_features(df)
    if features is None:
        st.info(
            f"⏳ **Aguardando {MIN_BARS_FOR_FEATURES}+ barras** para calcular as "
            f"features DSP. ({len(df) if df is not None else 0} disponíveis)"
        )
    else:
        current_price = None
        current_spread = None
        try:
            current_price = MarketData(connector).get_latest_price(symbol)
            current_spread = MarketData(connector).current_spread(symbol)
        except Exception:
            pass
        v26, wce, heads = get_signals(
            features, settings, symbol, current_price, current_spread
        )
        render_signals(v26, wce, heads)

    # --- Mercados relacionados (MONITORAMENTO APENAS — sem trading) ---
    watch_md = MarketData(connector)
    for watch_symbol in WATCH_SYMBOLS:
        st.subheader(f"👁️ {watch_symbol} — monitoramento")
        watch_df = fetch_watch_data(watch_md, watch_symbol)
        render_market_watch(watch_df, get_quote(watch_md, watch_symbol), watch_symbol)

    st.divider()

    # --- Posições ---
    st.subheader("📋 Posições abertas")
    positions = get_open_positions_table(connector, settings)
    if positions.empty:
        st.caption("Nenhuma posição aberta com magic 20250924.")
    else:
        st.dataframe(positions, use_container_width=True, hide_index=True)

    # --- Últimas ordens ---
    st.subheader("🧾 Últimas ordens (7 dias)")
    orders = get_recent_orders_table(connector, settings)
    if orders.empty:
        st.caption("Nenhuma ordem registrada nos últimos 7 dias.")
    else:
        st.dataframe(orders, use_container_width=True, hide_index=True)

    # --- Logs shadow ---
    st.subheader("📝 Logs de sinais (shadow)")
    render_shadow_logs()


if __name__ == "__main__":
    main()
