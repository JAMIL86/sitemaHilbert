"""Teste de conexão real ao MT5 Headway com validações críticas (Etapa 6).

ATENÇÃO: Este teste conecta ao terminal MT5 REAL e valida:
1. Path correto (Headway MT5 Terminal)
2. Conta correta (1045989)
3. Símbolo XAUUSD-VIP
4. Coleta de 10 barras M5
5. Spread atual
"""

import pytest
from loguru import logger

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    mt5 = None

from config.settings import get_settings
from core.mt5_connector import MT5Connector


@pytest.mark.skipif(not MT5_AVAILABLE, reason="MetaTrader5 não disponível nesta plataforma")
def test_mt5_headway_connection():
    """Valida conexão ao terminal Headway com conta 1045989."""
    settings = get_settings()
    connector = MT5Connector(settings)

    # 1. Valida constantes críticas
    assert connector.EXPECTED_MT5_PATH == r"C:\Program Files\Headway MT5 Terminal\terminal64.exe"
    assert connector.EXPECTED_LOGIN == 1045989

    # 2. Conecta ao MT5
    logger.info("Iniciando conexão ao MT5 Headway...")
    connected = connector.connect()

    try:
        assert connected, "Falha ao conectar no MT5 Headway"

        # 3. Valida account_info
        acc_info = connector.get_account_info()
        assert acc_info is not None, "account_info retornou None"

        logger.info("Account Info: {}", acc_info)

        # 4. VALIDAÇÃO CRÍTICA: Conta DEVE ser 1045989 (Headway ECN-Pro VIP)
        assert acc_info["login"] == 1045989, (
            f"Conta ERRADA! Esperado: 1045989 (Headway) | "
            f"Recebido: {acc_info['login']} ({acc_info.get('server', 'Unknown')})"
        )

        # 5. Valida servidor Headway
        assert "Headway" in acc_info["server"], f"Servidor inesperado: {acc_info['server']}"

        logger.info(
            "✓ Conectado na conta CORRETA: {} ({}) | Servidor: {} | Saldo: {:.2f} {}",
            acc_info["login"],
            acc_info["trade_mode"],
            acc_info["server"],
            acc_info["balance"],
            acc_info["currency"],
        )

        # 6. Valida símbolo XAUUSD-VIP
        symbol = settings.symbol_xau
        assert "XAUUSD" in symbol, f"Símbolo inválido: {symbol}"

        symbol_info = mt5.symbol_info(symbol)
        assert symbol_info is not None, f"Símbolo {symbol} não encontrado no Market Watch"

        logger.info("✓ Símbolo {} disponível e ativo no Market Watch", symbol)

        # 7. Coleta 10 barras M5 de XAUUSD-VIP
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 10)
        assert rates is not None, f"Falha ao coletar barras de {symbol}"
        assert len(rates) >= 10, f"Esperado 10 barras, recebido {len(rates)}"

        logger.info("✓ Coletadas {} barras M5 de {}", len(rates), symbol)
        logger.info("  Última barra: Open={:.2f} High={:.2f} Low={:.2f} Close={:.2f}",
                   rates[-1]["open"], rates[-1]["high"], rates[-1]["low"], rates[-1]["close"])

        # 8. Valida spread atual
        tick = mt5.symbol_info_tick(symbol)
        assert tick is not None, f"Falha ao obter tick de {symbol}"

        spread = tick.ask - tick.bid
        logger.info("✓ Spread atual de {}: {:.2f} pontos (Ask={:.5f} | Bid={:.5f})",
                   symbol, spread, tick.ask, tick.bid)

        # 9. Resumo final
        logger.info("\n=== VALIDAÇÃO DE CONEXÃO MT5 CONCLUÍDA COM SUCESSO ===")
        logger.info("Path: {}", connector.EXPECTED_MT5_PATH)
        logger.info("Conta: {} (Headway ECN-Pro VIP)", acc_info["login"])
        logger.info("Servidor: {}", acc_info["server"])
        logger.info("Símbolo: {} (ativo e com dados)", symbol)
        logger.info("Barras M5: {} coletadas", len(rates))
        logger.info("Spread: {:.2f} pontos", spread)

    finally:
        # Desconecta sempre ao final
        connector.disconnect()
        logger.info("Desconectado do MT5 com sucesso.")


if __name__ == "__main__":
    # Execução direta para teste manual
    test_mt5_headway_connection()
