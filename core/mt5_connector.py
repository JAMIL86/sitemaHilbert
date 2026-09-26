"""Conector e gerenciador de ciclo de vida do MetaTrader 5 (Etapa 6).

Responsabilidades:
1. Conexão resiliente com até 3 tentativas de reconexão.
2. Identificação de modo de conta (DEMO, CONTEST, REAL).
3. Trava de segurança para conta REAL exigindo CONFIRM_LIVE='yes_sou_consciente'.
4. Seleção e preparação de símbolos (XAUUSD, XAGUSD) no Market Watch.
5. Telemetria e heartbeat de conectividade com MT5.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from loguru import logger

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None  # type: ignore
    MT5_AVAILABLE = False

from config.settings import Settings, get_settings


class MT5Connector:
    """Gerenciador de conexão com o terminal MetaTrader 5."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.connected = False
        self._account_info: Optional[dict[str, Any]] = None

        # TRAVA CRÍTICA: Path obrigatório do Headway MT5 Terminal
        self.EXPECTED_MT5_PATH = r"C:\Program Files\Headway MT5 Terminal\terminal64.exe"
        self.EXPECTED_LOGIN = 1045989  # Conta Headway ECN-Pro VIP

    def connect(
        self,
        max_attempts: Optional[int] = None,
        retry_delay: Optional[float] = None,
    ) -> bool:
        """Inicializa e autentica no MetaTrader 5 com até N tentativas."""
        if not MT5_AVAILABLE or mt5 is None:
            logger.error("Pacote MetaTrader5 não está instalado ou não disponível nesta plataforma.")
            self.connected = False
            return False

        attempts = max_attempts or self.settings.max_reconnect_attempts
        delay = retry_delay or self.settings.reconnect_delay_seconds

        for attempt in range(1, attempts + 1):
            logger.info(
                "Tentativa de conexão MT5 ({}/{})...",
                attempt,
                attempts,
            )

            # TRAVA CRÍTICA: Inicializa MT5 SOMENTE com path do Headway
            initialized = False
            try:
                # 1. SEMPRE usa o path do Headway MT5 Terminal
                path_to_use = self.settings.mt5_path or self.EXPECTED_MT5_PATH
                logger.info("Conectando ao terminal: {}", path_to_use)

                init_kwargs: dict[str, Any] = {"path": path_to_use}

                # 2. Adiciona credenciais se configuradas
                if self.settings.mt5_login:
                    init_kwargs["login"] = int(self.settings.mt5_login)
                if self.settings.mt5_password:
                    init_kwargs["password"] = self.settings.mt5_password
                if self.settings.mt5_server:
                    init_kwargs["server"] = self.settings.mt5_server

                initialized = mt5.initialize(**init_kwargs)
            except Exception as e:
                logger.warning("Exceção ao chamar mt5.initialize(): {}", e)
                initialized = False

            if not initialized:
                error_code = mt5.last_error() if mt5 else "Unknown"
                logger.warning(
                    "Falha ao inicializar MT5 na tentativa {}/{}. Erro: {}",
                    attempt,
                    attempts,
                    error_code,
                )
                if attempt < attempts:
                    time.sleep(delay)
                continue

            # Validação do Account Info
            acc_info = mt5.account_info()

            # Se login/password/server foram passados e a conta atual for diferente da configurada
            if acc_info is None or (self.settings.mt5_login and acc_info.login != int(self.settings.mt5_login)):
                if self.settings.mt5_login and self.settings.mt5_password and self.settings.mt5_server:
                    try:
                        authorized = mt5.login(
                            login=int(self.settings.mt5_login),
                            password=self.settings.mt5_password,
                            server=self.settings.mt5_server,
                        )
                        if not authorized:
                            logger.warning(
                                "Falha ao autenticar login MT5 ({}/{}). Erro: {}",
                                attempt,
                                attempts,
                                mt5.last_error(),
                            )
                            # Se já temos um acc_info válido na sessão aberta, usamos a conta ativa
                            if acc_info is None:
                                mt5.shutdown()
                                if attempt < attempts:
                                    time.sleep(delay)
                                continue
                        else:
                            acc_info = mt5.account_info()
                    except Exception as e:
                        logger.warning("Exceção no mt5.login(): {}", e)
                        if acc_info is None:
                            mt5.shutdown()
                            if attempt < attempts:
                                time.sleep(delay)
                            continue

            if acc_info is None:
                logger.warning("MT5 conectado, mas account_info retornou None. Erro: {}", mt5.last_error())
                mt5.shutdown()
                if attempt < attempts:
                    time.sleep(delay)
                continue

            # VALIDAÇÃO CRÍTICA: Garante que conectou na conta Headway (1045989)
            if acc_info.login != self.EXPECTED_LOGIN:
                logger.critical(
                    "BLOQUEIO DE SEGURANÇA: Terminal conectado em conta ERRADA! "
                    "Esperado: {} (Headway ECN-Pro VIP) | Recebido: {} ({}).",
                    self.EXPECTED_LOGIN,
                    acc_info.login,
                    acc_info.server,
                )
                mt5.shutdown()
                self.connected = False
                return False

            # Mapeamento do Trade Mode
            trade_mode_val = getattr(acc_info, "trade_mode", 0)
            trade_mode_str = "DEMO"
            if trade_mode_val == getattr(mt5, "ACCOUNT_TRADE_MODE_REAL", 2):
                trade_mode_str = "REAL"
            elif trade_mode_val == getattr(mt5, "ACCOUNT_TRADE_MODE_CONTEST", 1):
                trade_mode_str = "CONTEST"

            # TRAVA DE SEGURANÇA 5: Confirmação estrita para CONTA REAL
            if trade_mode_str == "REAL" and (not self.settings.dry_run and self.settings.live_trading):
                if self.settings.confirm_live != "yes_sou_consciente":
                    logger.critical(
                        "BLOQUEIO CRÍTICO DE SEGURANÇA: Tentativa de operar em CONTA REAL sem a flag "
                        "CONFIRM_LIVE='yes_sou_consciente'. Abortando conexão imediatamente."
                    )
                    mt5.shutdown()
                    self.connected = False
                    return False

            self._account_info = {
                "login": acc_info.login,
                "trade_mode": trade_mode_str,
                "server": acc_info.server,
                "currency": acc_info.currency,
                "leverage": acc_info.leverage,
                "balance": acc_info.balance,
                "equity": acc_info.equity,
                "profit": acc_info.profit,
                "margin_free": acc_info.margin_free,
                "company": acc_info.company,
            }

            # Prepara os símbolos permitidos no Market Watch (inclui sufixos de corretora)
            symbols_to_select = list(self.settings.allowed_symbols) + [
                self.settings.symbol_xau,
                self.settings.symbol_xag,
                self.settings.mt5_symbol,
            ]
            for sym in dict.fromkeys(symbols_to_select):  # unique, preserve order
                if not sym:
                    continue
                selected = mt5.symbol_select(sym, True)
                if not selected:
                    logger.warning("Aviso: Símbolo {} não pôde ser ativado no Market Watch", sym)

            self.connected = True
            logger.info(
                "MT5 Conectado com Sucesso! Corretora: {} | Servidor: {} | Conta: {} ({}) | "
                "Saldo: {:.2f} {} | Equity: {:.2f} {}",
                self._account_info["company"],
                self._account_info["server"],
                self._account_info["login"],
                self._account_info["trade_mode"],
                self._account_info["balance"],
                self._account_info["currency"],
                self._account_info["equity"],
                self._account_info["currency"],
            )
            return True

        logger.critical(
            "FALHA CRÍTICA DE CONEXÃO: Não foi possível conectar ao MT5 após {} tentativas.",
            attempts,
        )
        self.connected = False
        return False

    def disconnect(self) -> None:
        """Desconecta graciosamente do terminal MetaTrader 5."""
        if MT5_AVAILABLE and mt5 is not None and self.connected:
            try:
                mt5.shutdown()
                logger.info("MT5 desconectado com sucesso.")
            except Exception as e:
                logger.warning("Erro ao desconectar MT5: {}", e)
        self.connected = False
        self._account_info = None

    def is_connected(self) -> bool:
        """Verifica o estado ativo da conexão com o terminal."""
        if not self.connected or not MT5_AVAILABLE or mt5 is None:
            return False
        try:
            terminal_info = mt5.terminal_info()
            if terminal_info is None or not terminal_info.connected:
                self.connected = False
                return False
            return True
        except Exception:
            self.connected = False
            return False

    def get_account_info(self) -> Optional[dict[str, Any]]:
        """Obtém dados atualizados da conta diretamente do MT5."""
        if not self.is_connected() or mt5 is None:
            return self._account_info

        try:
            acc = mt5.account_info()
            if acc is not None:
                trade_mode_val = getattr(acc, "trade_mode", 0)
                trade_mode_str = "DEMO"
                if trade_mode_val == getattr(mt5, "ACCOUNT_TRADE_MODE_REAL", 2):
                    trade_mode_str = "REAL"
                elif trade_mode_val == getattr(mt5, "ACCOUNT_TRADE_MODE_CONTEST", 1):
                    trade_mode_str = "CONTEST"

                self._account_info = {
                    "login": acc.login,
                    "trade_mode": trade_mode_str,
                    "server": acc.server,
                    "currency": acc.currency,
                    "leverage": acc.leverage,
                    "balance": acc.balance,
                    "equity": acc.equity,
                    "profit": acc.profit,
                    "margin_free": acc.margin_free,
                    "company": acc.company,
                }
        except Exception as e:
            logger.warning("Erro ao atualizar account_info: {}", e)

        return self._account_info
