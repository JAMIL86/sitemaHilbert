"""Módulo de coleta e streaming de Market Data via MetaTrader 5 (Etapa 6).

Responsabilidades:
1. Mapeamento de timeframes (M1, M5, M15, H1, etc.) para constantes do MT5.
2. Coleta de barras históricas OHLCV em tempo real (copy_rates_from_pos).
3. Conversão para Pandas DataFrame estruturado com timestamps UTC.
4. Consulta de spread instantâneo e ticks em tempo real (symbol_info_tick).
5. Metadados do ativo (point, digits, volume_min, volume_step, tick_value).
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd
from loguru import logger

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None  # type: ignore
    MT5_AVAILABLE = False

from config.settings import Settings, get_settings
from core.mt5_connector import MT5Connector


TIMEFRAME_MAP: dict[str, Any] = {}
if MT5_AVAILABLE and mt5 is not None:
    TIMEFRAME_MAP = {
        "M1": mt5.TIMEFRAME_M1,
        "M2": mt5.TIMEFRAME_M2,
        "M3": mt5.TIMEFRAME_M3,
        "M4": mt5.TIMEFRAME_M4,
        "M5": mt5.TIMEFRAME_M5,
        "M6": mt5.TIMEFRAME_M6,
        "M10": mt5.TIMEFRAME_M10,
        "M12": mt5.TIMEFRAME_M12,
        "M15": mt5.TIMEFRAME_M15,
        "M20": mt5.TIMEFRAME_M20,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H2": mt5.TIMEFRAME_H2,
        "H3": mt5.TIMEFRAME_H3,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }


class MarketData:
    """Provedor de dados de mercado conectado ao MT5."""

    def __init__(
        self,
        connector: MT5Connector | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.connector = connector or MT5Connector(self.settings)

    def _ensure_connected(self) -> bool:
        """Garante que a conexão com o terminal está ativa."""
        if not self.connector.is_connected():
            return self.connector.connect()
        return True

    def fetch_ohlcv(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        n_bars: Optional[int] = None,
    ) -> pd.DataFrame:
        """Busca as últimas N barras históricas no timeframe especificado.

        Retorna DataFrame com colunas: ['time', 'open', 'high', 'low', 'close', 'tick_volume', 'spread', 'real_volume']
        """
        symbol = symbol or self.settings.mt5_symbol
        tf_str = (timeframe or self.settings.timeframe).upper()
        n = n_bars or self.settings.max_window

        cols = ["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]

        if not MT5_AVAILABLE or mt5 is None:
            logger.error("MetaTrader5 indisponível para fetch_ohlcv.")
            return pd.DataFrame(columns=cols)

        if not self._ensure_connected():
            logger.error("Não foi possível conectar ao MT5 para obter dados de {}.", symbol)
            return pd.DataFrame(columns=cols)

        tf_mt5 = TIMEFRAME_MAP.get(tf_str, mt5.TIMEFRAME_M5)

        rates = mt5.copy_rates_from_pos(symbol, tf_mt5, 0, n)
        if rates is None or len(rates) == 0:
            error_code = mt5.last_error()
            logger.warning(
                "Nenhuma barra retornada para symbol={} tf={} n={}. Erro MT5: {}",
                symbol,
                tf_str,
                n,
                error_code,
            )
            return pd.DataFrame(columns=cols)

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df["open"] = df["open"].astype(np.float64)
        df["high"] = df["high"].astype(np.float64)
        df["low"] = df["low"].astype(np.float64)
        df["close"] = df["close"].astype(np.float64)
        df["tick_volume"] = df["tick_volume"].astype(np.int64)
        if "real_volume" in df.columns:
            df["real_volume"] = df["real_volume"].astype(np.int64)
        if "spread" in df.columns:
            df["spread"] = df["spread"].astype(np.int32)

        return df

    def current_spread(self, symbol: Optional[str] = None) -> Optional[float]:
        """Obtém o spread atual em unidades de preço (ask - bid)."""
        symbol = symbol or self.settings.mt5_symbol

        if not MT5_AVAILABLE or mt5 is None or not self._ensure_connected():
            return None

        tick = mt5.symbol_info_tick(symbol)
        if tick is None or tick.ask == 0.0 or tick.bid == 0.0:
            info = mt5.symbol_info(symbol)
            if info is not None and info.spread is not None and info.point is not None:
                return float(info.spread * info.point)
            return None

        spread_price = float(tick.ask - tick.bid)
        return round(spread_price, 5)

    def get_latest_price(self, symbol: Optional[str] = None) -> Optional[float]:
        """Obtém o preço atual (média bid/ask ou último tick)."""
        symbol = symbol or self.settings.mt5_symbol

        if not MT5_AVAILABLE or mt5 is None or not self._ensure_connected():
            return None

        tick = mt5.symbol_info_tick(symbol)
        if tick is not None and tick.bid > 0.0:
            if tick.ask > 0.0:
                return round((tick.bid + tick.ask) / 2.0, 5)
            return float(tick.bid)

        # Fallback para última barra
        bars = self.fetch_ohlcv(symbol=symbol, n_bars=1)
        if not bars.empty:
            return float(bars["close"].iloc[-1])

        return None

    def get_symbol_info(self, symbol: Optional[str] = None) -> Optional[dict[str, Any]]:
        """Retorna especificações operacionais do ativo."""
        symbol = symbol or self.settings.mt5_symbol

        if not MT5_AVAILABLE or mt5 is None or not self._ensure_connected():
            return None

        info = mt5.symbol_info(symbol)
        if info is None:
            return None

        return {
            "name": info.name,
            "point": info.point,
            "digits": info.digits,
            "spread": info.spread,
            "trade_tick_value": getattr(info, "trade_tick_value", 1.0),
            "trade_tick_size": getattr(info, "trade_tick_size", info.point),
            "volume_min": getattr(info, "volume_min", 0.01),
            "volume_max": getattr(info, "volume_max", 100.0),
            "volume_step": getattr(info, "volume_step", 0.01),
            "bid": info.bid,
            "ask": info.ask,
        }
