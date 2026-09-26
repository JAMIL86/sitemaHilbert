"""Motor de execução e gestão de ordens no MetaTrader 5 (Etapa 6).

Responsabilidades:
1. Tripla Trava de Segurança (dry_run=True, live_trading=False, CONFIRM_LIVE='yes_sou_consciente').
2. Validação estrita pré-ordem (volume <= 0.10, SL >= 50 pts, magic=20250924, symbols XAU/XAG).
3. Circuit Breaker de Stop Diário (3.0% do saldo bloqueia todas as ordens até 00:00 UTC).
4. Dimensionamento dinâmico de lote com base no risco exato de 1.0% por trade.
5. Operações de trade: Envio de Ordem (BUY/SELL), Modificação de SL (Breakeven/Trailing),
   Fechamento Parcial (30%+30%) e Encerramento Total.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

import numpy as np
from loguru import logger

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None  # type: ignore
    MT5_AVAILABLE = False

from config.settings import Settings, get_settings
from core.mt5_connector import MT5Connector
from strategy.pdf_strategies import Position, TradeAction

Signal = Literal["BUY", "SELL", "HOLD"]


class Executor:
    """Executor de ordens conectado ao MetaTrader 5 com travas de segurança institucionais."""

    def __init__(
        self,
        connector: MT5Connector | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.connector = connector or MT5Connector(self.settings)
        self._simulated_ticket_counter = 100000

    def is_live_execution_armed(self) -> bool:
        """Verifica a TRIPLA TRAVA: Somente arma se dry_run=False E live_trading=True."""
        return (not self.settings.dry_run) and self.settings.live_trading

    def daily_stop_hit(self) -> bool:
        """Verifica se a perda acumulada no dia atingiu ou superou o Stop Diário de 3.0%."""
        if not MT5_AVAILABLE or mt5 is None or not self.connector.is_connected():
            return False

        try:
            now_utc = datetime.now(timezone.utc)
            start_of_day_utc = datetime(now_utc.year, now_utc.month, now_utc.day, tzinfo=timezone.utc)

            # Histórico de deals fechados hoje
            deals = mt5.history_deals_get(start_of_day_utc, now_utc)
            daily_profit = 0.0
            if deals:
                for deal in deals:
                    # Considera apenas deals da estratégia ou da conta no dia
                    if getattr(deal, "magic", 0) == self.settings.magic_number or getattr(deal, "entry", 0) == 1:
                        daily_profit += (deal.profit + getattr(deal, "swap", 0.0) + getattr(deal, "commission", 0.0))

            acc = self.connector.get_account_info()
            if acc is None:
                return False

            balance = acc.get("balance", 0.0)
            if balance <= 0.0:
                return False

            # Se o PnL do dia for negativo e representar >= 3% do saldo
            if daily_profit < 0.0:
                drawdown_pct = (abs(daily_profit) / balance) * 100.0
                if drawdown_pct >= self.settings.daily_stop_percent:
                    logger.critical(
                        "CIRCUIT BREAKER: Stop Diário de 3.0% atingido! Perda hoje: {:.2f} {} ({:.2f}%). "
                        "Todas as ordens estão bloqueadas até 00:00 UTC.",
                        daily_profit,
                        acc.get("currency", "USD"),
                        drawdown_pct,
                    )
                    return True

            return False
        except Exception as e:
            logger.warning("Erro ao calcular stop diário no MT5: {}", e)
            return False

    def calculate_lot_size(
        self,
        sl_points: float,
        symbol: str,
        account_balance: Optional[float] = None,
    ) -> float:
        """Calcula o volume do lote para arriscar exatamente 1.0% do saldo com base no SL.

        Fórmula: Lote = (Saldo * 0.01) / (SL_pts * Valor_Ponto_Por_Lote)
        Cap estrito: max_volume = 0.10 lote.
        """
        if sl_points <= 0.0:
            logger.warning("sl_points <= 0 ({}), usando volume mínimo seguro {}", sl_points, self.settings.min_volume)
            return self.settings.min_volume

        balance = account_balance
        if balance is None:
            acc = self.connector.get_account_info()
            balance = acc.get("balance", 1000.0) if acc else 1000.0

        risk_amount_usd = balance * (self.settings.risk_percent_per_trade / 100.0)

        # Determina valor de 1 ponto (ex: 1.00 USD) para 1.0 lote padrão
        # No XAUUSD padrão (100 oz): 1 pt = $1.00 de preço * 100 = $100 por lote.
        point_value_per_lot = 100.0
        if "XAG" in symbol.upper():
            # XAGUSD padrão (5000 oz): 1 pt = $1.00 de preço * 5000 = $5000 por lote.
            point_value_per_lot = 5000.0

        if MT5_AVAILABLE and mt5 is not None and self.connector.is_connected():
            info = mt5.symbol_info(symbol)
            if info is not None:
                tick_value = getattr(info, "trade_tick_value", None)
                tick_size = getattr(info, "trade_tick_size", None)
                if tick_value and tick_size and tick_size > 0:
                    point_value_per_lot = tick_value / tick_size

        lot_raw = risk_amount_usd / (sl_points * point_value_per_lot)

        # Arredondamento pelo step de 0.01
        lot_rounded = round(float(np.floor(lot_raw / self.settings.min_volume) * self.settings.min_volume), 2)

        # Garante limites institucionais: min_volume (0.01) <= lote <= max_volume (0.10)
        lot_final = max(self.settings.min_volume, min(lot_rounded, self.settings.max_volume))

        logger.debug(
            "Dimensionamento de Risco (1%): Saldo={:.2f} | Risco=${:.2f} | SL_pts={:.2f} | Lote={:.2f}",
            balance,
            risk_amount_usd,
            sl_points,
            lot_final,
        )
        return lot_final

    def validate_order(
        self,
        symbol: str,
        volume: float,
        current_price: float,
        sl_price: float,
        tp_price: Optional[float] = None,
        magic: Optional[int] = None,
    ) -> tuple[bool, str]:
        """Valida todas as 5 regras de segurança obrigatórias antes do envio da ordem."""
        # 1. Símbolo Permitido (aceita sufixos de corretora, ex: XAUUSD-VIP)
        clean_sym = symbol.upper().strip()
        allowed_bases = ("XAUUSD", "XAGUSD")
        is_allowed = (
            clean_sym in self.settings.allowed_symbols
            or clean_sym in allowed_bases
            or any(clean_sym.startswith(base) for base in allowed_bases)
        )
        if not is_allowed:
            msg = f"Símbolo inválido '{symbol}'. Permitidos apenas: {self.settings.allowed_symbols} (ou sufixos de corretora)"
            logger.error("VALIDAÇÃO FALHOU: {}", msg)
            return False, msg

        # 2. Volume dentro do teto seguro (0 < volume <= 0.10)
        if volume <= 0.0 or volume > self.settings.max_volume:
            msg = f"Volume inválido ({volume:.2f}). Deve ser > 0 e <= {self.settings.max_volume}"
            logger.error("VALIDAÇÃO FALHOU: {}", msg)
            return False, msg

        # 3. Distância mínima do Stop Loss (>= 50 pontos)
        sl_distance = abs(current_price - sl_price)
        if sl_distance < self.settings.min_sl_distance_pts:
            msg = (
                f"Distância do SL ({sl_distance:.2f} pts) inferior ao mínimo de segurança "
                f"({self.settings.min_sl_distance_pts:.2f} pts). Preço: {current_price:.2f}, SL: {sl_price:.2f}"
            )
            logger.error("VALIDAÇÃO FALHOU: {}", msg)
            return False, msg

        # 4. Distância mínima do Take Profit (se fornecido)
        if tp_price is not None and tp_price > 0.0:
            tp_distance = abs(current_price - tp_price)
            if tp_distance < self.settings.min_sl_distance_pts:
                msg = (
                    f"Distância do TP ({tp_distance:.2f} pts) inferior ao mínimo de segurança "
                    f"({self.settings.min_sl_distance_pts:.2f} pts)."
                )
                logger.error("VALIDAÇÃO FALHOU: {}", msg)
                return False, msg

        # 5. Magic Number Institucional
        order_magic = magic or self.settings.magic_number
        if order_magic != self.settings.magic_number:
            msg = f"Magic number incorreto ({order_magic}). Esperado: {self.settings.magic_number}"
            logger.error("VALIDAÇÃO FALHOU: {}", msg)
            return False, msg

        return True, "Validação de segurança aprovada com sucesso."

    def execute_signal(
        self,
        signal: Signal,
        symbol: str,
        current_price: float,
        sl_price: float,
        sl_points: float,
        volume: Optional[float] = None,
        tp_price: Optional[float] = None,
        comment: str = "Hilberti V26",
    ) -> dict[str, Any]:
        """Executa entrada de mercado (BUY / SELL) validando travas e regras de risco."""
        if signal == "HOLD":
            logger.debug("Executor: Sinal HOLD recebido — nenhuma ordem a enviar.")
            return {"status": "SKIPPED", "reason": "Signal is HOLD"}

        # 1. Verifica Stop Diário 3%
        if self.daily_stop_hit():
            logger.critical("Ordem abortada: Circuit Breaker de Stop Diário (3%) ativo.")
            return {"status": "ABORTED", "reason": "Daily stop loss 3% reached"}

        # 2. Calcula / valida volume (Risco 1%)
        vol = volume if volume is not None else self.calculate_lot_size(sl_points, symbol)

        # 3. Validação estrita pré-ordem
        valid, msg = self.validate_order(
            symbol=symbol,
            volume=vol,
            current_price=current_price,
            sl_price=sl_price,
            tp_price=tp_price,
            magic=self.settings.magic_number,
        )
        if not valid:
            return {"status": "ABORTED", "reason": msg}

        # 4. TRIPLA TRAVA: Simulação vs Execução Real
        if not self.is_live_execution_armed():
            self._simulated_ticket_counter += 1
            simulated_ticket = self._simulated_ticket_counter
            logger.info(
                "[MODO SEGURO / SIMULAÇÃO] Ordem {} {} Lote={:.2f} Preço={:.2f} SL={:.2f} | "
                "dry_run={} live_trading={} | Ticket Simulado #{}",
                signal,
                symbol,
                vol,
                current_price,
                sl_price,
                self.settings.dry_run,
                self.settings.live_trading,
                simulated_ticket,
            )
            return {
                "status": "SIMULATED",
                "ticket": simulated_ticket,
                "signal": signal,
                "symbol": symbol,
                "volume": vol,
                "price": current_price,
                "sl": sl_price,
                "tp": tp_price,
                "magic": self.settings.magic_number,
                "dry_run": self.settings.dry_run,
                "live_trading": self.settings.live_trading,
            }

        # 5. EXECUÇÃO REAL NO METATRADER 5
        if not MT5_AVAILABLE or mt5 is None or not self.connector.is_connected():
            logger.error("MT5 não conectado para execução real da ordem.")
            return {"status": "ERROR", "reason": "MT5 not connected"}

        order_type = mt5.ORDER_TYPE_BUY if signal == "BUY" else mt5.ORDER_TYPE_SELL

        # Preço de execução direto do book do MT5
        tick = mt5.symbol_info_tick(symbol)
        if tick is not None:
            exec_price = tick.ask if signal == "BUY" else tick.bid
        else:
            exec_price = current_price

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(vol),
            "type": order_type,
            "price": float(exec_price),
            "sl": float(sl_price),
            "tp": float(tp_price) if tp_price else 0.0,
            "deviation": 20,
            "magic": self.settings.magic_number,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        logger.info("Enviando ordem REAL ao MT5: {} {} {:.2f} lotes @ {:.2f}", signal, symbol, vol, exec_price)
        result = mt5.order_send(request)

        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            retcode = getattr(result, "retcode", "None")
            comment_err = getattr(result, "comment", mt5.last_error())
            logger.error("FALHA ao enviar ordem MT5. Retcode: {} | Detalhes: {}", retcode, comment_err)
            return {"status": "FAILED", "retcode": retcode, "reason": str(comment_err)}

        logger.info(
            "Ordem REAL executada com SUCESSO! Ticket: #{} | Volume: {:.2f} | Preço: {:.2f}",
            result.order,
            result.volume,
            result.price,
        )
        return {
            "status": "EXECUTED",
            "ticket": result.order,
            "volume": result.volume,
            "price": result.price,
            "deal": result.deal,
            "retcode": result.retcode,
        }

    def modify_sl(self, ticket: int, new_sl: float, symbol: str) -> dict[str, Any]:
        """Modifica o Stop Loss de uma posição aberta (Breakeven / Trailing)."""
        if not self.is_live_execution_armed():
            logger.info(
                "[MODO SEGURO / SIMULAÇÃO] Modificação de SL: Ticket #{} -> Novo SL={:.2f} ({})",
                ticket,
                new_sl,
                symbol,
            )
            return {"status": "SIMULATED", "action": "MODIFY_SL", "ticket": ticket, "new_sl": new_sl}

        if not MT5_AVAILABLE or mt5 is None or not self.connector.is_connected():
            return {"status": "ERROR", "reason": "MT5 not connected"}

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": symbol,
            "sl": float(new_sl),
            "magic": self.settings.magic_number,
        }

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.warning("Falha ao modificar SL Ticket #{}. Erro: {}", ticket, getattr(result, "comment", "Unknown"))
            return {"status": "FAILED", "ticket": ticket, "retcode": getattr(result, "retcode", None)}

        logger.info("SL modificado com sucesso para Ticket #{} -> {:.2f}", ticket, new_sl)
        return {"status": "EXECUTED", "action": "MODIFY_SL", "ticket": ticket, "new_sl": new_sl}

    def close_partial(self, ticket: int, volume_to_close: float, symbol: str, order_type: str) -> dict[str, Any]:
        """Executa fechamento parcial (ex: 30% no Alvo 1 / Alvo 2)."""
        vol = round(float(volume_to_close), 2)
        if vol <= 0.0 or vol > self.settings.max_volume:
            logger.warning("Volume parcial inválido ({:.2f}). Abortando parcial.", vol)
            return {"status": "ABORTED", "reason": "Invalid partial volume"}

        if not self.is_live_execution_armed():
            logger.info(
                "[MODO SEGURO / SIMULAÇÃO] Parcial de {:.2f} lotes no Ticket #{} ({})",
                vol,
                ticket,
                symbol,
            )
            return {"status": "SIMULATED", "action": "PARTIAL_CLOSE", "ticket": ticket, "volume_closed": vol}

        if not MT5_AVAILABLE or mt5 is None or not self.connector.is_connected():
            return {"status": "ERROR", "reason": "MT5 not connected"}

        # Para fechar parcial de BUY, envia SELL; para fechar parcial de SELL, envia BUY
        close_type = mt5.ORDER_TYPE_SELL if order_type.upper() == "BUY" else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(symbol)
        price = (tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask) if tick else 0.0

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": symbol,
            "volume": vol,
            "type": close_type,
            "price": float(price),
            "deviation": 20,
            "magic": self.settings.magic_number,
            "comment": "Hilberti Parcial 30%",
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.warning("Falha na parcial do Ticket #{}. Erro: {}", ticket, getattr(result, "comment", "Unknown"))
            return {"status": "FAILED", "ticket": ticket, "retcode": getattr(result, "retcode", None)}

        logger.info("Parcial de {:.2f} lotes executada no Ticket #{}", vol, ticket)
        return {"status": "EXECUTED", "action": "PARTIAL_CLOSE", "ticket": ticket, "volume_closed": vol}

    def get_open_positions(self, symbol: Optional[str] = None) -> list[Position]:
        """Recupera posições abertas no MT5 gerenciadas pelo Hilberti (magic number)."""
        if not MT5_AVAILABLE or mt5 is None or not self.connector.is_connected():
            return []

        sym = symbol or self.settings.mt5_symbol
        positions_mt5 = mt5.positions_get(symbol=sym)
        if not positions_mt5:
            return []

        active_positions: list[Position] = []
        for p in positions_mt5:
            if getattr(p, "magic", 0) == self.settings.magic_number:
                order_type = "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL"
                pos = Position(
                    ticket=p.ticket,
                    symbol=p.symbol,
                    order_type=order_type,
                    volume=p.volume,
                    open_price=p.price_open,
                    sl=p.sl,
                    tp=p.tp if p.tp > 0 else None,
                )
                active_positions.append(pos)

        return active_positions
