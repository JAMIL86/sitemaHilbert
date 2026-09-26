"""Downloader de dados históricos do MT5 para backtest (Etapa 9).

Responsável por:
1. Baixar barras históricas OHLCV do MT5 (copy_rates_range).
2. Salvar em CSV ou pickle para reutilização.
3. Validação: sem gaps, sem lookahead bias (dados estritamente <= data de referência).

INVARIANTE DE TRADING:
- Este módulo é SOMENTE LEITURA de dados históricos.
- Não executa ordens, não altera dry_run, não toca o Executor.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

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


class HistoricalDataDownloader:
    """Downloader de dados históricos do MT5 para backtest."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.connector = MT5Connector(self.settings)
        self.data_dir = Path("backtest/data")
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def download_range(
        self,
        symbol: str,
        timeframe: str = "M5",
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        months: int = 6,
    ) -> pd.DataFrame:
        """Baixa barras históricas do MT5 entre start_date e end_date.

        Args:
            symbol: Símbolo (ex: XAUUSD-VIP)
            timeframe: Timeframe (ex: M5)
            start_date: Data inicial (default: 6 meses atrás)
            end_date: Data final (default: hoje)
            months: Meses retroativos quando start_date é None

        Returns:
            DataFrame com colunas: time, open, high, low, close, tick_volume, spread, real_volume
        """
        if not MT5_AVAILABLE or mt5 is None:
            logger.error("MetaTrader5 indisponível.")
            return pd.DataFrame()

        if not self.connector.is_connected():
            if not self.connector.connect():
                logger.error("Falha ao conectar ao MT5.")
                return pd.DataFrame()

        tf_map = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
                  "H1": mt5.TIMEFRAME_H1, "D1": mt5.TIMEFRAME_D1}
        tf_mt5 = tf_map.get(timeframe.upper(), mt5.TIMEFRAME_M5)

        end_date = end_date or datetime.now()
        start_date = start_date or (end_date - timedelta(days=months * 30))

        logger.info("Baixando {} {} {} → {}", symbol, timeframe, start_date.date(), end_date.date())

        rates = mt5.copy_rates_range(symbol, tf_mt5, start_date, end_date)
        if rates is None or len(rates) == 0:
            error_code = mt5.last_error()
            logger.warning("Nenhuma barra retornada. Erro MT5: {}", error_code)
            return pd.DataFrame()

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.astype({"open": "float64", "high": "float64", "low": "float64", "close": "float64",
                        "tick_volume": "int64", "spread": "int32", "real_volume": "int64"})

        logger.info("Baixadas {} barras de {} a {}", len(df), df["time"].iloc[0], df["time"].iloc[-1])
        return df

    def save(self, df: pd.DataFrame, symbol: str, timeframe: str, fmt: str = "csv") -> Path:
        """Salva o DataFrame em disco (CSV ou pickle).

        Returns:
            Path do arquivo salvo
        """
        if df.empty:
            raise ValueError("DataFrame vazio — nada a salvar.")

        fname = f"{symbol}_{timeframe}_{df['time'].iloc[0].date()}_{df['time'].iloc[-1].date()}.{fmt}"
        fpath = self.data_dir / fname

        if fmt == "csv":
            df.to_csv(fpath, index=False)
        elif fmt == "pickle":
            df.to_pickle(fpath)
        else:
            raise ValueError(f"Formato desconhecido: {fmt}")

        logger.info("Salvo em {} ({} bytes)", fpath, fpath.stat().st_size)
        return fpath

    def load(self, path: Path) -> pd.DataFrame:
        """Carrega um arquivo salvo anteriormente."""
        if path.suffix == ".csv":
            df = pd.read_csv(path, parse_dates=["time"])
        elif path.suffix == ".pickle":
            df = pd.read_pickle(path)
        else:
            raise ValueError(f"Formato desconhecido: {path.suffix}")

        logger.info("Carregado {} barras de {}", len(df), path.name)
        return df

    def validate(self, df: pd.DataFrame) -> tuple[bool, str]:
        """Valida o DataFrame histórico (sem gaps, sem lookahead).

        Returns:
            (is_valid, mensagem_erro)
        """
        if df.empty:
            return False, "DataFrame vazio"

        if "time" not in df.columns:
            return False, "Coluna 'time' ausente"

        if not pd.api.types.is_datetime64_any_dtype(df["time"]):
            return False, "Coluna 'time' não é datetime"

        if df["time"].isna().any():
            return False, f"{df['time'].isna().sum()} timestamps NaT"

        if not df["time"].is_monotonic_increasing:
            return False, "Timestamps fora de ordem"

        gaps = (df["time"].diff() > timedelta(minutes=10)).sum()
        if gaps > 0:
            return False, f"{gaps} gaps > 10 min detectados"

        for col in ("open", "high", "low", "close"):
            if (df[col] <= 0).any():
                return False, f"{col} contém valores <= 0"

        return True, "OK"
