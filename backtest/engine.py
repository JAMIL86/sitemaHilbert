"""Engine de backtest — executa V26 em dados históricos sem lookahead bias (Etapa 9).

ANTI-LOOKAHEAD:
- Cada barra é processada em ordem cronológica estrita.
- A janela de features é `df.iloc[start:i]` — barra `i` NUNCA entra na própria
  janela de decisão. Só entra na janela da PRÓXIMA iteração.
- Nenhum `.shift(-n)`, `.rolling(center=True)` ou `bfill()` sobre a série.

GESTÃO DE POSIÇÃO (fonte única de verdade):
- As saídas NÃO são implementadas aqui. O engine delega a
  `V26Strategy.manage_open_trade()`, que aplica as regras do PDF: breakeven
  (+500 pts), parciais automáticas (30%/30%), trailing AGC adaptativo e saída
  por inversão de fase 180°. O PDF declara explicitamente "SEM Take Profit
  fixo" — por isso não existe TP no caminho V26, e nenhum alvo de preço é
  inventado.
- O engine só simula o preenchimento: se o preço alcançar o SL vigente, o
  trade fecha.

VARIANTES WCE (`wce_quadrant*`, ver `WCE_VARIANTS`):
- O WCE 2014 define a SAÍDA ("closed when the signal exits the quarter") e
  NADA mais: sem SL, sem TP. O modelo `wce` carrega um stop guardrail
  herdado do V26, que é de outra fonte que o artigo.
- As variantes isolam quanto do resultado depende desse stop, e medem o que
  acontece se um alvo fixo for acrescentado. `tp_points` e `sl_points`
  fixos nestas variantes NÃO são regra do PDF — todo relatório que as
  imprime diz isso explicitamente (ver `WCE_VARIANT_INFO` em report.py).
- Empate na mesma barra: se SL e TP forem ambos alcancados no MESMO M5, o
  SL vence. Sem tick intrabar não há sequencia observavel, e a leitura
  otimista inflaria o P&L de todas as variantes.

PARÂMETROS:
- Todos vêm de `settings` ou de `SignalDecision`. Nada é inventado aqui.
- `initial_balance` é explícito no construtor (padrão 10 000 USD).

TRADING:
- Simulação pura. `Executor` nunca importado, `order_send` nunca chamado,
  `dry_run` nunca alterado. Zero escrita em `shadow_log`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger

from ai.feature_engineer import FeatureEngineer
from config.settings import Settings, get_settings
from strategy.pdf_strategies import Position, V26Strategy, WCE2014Strategy

MIN_BARS = 200  # mesmo piso usado pelo dashboard para computar features


@dataclass(frozen=True)
class CostModel:
    """Custos de execução cobrados por trade fechado (round turn).

    Só `spread` é medido: vem de `mt5.symbol_info_tick()` quando o terminal
    responde (0,34 USD medido no XAUUSD-VIP em 2026-09-26), com fallback
    declarado de 0,15. `slippage_pts` é uma HIPÓTESE pessimista de 1 ponto
    por trade, não uma medição da corretora — declarada aqui para que ninguém
    a leia como dado. `commission` é contrato: a conta 1045989 é VIP, 0.

    - `spread`        preço, USD. Pago UMA vez por trade: entrada no ask e
                      saída no bid já embutem o spread inteiro.
    - `slippage_pts`  em PONTOS MT5 (1 pt = 0,01 USD no XAUUSD-VIP medido).
    - `point_size`    tamanho do ponto, USD. Medido no terminal: 0.01.
    - `commission`    USD por lote, por lado. VT Markets VIP = 0.

    `commission` NÃO é hipótese: a conta 1045989 é VIP e não cobra comissão.
    Ela é cobrada por lado (entrada + saída = 2x), como é o real.
    """
    spread: float = 0.0
    slippage_pts: float = 0.0
    point_size: float = 0.01
    commission: float = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.spread or self.slippage_pts or self.commission)

    def per_trade(self, volume: float) -> float:
        """Custo total, em USD, de um round trip de `volume` lotes."""
        slip_price = self.slippage_pts * self.point_size
        return (self.spread + slip_price) * volume * 100.0 + self.commission * volume * 2.0

    def describe(self) -> str:
        return (
            f"spread {self.spread:.4f} USD | slippage {self.slippage_pts:.0f} pt "
            f"({self.slippage_pts * self.point_size:.4f} USD) | "
            f"comissao {self.commission:.2f} USD/lote/lado"
        )


#: Custos padrão do XAUUSD-VIP. `spread` é sobrescrito por `load_spread()`
#: quando o MT5 responde; 0.15 é o fallback declarado (não medido ao vivo).
DEFAULT_COSTS = CostModel(spread=0.15, slippage_pts=1.0, point_size=0.01, commission=0.0)


#: As variantes WCE vivem em `strategy/experimental_wce.py` (bloco de
#: pesquisa, separado do backtester). Reexportadas aqui porque o `choices`
#: do argparse e `backtest/report.py` ja usavam estes nomes neste modulo.
from strategy.experimental_wce import (  # noqa: E402
    POINTS_TO_PRICE,
    WCE_VARIANTS,
    WCEQuadrantOnly,
    WCEQuadrantTP,
    WCEQuadrantTPSL,
    WCEVariant,
)


def load_spread(symbol: str = "XAUUSD-VIP") -> float:
    """Spread corrente do símbolo, ou `None` se o MT5 não responder.

    `None` e não 0.0 de propósito: zero seria afirmar que o ativo é grátis.
    O caller decide o fallback, e ele fica registrado no relatório.
    """
    try:
        import MetaTrader5 as mt5

        if not mt5.initialize():
            return None
        try:
            tick = mt5.symbol_info_tick(symbol)
            if tick is None or tick.ask <= 0.0 or tick.bid <= 0.0:
                return None
            return float(tick.ask - tick.bid)
        finally:
            mt5.shutdown()
    except Exception as exc:  # MT5 ausente/terminal fechado
        logger.debug("Spread indisponivel para {}: {}", symbol, exc)
        return None


@dataclass
class Trade:
    """Registro de um trade simulado, incluindo o resultado das parciais."""
    entry_time: object
    entry_price: float
    direction: str  # "BUY" | "SELL"
    volume: float
    sl: float
    sl_points: float
    tp: Optional[float] = None       # 0/None = sem take profit (padrao V26/WCE)
    tp_points: float = 0.0
    exit_time: Optional[object] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None  # "SL" | "TRAIL" | "END" | "QUADRANT" | "TP"
    pnl: Optional[float] = None
    costs: float = 0.0
    partials: list[dict] = field(default_factory=list)

    def close(
        self, exit_time, exit_price: float, reason: str, cost: float = 0.0
    ) -> None:
        """Fecha o trade e calcula P&L em USD.

        XAUUSD: 1.00 lot = 100 oz = 100 USD por 1.00 de variação de preço.
        Com volume em lotes: pnl = delta_preco * volume * 100. As parciais
        entram como P&L próprio e reduzem o volume restante.

        `cost` (spread + slippage + comissão) é subtraído do bruto. Sem
        custos, o PF de 1746 trades do V26 (0.929) é irreproduzível ao vivo.
        """
        self.exit_time = exit_time
        self.exit_price = exit_price
        self.exit_reason = reason
        self.costs = cost

        delta = (
            exit_price - self.entry_price
            if self.direction == "BUY"
            else self.entry_price - exit_price
        )
        final = delta * self.volume * 100.0
        self.pnl = final + sum(p["pnl"] for p in self.partials) - cost


@dataclass
class BacktestResult:
    """Resultado agregado do backtest."""
    symbol: str
    start_date: object
    end_date: object
    initial_balance: float
    final_balance: float
    trades: list[Trade] = field(default_factory=list)
    equity_curve: pd.DataFrame = field(default_factory=pd.DataFrame)
    bars_processed: int = 0
    bars_skipped: int = 0
    model: str = "v26"
    total_costs: float = 0.0
    cost_model: Optional[CostModel] = None

    def to_dict(self) -> dict:
        """Serializa para dict (consumido por metrics.py e report.py)."""
        return {
            "symbol": self.symbol,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "initial_balance": self.initial_balance,
            "final_balance": self.final_balance,
            "trades": [t.__dict__.copy() for t in self.trades],
            "equity_curve": (
                self.equity_curve["equity"]
                if not self.equity_curve.empty
                else pd.Series(dtype=float)
            ),
            "bars_processed": self.bars_processed,
            "bars_skipped": self.bars_skipped,
            "model": self.model,
            "total_costs": self.total_costs,
            "cost_model": self.cost_model,
            "cost_model_desc": self.cost_model.describe() if self.cost_model else "desligado",
        }


class BacktestEngine:
    """Engine de backtest sequencial, sem lookahead bias.

    `model` seleciona o motor: "v26" (Precision Accumulation Breakout) ou
    "wce" (Hilbert + travessia de quadrante, WCE 2014). Os dois implementam a
    mesma interface de entrada/saída, então o resto do engine é idêntico —
    é isso que torna a comparação V26 vs WCE justa (mesmos custos, mesma
    janela, mesma contabilidade).

    `costs=None` desliga a cobrança. O default é COBRAR: um backtest sem
    spread é um número que não se reproduz ao vivo.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        initial_balance: float = 10_000.0,
        model: Optional[str] = None,
        costs: Optional[CostModel] = DEFAULT_COSTS,
    ):
        self.settings = settings or get_settings()
        self.model = (model or self.settings.active_model).lower()
        # `None` para v26/wce (que tem seu proprio SL); o objeto da variante
        # para os `wce_quadrant*`, que sobrescrevem os parametros de saida.
        self.variant: Optional[WCEVariant] = WCE_VARIANTS.get(self.model)

        if self.model == "v26":
            self.strategy = V26Strategy(self.settings)
        elif self.model == "wce" or self.variant is not None:
            self.strategy = WCE2014Strategy(self.settings)
        else:
            raise ValueError(
                f"modelo desconhecido: {self.model!r} (use 'v26', 'wce' ou "
                f"uma variante: {', '.join(WCE_VARIANTS)})"
            )
        # Dispatch resolvido UMA vez, aqui. Antes, cada ponto do engine que
        # precisava saber o modelo testava `self.model == "wce"` — tres
        # compares que transformavam "adicionar um modelo" em tres edicoes
        # (Shotgun Surgery). Um terceiro modelo agora entra so nesta tabela.
        self._entry_hook = self._entry_v26 if self.model == "v26" else self._entry_wce
        self._manage_hook = self._manage_v26 if self.model == "v26" else self._manage_wce
        self.costs = costs
        self.feature_eng = FeatureEngineer()
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.open_trade: Optional[Trade] = None
        self.position: Optional[Position] = None
        self.closed_trades: list[Trade] = []
        self.total_costs = 0.0
        self._ticket = 0

    def reset(self) -> None:
        """Zera o estado entre execuções (permite reuso do engine)."""
        self.current_balance = self.initial_balance
        self.open_trade = None
        self.position = None
        self.closed_trades = []
        self.total_costs = 0.0
        self._ticket = 0

    def run(self, df: pd.DataFrame, symbol: Optional[str] = None) -> BacktestResult:
        """Executa o backtest barra a barra.

        Args:
            df: DataFrame com [time, open, high, low, close, tick_volume],
                ordenado cronologicamente.
            symbol: Símbolo negociado (default: settings.symbol_xau).

        Returns:
            BacktestResult com trades, curva de equity e contadores.
        """
        df = self._prepare(df)
        symbol = symbol or self.settings.symbol_xau

        if len(df) < MIN_BARS:
            raise ValueError(f"Dados insuficientes: {len(df)} barras (mín {MIN_BARS})")

        self.reset()
        logger.info(
            "Backtest {}: {} barras de {} a {}",
            symbol, len(df), df["time"].iloc[0], df["time"].iloc[-1],
        )

        window = min(self.settings.max_window, 1000)
        equity_rows: list[dict] = []
        skipped = 0

        for i in range(MIN_BARS, len(df)):
            bar = df.iloc[i]
            features = self._features(df, i, window)

            if features is None:
                skipped += 1
                equity_rows.append(self._equity_row(bar))
                continue

            price = float(bar["close"])

            # 1) Fecha por stop OU take profit ANTES de gerenciar: se o preço
            #    já matou a posição, a gestão da barra é irrelevante.
            #    SL é testado antes do TP de propósito: se ambos forem
            #    alcancados no MESMO M5, a sequencia real é desconhecida sem
            #    tick, e escolher o TP inflaria o P&L.
            if self._stop_hit(bar):
                self._close(bar["time"], self.open_trade.sl, self._exit_reason())
            elif self._target_hit(bar):
                self._close(bar["time"], self.open_trade.tp, "TP")
            else:
                self._manage(features, price, bar["time"])

            # 2) Abre posição apenas se não houver uma aberta.
            if self.open_trade is None:
                self._maybe_open(features, df["time"].iloc[i], symbol, price)

            equity_rows.append(self._equity_row(bar))

        if self.open_trade is not None:
            last = df.iloc[-1]
            self._close(last["time"], float(last["close"]), "END")

        result = BacktestResult(
            symbol=symbol,
            start_date=df["time"].iloc[0],
            end_date=df["time"].iloc[-1],
            initial_balance=self.initial_balance,
            final_balance=self.current_balance,
            trades=list(self.closed_trades),
            equity_curve=pd.DataFrame(equity_rows),
            bars_processed=len(df) - MIN_BARS,
            bars_skipped=skipped,
            model=self.model,
            total_costs=self.total_costs,
            cost_model=self.costs,
        )
        logger.info(
            "Concluído: {} trades, saldo {} -> {}",
            len(self.closed_trades), self.initial_balance, self.current_balance,
        )
        return result

    # --- features e janela -------------------------------------------------

    def _features(self, df: pd.DataFrame, i: int, window: int):
        """Features da barra i-1 (janela SOMENTE do passado)."""
        history = df.iloc[max(0, i - window):i]
        if len(history) < MIN_BARS:
            return None
        try:
            return self.feature_eng.compute(history)
        except Exception as exc:  # janela degenerada (ex.: pré-abertura plana)
            logger.debug("Features indisponíveis: {}", exc)
            return None

    def _entry_decision(self, features, symbol: str, price: float):
        """Entrada do modelo ativo, normalizada para um `SignalDecision`."""
        return self._entry_hook(features, symbol, price)

    def _entry_wce(self, features, symbol: str, price: float):
        """WCE 2014 — entrada por travessia de quadrante.

        O artigo não emite SL (`sl_points == 0`): não tem stop. O guardrail de
        projeto entra AQUI, marcado com `guardrail_projeto=True`, para que
        nenhum relatório possa apresentá-lo como regra do PDF.

        Numa variante (`wce_quadrant*`) os parametros de saida sao os da
        variante, NAO o guardrail ATR: `sl_points` e `tp_points` sao fixos e
        vem do `WCEVariant`, e um zero significa "sem stop / sem alvo" — o
        que a variante A e B pedem explicitamente.
        """
        decision = self.strategy.generate_signal(features)
        if decision.signal in ("BUY", "SELL"):
            variant = self.variant
            if variant is not None:
                # `*_points` das variantes sao PONTOS (1 pt = 0,01 USD) e o
                # preco do alvo/stop precisa da conversao. Sem ela, "TP de
                # 50 pontos" viraria alvo a +50,00 USD.
                sl_points = variant.sl_points if variant.use_sl else 0.0
                sl_dist = sl_points * POINTS_TO_PRICE
                sl = (
                    price - sl_dist if decision.signal == "BUY"
                    else price + sl_dist
                ) if sl_dist > 0 else 0.0
                tp_points = variant.tp_points if variant.use_tp else 0.0
                tp_dist = tp_points * POINTS_TO_PRICE
                tp = (
                    price + tp_dist if decision.signal == "BUY"
                    else price - tp_dist
                ) if tp_dist > 0 else 0.0
            else:
                sl_points, sl = self.strategy.initial_sl(
                    current_price=price,
                    atr14=float(features.atr14[-1]),
                    period_smooth=float(features.period_smooth[-1]),
                    direction=decision.signal,
                )
                tp_points, tp = 0.0, 0.0
            decision.sl_points = sl_points
            decision.initial_sl = sl
            decision.tp_points = tp_points
            decision.tp = tp
            decision.price = price
            decision.symbol = symbol
        return decision

    def _entry_v26(self, features, symbol: str, price: float):
        """V26 — o motor ja emite SL, preco e simbolo na propria decisao."""
        return self.strategy.signal(
            features, symbol=symbol, current_price=price, current_spread=0.0
        )

        return self.strategy.signal(
            features, symbol=symbol, current_price=price, current_spread=0.0
        )

    def _maybe_open(self, features, when, symbol: str, price: float) -> None:
        """Abre trade quando o modelo ativo emite sinal e não há posição aberta.

        Recebe as MESMAS features já computadas para a barra atual — a janela
        é o passado para as duas decisões, então recalcular só dobraria o
        custo do backtest sem mudar o resultado.

        A guarda `sl_points <= 0` aborta a entrada quando o motor nao emite
        stop. Ela existe para o V26, cujo SL e obrigatorio. Numa variante sem
        SL (`wce_quadrant`, `wce_quadrant_tp`) abortar aqui produziria ZERO
        trades — o oposto do que a variante mede — entao a guarda so vale
        para quem precisa de stop. Onde `sl == 0.0` significa "sem stop".
        """
        decision = self._entry_decision(features, symbol, price)
        if decision is None or decision.signal not in ("BUY", "SELL"):
            return
        if decision.sl_points <= 0 and self.variant is None:
            return

        sl_points = float(decision.sl_points)
        if sl_points > 0:
            # `initial_sl` manda quando o motor ja calculou o preco do stop; o
            # `or` abaixo so refaz o preco a partir dos pontos quando ele nao
            # veio. A guarda `sl_points > 0` e obrigatoria antes do `or`: sem
            # ela, uma variante sem SL cairia no lado direito da conta e
            # receberia um stop no PRECO (atingido na mesma barra).
            sl = float(decision.initial_sl) or (
                price - sl_points
                if decision.signal == "BUY"
                else price + sl_points
            )
        else:
            sl = 0.0  # 0.0 = sem stop, e nao "stop no preco"
        tp = float(getattr(decision, "tp", 0.0) or 0.0)

        self._ticket += 1
        self.open_trade = Trade(
            entry_time=when,
            entry_price=price,
            direction=decision.signal,
            volume=self.settings.min_volume,
            sl=sl,
            sl_points=sl_points,
            tp=tp or None,
            tp_points=float(getattr(decision, "tp_points", 0.0) or 0.0),
        )
        # `entry_phase` é lido pelo V26 para a saída por inversão de fase.
        self.position = Position(
            ticket=self._ticket,
            symbol=symbol,
            order_type=decision.signal,
            volume=self.settings.min_volume,
            open_price=price,
            sl=sl,
            tp=tp or None,
            open_time=when,
            entry_phase=float(features.phase[-1]),
        )
        logger.debug("Aberto {} @ {} SL {} TP {}", decision.signal, price, sl, tp)

    # --- gestão e saída ----------------------------------------------------

    def _stop_hit(self, bar) -> bool:
        """O preço da barra alcançou o SL vigente?

        `sl == 0.0` significa "sem stop" (variantes WCE sem guardrail) e
        NUNCA pode ser comparado com o preço: num XAU a 3 000, `low <= 0.0` é
        falso, mas a guarda explicita evita depender desse acidente — e numa
        variante cujo sl é 0 o trade precisa atravessar o ciclo do Hilbert.
        """
        if self.open_trade is None or self.open_trade.sl <= 0.0:
            return False
        low, high = float(bar["low"]), float(bar["high"])
        return (
            low <= self.open_trade.sl
            if self.open_trade.direction == "BUY"
            else high >= self.open_trade.sl
        )

    def _target_hit(self, bar) -> bool:
        """O preço da barra alcançou o TP vigente? (`tp is None` = sem alvo.)"""
        if self.open_trade is None or not self.open_trade.tp:
            return False
        low, high = float(bar["low"]), float(bar["high"])
        return (
            high >= self.open_trade.tp
            if self.open_trade.direction == "BUY"
            else low <= self.open_trade.tp
        )

    def _exit_reason(self) -> str:
        """Distingue stop inicial de stop movido (trailing/breakeven).

        Reportar tudo como "SL" esconderia que a maior parte das saídas
        lucrativas veio do trailing adaptativo do V26, não do stop original.
        """
        if self.open_trade is None:
            return "SL"
        moved = (
            self.open_trade.sl > self.open_trade.entry_price
            if self.open_trade.direction == "BUY"
            else self.open_trade.sl < self.open_trade.entry_price
        )
        return "TRAIL" if moved else "SL"

    def _manage(self, features, price: float, when) -> None:
        """Aplica a regra de SAÍDA do modelo ativo (dispatch já resolvido)."""
        if self.open_trade is None or self.position is None:
            return
        self._manage_hook(features, price, when)

    def _manage_wce(self, features, price: float, when) -> None:
        """WCE 2014: literal do PDF — "closed when the signal exits the quarter".

        Long sai ao deixar Q1, short ao deixar Q3. Sem trailing, sem breakeven,
        sem parcial: o artigo não escreve nenhum deles.
        """
        quad = self.strategy.quadrant(
            float(features.i1[-1]), float(features.q1[-1])
        )
        if self.strategy.should_exit(quad, self.open_trade.direction):
            self._close(when, price, "QUADRANT")

    def _manage_v26(self, features, price: float, when) -> None:
        """V26: trailing, break-even e parciais, conforme o PDF V26 §07."""
        action = self.strategy.manage_open_trade(self.position, features, price)
        kind = getattr(action, "action", None)

        if kind == "MODIFY_SL" and action.new_sl is not None:
            # Trailing é MONOTÔNICO: o SL nunca afasta do preço.
            if self.position.order_type == "BUY" and action.new_sl > self.open_trade.sl:
                self.open_trade.sl = action.new_sl
                self.position.sl = action.new_sl
            elif self.position.order_type == "SELL":
                worse = self.open_trade.sl == 0.0 or action.new_sl < self.open_trade.sl
                if worse and action.new_sl > 0.0:
                    self.open_trade.sl = action.new_sl
                    self.position.sl = action.new_sl

        elif kind == "PARTIAL_CLOSE" and action.volume_to_close > 0:
            self._partial(when, price, action)

    def _partial(self, when, price: float, action) -> None:
        """Fecha parte do volume e realiza o P&L correspondente."""
        volume = min(action.volume_to_close, self.open_trade.volume)
        if volume <= 0:
            return
        delta = (
            price - self.open_trade.entry_price
            if self.open_trade.direction == "BUY"
            else self.open_trade.entry_price - price
        )
        pnl = delta * volume * 100.0

        self.current_balance += pnl
        self.open_trade.volume = round(self.open_trade.volume - volume, 4)
        self.open_trade.partials.append(
            {
                "time": when,
                "volume": volume,
                "price": price,
                "pnl": pnl,
                "reason": action.reason,
            }
        )
        if self.position is not None:
            self.position.volume = self.open_trade.volume
        logger.debug("Parcial {:.2f} @ {} P&L {:.2f}", volume, price, pnl)

    def _close(self, when, price: float, reason: str) -> None:
        if self.open_trade is None:
            return
        cost = (
            self.costs.per_trade(self.open_trade.volume)
            if self.costs is not None and self.costs.enabled
            else 0.0
        )
        self.total_costs += cost
        if self.open_trade.volume > 0:
            self.open_trade.close(when, price, reason, cost=cost)
            self.current_balance += self.open_trade.pnl or 0.0
        else:
            # Todo o volume já saiu nas parciais.
            self.open_trade.exit_time = when
            self.open_trade.exit_price = price
            self.open_trade.exit_reason = reason
            self.open_trade.pnl = sum(p["pnl"] for p in self.open_trade.partials)
        self.closed_trades.append(self.open_trade)
        logger.debug("Fechado {} P&L {:.2f}", reason, self.open_trade.pnl or 0.0)
        self.open_trade = None
        self.position = None

    # --- curva de equity ---------------------------------------------------

    def _equity_row(self, bar) -> dict:
        """Balance + P&L flutuante da posição aberta."""
        floating = 0.0
        if self.open_trade is not None:
            price = float(bar["close"])
            delta = (
                price - self.open_trade.entry_price
                if self.open_trade.direction == "BUY"
                else self.open_trade.entry_price - price
            )
            floating = delta * self.open_trade.volume * 100.0
        return {
            "time": bar["time"],
            "balance": self.current_balance,
            "equity": self.current_balance + floating,
        }

    @staticmethod
    def _prepare(df: pd.DataFrame) -> pd.DataFrame:
        """Normaliza tipos e rejeita séries fora de ordem."""
        out = df.copy()
        out["time"] = pd.to_datetime(out["time"])
        if not out["time"].is_monotonic_increasing:
            # Falhar expõe o dado ruim; ordenar automaticamente o esconderia.
            raise ValueError("Dados fora de ordem cronológica.")
        for col in ("open", "high", "low", "close"):
            out[col] = out[col].astype("float64")
        return out.reset_index(drop=True)


