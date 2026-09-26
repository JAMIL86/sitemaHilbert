"""Script de validação da conexão real ao vivo com o MetaTrader 5 (Etapa 6).

Executa:
1. Conexão e autenticação na conta DEMO configurada no .env.
2. Leitura dos metadados da conta (corretora, servidor, saldo, equity).
3. Coleta das últimas 10 barras OHLCV M5 de XAUUSD.
4. Consulta do spread instantâneo e ticks em tempo real.
5. Garantia absoluta de que nenhuma ordem é enviada.
"""

from __future__ import annotations

import sys
from loguru import logger
import pandas as pd

from config.settings import get_settings
from core.market_data import MarketData
from core.mt5_connector import MT5Connector


def main() -> None:
    settings = get_settings()
    logger.info("Iniciando teste de conectividade com MetaTrader 5...")
    logger.info("Configuração ativa: dry_run={} | live_trading={}", settings.dry_run, settings.live_trading)

    connector = MT5Connector(settings)
    market_data = MarketData(connector, settings)

    connected = connector.connect()
    if not connected:
        logger.critical("Falha ao conectar no terminal MT5.")
        sys.exit(1)

    try:
        acc_info = connector.get_account_info()
        print("\n" + "=" * 65)
        print("           METATRADER 5 — CONECTIVIDADE VALIDADA")
        print("=" * 65)
        if acc_info:
            print(f" Corretora     : {acc_info.get('company')}")
            print(f" Servidor      : {acc_info.get('server')}")
            print(f" Conta / Login : {acc_info.get('login')} ({acc_info.get('trade_mode')})")
            print(f" Moeda         : {acc_info.get('currency')}")
            print(f" Saldo         : {acc_info.get('balance'):,.2f} {acc_info.get('currency')}")
            print(f" Equity        : {acc_info.get('equity'):,.2f} {acc_info.get('currency')}")
            print(f" Margem Livre  : {acc_info.get('margin_free'):,.2f} {acc_info.get('currency')}")
        print("-" * 65)

        # 1. Coleta de 10 barras M5 de XAUUSD
        symbol = settings.symbol_xau
        print(f"\n>> Coletando 10 barras M5 de {symbol}...")
        df = market_data.fetch_ohlcv(symbol=symbol, timeframe="M5", n_bars=10)

        if df.empty:
            logger.warning("Nenhuma barra retornada para {}.", symbol)
        else:
            pd.set_option("display.max_columns", 10)
            pd.set_option("display.width", 1000)
            print("\nÚLTIMAS 10 BARRAS M5 (XAUUSD):")
            print(df.to_string(index=False))

        # 2. Spread e Preço Atual
        spread = market_data.current_spread(symbol=symbol)
        price = market_data.get_latest_price(symbol=symbol)
        sym_info = market_data.get_symbol_info(symbol=symbol)

        print("\n" + "-" * 65)
        print(f">> COTAÇÃO E SPREAD EM TEMPO REAL ({symbol}):")
        print(f" Preço Atual : {price}")
        print(f" Spread Atual: {spread} (unidades de preço)")
        if sym_info:
            print(f" Digits      : {sym_info.get('digits')}")
            print(f" Point Size  : {sym_info.get('point')}")
            print(f" Lote Mín/Máx: {sym_info.get('volume_min')} / {sym_info.get('volume_max')}")
        print("=" * 65 + "\n")

    finally:
        connector.disconnect()
        logger.info("Teste de conexão concluído com sucesso e MT5 desconectado.")


if __name__ == "__main__":
    main()
