"""Loop principal Hilberti.

Stub da Etapa 2: monta os componentes e sai. Sem loop de trading.
"""

from loguru import logger

from ai.feature_engineer import FeatureEngineer
from ai.model_trainer import ModelTrainer
from ai.pattern_detector import PatternDetector
from config.settings import get_settings
from core.executor import Executor
from core.market_data import MarketData
from core.mt5_connector import MT5Connector
from strategy.pdf_strategies import StrategyRouter


def build() -> dict:
    settings = get_settings()
    logger.info(
        "Hilberti stub tf={} magic={} dry_run={} modelo={} wce_shadow={} h3={} h4={}",
        settings.timeframe,
        settings.magic_number,
        settings.dry_run,
        settings.active_model,
        settings.wce_shadow,
        settings.head3_shadow,
        settings.head4_shadow,
    )
    connector = MT5Connector(settings)
    return {
        "settings": settings,
        "connector": connector,
        "market": MarketData(connector, settings),
        "executor": Executor(connector, settings),
        "features": FeatureEngineer(settings),
        "patterns": PatternDetector(settings),
        "trainer": ModelTrainer(settings),
        "router": StrategyRouter(settings),
    }


def run() -> None:
    logger.warning("main.run() stub — loop de trading ainda não implementado")
    build()


if __name__ == "__main__":
    run()
