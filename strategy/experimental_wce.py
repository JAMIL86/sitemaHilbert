"""Variantes experimentais do WCE 2014 — bloco de PESQUISA, nao de produto.

Por que este arquivo existe separado de `backtest/engine.py`: o engine tem
`wce_quadrant` no `choices` do argparse e importa estes nomes. Mover as
definicoes para ca e reexportar mantem os dois importadores funcionando
enquanto tira do engine a lista de parametros de pesquisa — numeros que
nao vem do artigo e que nao deveriam se parecer com parte do backtester.

NAO entra em producao. `dry_run` e `LIVE_TRADING` nao importam este
modulo, e nao devem: o WCE 2014 nao define stop nem take profit, e estas
variantes acrescentam os dois.

Hierarquia de uma-variavel-por-vez. O modelo `wce` (em `pdf_strategies.py`)
= WCE literal + stop guardrail do V26. Cada variante remove ou acrescenta
UM aspecto, para que a diferenca de resultado seja atribuivel a aquele
aspecto e nao a uma combinacao:

  wce_quadrant        remove o guardrail -> o que resta e o artigo puro.
  wce_quadrant_tp     acrescenta TP fixo, ainda sem SL.
  wce_quadrant_tp_sl  acrescenta TP E um SL FIXO (nao o ATR do V26, para nao
                      variar por barra e nao confundir o efeito do stop com
                      o efeito da formula ATR).

Sobre a UNIDADE de `sl_points`/`tp_points` — leia antes de mexer:

Sao PONTOS de preco (1 pt = 0,01 USD no XAUUSD-VIP) e sao multiplicados por
`POINTS_TO_PRICE` antes de virar preco. Isto nao e cosmetico.
`V26Strategy.calculate_initial_sl` faz `current_price - sl_points` SEM
converter (medido: `sl_points` mediano 10,09 para uma distancia real
entrada->stop de 3,62 USD), entao o `sl_points` do V26 e um delta em USD
apesar do nome — a unidade "pontos" e uma heranca que os dois lados
carregam sem conversao.

Um TP escrito como 50 sem a conversao vira alvo a +50,00 USD: ~11x a
amplitude mediana de uma barra M5 (4,34 USD), e por isso NENHUM TP era
atingido. O sintoma e indistinguivel de "alvo geometricamente distante", e
foi diagnosticado como tal por duas rodadas antes de virar bug de unidade.
Ver `docs/handoff.md` §14.6.
"""

from __future__ import annotations

from dataclasses import dataclass


#: 1 ponto de preco do XAUUSD-VIP = 0,01 USD. Conversao de `*_points` -> preco.
POINTS_TO_PRICE = 0.01


@dataclass(frozen=True)
class WCEVariant:
    """Uma variante do WCE 2014 differindo do modelo `wce` em UM aspecto.

    `use_sl`/`use_tp` sao interruptores explicitos e nao Sao inferidos do
    valor: um `sl_points = 0.0` seria ambiguo entre "stop no preco" e "sem
    stop", e a engine precisa distinguir os dois sem ambiguidade.
    """

    name: str
    use_sl: bool
    use_tp: bool
    sl_points: float = 0.0
    tp_points: float = 0.0
    description: str = ""


#: Variantes WCE disponiveis via `--model`. Ver `WCEVariant` para a semantica.
WCE_VARIANTS: dict[str, WCEVariant] = {
    "wce_quadrant": WCEVariant(
        name="wce_quadrant",
        use_sl=False,
        use_tp=False,
        description="WCE 2014 literal: entra por travessia de quadrante e sai "
                    "ao sair do quadrante. SEM stop, SEM take profit — o "
                    "artigo nao escreve nenhum dos dois.",
    ),
    "wce_quadrant_tp": WCEVariant(
        name="wce_quadrant_tp",
        use_sl=False,
        use_tp=True,
        tp_points=50.0,
        description="WCE 2014 + take profit fixo de 50 pontos (0,50 USD). O PDF "
                    "nao define TP: este numero e parametro de pesquisa, nao "
                    "regra do artigo. A primeira medicao usou 500 e produziu "
                    "ZERO TPs, mas a causa nao era geometria do mercado: os "
                    "`*_points` estavam sendo somados ao preco como se "
                    "fossem USD, colocando o alvo a +50,00 USD. Ver "
                    "docs/handoff.md §14.6.",
    ),
    "wce_quadrant_tp_sl": WCEVariant(
        name="wce_quadrant_tp_sl",
        use_sl=True,
        use_tp=True,
        sl_points=250.0,
        tp_points=50.0,
        description="WCE 2014 + take profit de 50 pontos (0,50 USD) + stop "
                    "fixo de 250 pontos (2,50 USD). Nem o TP nem o SL vem do "
                    "PDF: sao parametros de pesquisa, e o SL e FIXO para nao se "
                    "confundir com o stop ATR do V26.",
    ),
}


#: Aliases com o nome que a tarefa usou. O `WCEQuadrant*` foi pedido
#: explicitamente; `WCEQuadrantOnly` e o mesmo objeto de `wce_quadrant` (o
#: artigo puro, sem TP e sem SL), guardado porque o nome "Only" diz em uma
#: palavra o que a variante A precisa de tres flags para expressar.
WCEQuadrantOnly = WCE_VARIANTS["wce_quadrant"]
WCEQuadrantTP = WCE_VARIANTS["wce_quadrant_tp"]
WCEQuadrantTPSL = WCE_VARIANTS["wce_quadrant_tp_sl"]


def resolve(name: str) -> WCEVariant | None:
    """Variante pelo nome do `--model`, ou None para o modelo `wce`."""
    return WCE_VARIANTS.get(name)
