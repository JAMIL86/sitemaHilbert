"""Script de teste manual MT5 — Execute com o terminal Headway ABERTO.

ANTES DE RODAR:
1. Abra o MetaTrader 5 Headway manualmente
2. Faça login na conta 1045989 (Headway ECN-Pro VIP)
3. Execute: python test_mt5_manual.py

Este script valida:
- Conexão ao terminal correto (Headway)
- Conta correta (1045989)
- Símbolo XAUUSD-VIP
- Coleta de 10 barras M5
- Spread atual
"""

from loguru import logger

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    mt5 = None

from config.settings import get_settings
from core.mt5_connector import MT5Connector


def main():
    if not MT5_AVAILABLE:
        print("❌ MetaTrader5 não está instalado ou não disponível!")
        return

    logger.info("=== TESTE MANUAL MT5 HEADWAY ===\n")

    settings = get_settings()
    connector = MT5Connector(settings)

    # 1. Valida constantes críticas
    logger.info("1. Validando constantes de segurança...")
    logger.info("   Path esperado: {}", connector.EXPECTED_MT5_PATH)
    logger.info("   Login esperado: {}", connector.EXPECTED_LOGIN)

    # 2. Conecta ao MT5
    logger.info("\n2. Conectando ao MT5 Headway...")
    connected = connector.connect()

    if not connected:
        logger.error("❌ FALHA ao conectar no MT5!")
        logger.error("   Certifique-se que:")
        logger.error("   - O terminal Headway MT5 está ABERTO")
        logger.error("   - Você está logado na conta 1045989")
        logger.error("   - O caminho está correto: {}", connector.EXPECTED_MT5_PATH)
        return

    try:
        # 3. Valida account_info
        logger.info("\n3. Validando informações da conta...")
        acc_info = connector.get_account_info()

        if acc_info is None:
            logger.error("❌ account_info retornou None!")
            return

        # 4. VALIDAÇÃO CRÍTICA: Conta DEVE ser 1045989
        logger.info("\n4. Verificando conta...")
        if acc_info["login"] != 1045989:
            logger.error(
                "❌ CONTA ERRADA! Esperado: 1045989 (Headway) | Recebido: {} ({})",
                acc_info["login"],
                acc_info.get("server", "Unknown")
            )
            return

        logger.success("✓ Conta CORRETA: {} ({})", acc_info["login"], acc_info["trade_mode"])
        logger.info("  Servidor: {}", acc_info["server"])
        logger.info("  Corretora: {}", acc_info["company"])
        logger.info("  Saldo: {:.2f} {}", acc_info["balance"], acc_info["currency"])
        logger.info("  Equity: {:.2f} {}", acc_info["equity"], acc_info["currency"])

        # 5. Valida símbolo XAUUSD-VIP
        logger.info("\n5. Validando símbolo XAUUSD-VIP...")
        symbol = settings.symbol_xau
        logger.info("  Símbolo configurado: {}", symbol)

        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            logger.error("❌ Símbolo {} não encontrado no Market Watch!", symbol)
            logger.info("  Tentando ativar o símbolo...")
            if mt5.symbol_select(symbol, True):
                logger.success("✓ Símbolo {} ativado com sucesso!", symbol)
                symbol_info = mt5.symbol_info(symbol)
            else:
                logger.error("❌ Falha ao ativar símbolo {}!", symbol)
                return
        else:
            logger.success("✓ Símbolo {} disponível no Market Watch", symbol)

        # 6. Coleta 10 barras M5
        logger.info("\n6. Coletando 10 barras M5 de {}...", symbol)
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 10)

        if rates is None:
            logger.error("❌ Falha ao coletar barras de {}!", symbol)
            return

        if len(rates) < 10:
            logger.warning("⚠️ Apenas {} barras coletadas (esperado 10)", len(rates))
        else:
            logger.success("✓ {} barras M5 coletadas com sucesso", len(rates))

        logger.info("\n  Última barra (Close):")
        logger.info("    Open:  {:.5f}", rates[-1]["open"])
        logger.info("    High:  {:.5f}", rates[-1]["high"])
        logger.info("    Low:   {:.5f}", rates[-1]["low"])
        logger.info("    Close: {:.5f}", rates[-1]["close"])

        # 7. Valida spread atual
        logger.info("\n7. Validando spread atual...")
        tick = mt5.symbol_info_tick(symbol)

        if tick is None:
            logger.error("❌ Falha ao obter tick de {}!", symbol)
            return

        spread_points = tick.ask - tick.bid
        logger.success("✓ Spread atual de {}: {:.5f} pontos", symbol, spread_points)
        logger.info("  Ask: {:.5f}", tick.ask)
        logger.info("  Bid: {:.5f}", tick.bid)

        # 8. Resumo final
        logger.info("\n" + "="*60)
        logger.success("✅ VALIDAÇÃO MT5 CONCLUÍDA COM SUCESSO!")
        logger.info("="*60)
        logger.info("Path:       {}", connector.EXPECTED_MT5_PATH)
        logger.info("Conta:      {} (Headway ECN-Pro VIP)", acc_info["login"])
        logger.info("Servidor:   {}", acc_info["server"])
        logger.info("Símbolo:    {} (ativo)", symbol)
        logger.info("Barras M5:  {} coletadas", len(rates))
        logger.info("Spread:     {:.5f} pontos", spread_points)
        logger.info("="*60)

    except Exception as e:
        logger.exception("❌ Erro durante a validação: {}", e)

    finally:
        # Desconecta sempre ao final
        logger.info("\nDesconectando do MT5...")
        connector.disconnect()
        logger.info("✓ Desconectado com sucesso.")


if __name__ == "__main__":
    main()