def main() -> int:
    """CLI: roda o backtest sobre os dados baixados e grava o relatório."""
    import argparse

    from backtest.downloader import HistoricalDataDownloader
    from backtest.metrics import compute_metrics
    from backtest.report import save_report

    parser = argparse.ArgumentParser(description="Backtest V26/WCE sobre historico do MT5.")
    parser.add_argument("--data", default=None, help="CSV local; sem ele usa backtest/data/*.csv")
    parser.add_argument("--symbol", default="XAUUSD-VIP")
    parser.add_argument("--balance", type=float, default=10_000.0)
    parser.add_argument("--limit", type=int, default=0, help="Usa apenas as N barras mais recentes")
    parser.add_argument("--model", default=None,
                        choices=["v26", "wce", *WCE_VARIANTS],
                        help="Modelo; sem ele usa settings.active_model. "
                             "As variantes wce_quadrant* removem o guardrail "
                             "de SL e/ou acrescentam TP/SL fixos — ver "
                             "WCE_VARIANTS no engine.py")
    parser.add_argument("--with-costs", dest="with_costs", action=argparse.BooleanOptionalAction,
                        default=True, help="Cobrar spread+slippage+comissao (default: sim)")
    parser.add_argument("--spread", type=float, default=None,
                        help="Spread em USD; sem ele le mt5.symbol_info_tick()")
    args = parser.parse_args()

    downloader = HistoricalDataDownloader()
    if args.data:
        df = downloader.load(Path(args.data))
    else:
        files = sorted(downloader.data_dir.glob(f"{args.symbol}_M5_*.csv"))
        if not files:
            logger.error("Nenhum CSV em {}. Rode antes: python -m backtest.downloader", downloader.data_dir)
            return 1
        df = downloader.load(files[-1])
    if args.limit:
        df = df.iloc[-args.limit:]

    # Custos: default LIGADO. Medido no terminal quando disponivel.
    costs = None
    if args.with_costs:
        spread = args.spread if args.spread is not None else load_spread(args.symbol)
        origem = "MT5" if spread is not None and args.spread is None else "fallback"
        if spread is None:
            spread = DEFAULT_COSTS.spread
        costs = CostModel(
            spread=spread,
            slippage_pts=DEFAULT_COSTS.slippage_pts,
            point_size=DEFAULT_COSTS.point_size,
            commission=DEFAULT_COSTS.commission,
        )
        print(f"Custos       {costs.describe()} [spread {origem}]")
    else:
        print("Custos       DESLIGADOS (--no-with-costs) — resultado NAO reproduzivel ao vivo")

    engine = BacktestEngine(
        initial_balance=args.balance, model=args.model, costs=costs
    )
    result = engine.run(df, symbol=args.symbol)
    metrics = compute_metrics(result.to_dict())

    print(f"Modelo       {result.model}")
    if engine.variant is not None:
        print(f"Variante     {engine.variant.description}")
    print(f"Periodo      {result.start_date} a {result.end_date}")
    print(f"Barras       {len(df)} (processadas {result.bars_processed}, puladas {result.bars_skipped})")
    print(f"Trades       {metrics['total_trades']}")
    print(f"Win rate     {metrics['win_rate_pct']:.1f}%")
    print(f"Profit fact  {metrics['profit_factor']:.3f}")
    print(f"P&L          {metrics['total_pnl']:.2f} USD  ({result.initial_balance:.2f} -> {result.final_balance:.2f})")
    print(f"Max DD       {metrics['max_drawdown_pct']:.2f}%")
    print(f"Sharpe       {metrics['sharpe_ratio']:.3f}")

    print(f"Custo total  {result.total_costs:.2f} USD "
          f"({result.total_costs / max(1, metrics['total_trades']):.4f} USD/trade)")

    sls = [t.sl_points for t in result.trades if t.sl_points > 0]
    if sls:
        print(f"SL medio     {sum(sls) / len(sls):.2f} pontos  (min {min(sls):.2f}, max {max(sls):.2f})")
    else:
        print("SL medio     n/a (variante sem stop)")
    reasons: dict[str, int] = {}
    for t in result.trades:
        reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1
    print(f"Saidas       {reasons}")

    payload = result.to_dict()
    sufixo = "custos" if args.with_costs else "sem_custos"
    # As variantes WCE sao um conjunto de pesquisa que se compara ENTRE SI
    # (mesmo periodo, mesmos custos, uma variable por vez). Espalhar cada uma
    # em `wce_quadrant_custos/`, `wce_quadrant_tp_custos/`... esconderia essa
    # comparacao; vao todas para a mesma pasta, que ja traz o modelo no nome
    # do arquivo.
    raiz = Path("backtest/reports/wce_variants" if engine.variant else "backtest/reports")
    out_dir = raiz if engine.variant else raiz / f"{result.model}_{sufixo}"
    path = save_report(payload, output_dir=out_dir)
    print(f"Relatorio    {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
