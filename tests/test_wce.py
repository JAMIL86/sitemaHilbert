"""Testes do WCE 2014 como modelo ATIVO (Etapa 9, FASE 2).

Seams testados (acordados na FASE 2 da spec):
- `WCE2014Strategy.generate_signal`  -> decisao de entrada por TRANSICAO de quadrante
- `WCE2014Strategy.should_exit`      -> regra de saida do PDF
- ISOM                               -> desativado com warning (dx ausente no PDF)
- Integridade do V26                 -> V26 nao pode ter sido removido

Nenhum numero de regra foi inventado: as tres primeiras pecas vem de citacao
literal em `docs/modelos_extraidos.md`; o mapeamento algebrico dos quadrantes
vem do V26 p.3 (decisao do responsavel, 2026-09-26).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from strategy.pdf_strategies import Quadrant, WCE2014Strategy

# Digest da AST das classes que a ativação do WCE NÃO pode tocar.
_V26_DIGEST = "a80023b74c5fff00938914098a7a9c4260f9497e5b5e9052f0a761d233f94b7c"
_POSITION_DIGEST = "f566ef8b854dafd246a1eacc5acd22dfff1c90061bccb55a2baef17475bf3fe9"


def _features(i_pairs: list[tuple[float, float]]):
    """DSPFeatures minimo: so i1/q1 sao lidos pelo WCE."""
    from ai.feature_engineer import DSPFeatures

    n = len(i_pairs)
    zero = np.zeros(n)
    i1 = np.array([p[0] for p in i_pairs])
    q1 = np.array([p[1] for p in i_pairs])
    return DSPFeatures(
        close_smooth=i1.copy(), detrender=zero.copy(), i1=i1, q1=q1,
        phase=zero.copy(), amplitude=zero.copy(), period_raw=zero.copy(),
        period_smooth=np.full(n, 10.0), roofing=zero.copy(), eit=zero.copy(),
        eit_flat=zero.copy(), ebsw_sine=zero.copy(), ebsw_leadsine=zero.copy(),
        cycle_mode=zero.copy(), amplitude_norm=zero.copy(), atr14=np.full(n, 5.0),
    )


def _df(i_pairs: list[tuple[float, float]]) -> pd.DataFrame:
    """DataFrame no formato pedido pela spec (`generate_signal(df)`)."""
    return pd.DataFrame(
        {"i1": [p[0] for p in i_pairs], "q1": [p[1] for p in i_pairs]}
    )


# --- 1. Q4 -> Q1 = BUY ------------------------------------------------------
# Q4 = {I>0, Q<0}, Q1 = {I>0, Q>0}. O PDF fala em CRUZAMENTO de quadrante,
# nao em nivel: entrar so quando o sinal ATRAVESSA Q4 de dentro para Q1.

def test_buy_only_on_the_q4_to_q1_transition():
    wce = WCE2014Strategy()
    # Penultima barra em Q4 (+1, -1), ultima em Q1 (+1, +1).
    features = _features([(1.0, -1.0), (1.0, 1.0)])
    assert wce.generate_signal(features).signal == "BUY"


def test_buy_is_not_emitted_while_already_settled_inside_q1():
    """Estar em Q1 sem ter vindo de Q4 nao e entrada — o PDF diz 'crosses'."""
    wce = WCE2014Strategy()
    features = _features([(1.0, 1.0), (1.0, 1.0)])
    assert wce.generate_signal(features).signal == "HOLD"


def test_buy_crossing_must_come_from_q4_not_q2():
    """Q2 -> Q1 (+I, Q>0 nos dois) e uma virada de I, nao a entrada do PDF."""
    wce = WCE2014Strategy()
    features = _features([(-1.0, 1.0), (1.0, 1.0)])
    assert wce.generate_signal(features).signal == "HOLD"


# --- 2. Q2 -> Q3 = SELL -----------------------------------------------------

def test_sell_on_the_q2_to_q3_transition():
    wce = WCE2014Strategy()
    features = _features([(-1.0, 1.0), (-1.0, -1.0)])
    assert wce.generate_signal(features).signal == "SELL"


def test_sell_is_not_emitted_while_already_inside_q3():
    wce = WCE2014Strategy()
    features = _features([(-1.0, -1.0), (-1.0, -1.0)])
    assert wce.generate_signal(features).signal == "HOLD"


def test_generate_signal_accepts_a_dataframe_as_well_as_features():
    """A spec pede `generate_signal(df)`; o engine tem DSPFeatures. Ambas as
    formas precisam dar a MESMA decisao, senao o modelo diverge entre teste
    e producao."""
    wce = WCE2014Strategy()
    pairs = [(1.0, -1.0), (1.0, 1.0)]
    assert wce.generate_signal(_df(pairs)).signal == wce.generate_signal(_features(pairs)).signal


# --- 3. should_exit: regra literal do PDF -----------------------------------
# "…closed when the signal exits the quarter." Long sai ao deixar Q1; short ao
# deixar Q3.

def test_long_exits_when_leaving_q1_and_holds_while_inside():
    wce = WCE2014Strategy()
    assert wce.should_exit("Q1", "BUY") is False
    for quad in ("Q2", "Q3", "Q4"):
        assert wce.should_exit(quad, "BUY") is True


def test_short_exits_when_leaving_q3_and_holds_while_inside():
    wce = WCE2014Strategy()
    assert wce.should_exit("Q3", "SELL") is False
    for quad in ("Q1", "Q2", "Q4"):
        assert wce.should_exit(quad, "SELL") is True


def test_quadrant_classification_covers_the_whole_iq_plane():
    wce = WCE2014Strategy()
    assert wce.quadrant(1.0, 1.0) is Quadrant.Q1
    assert wce.quadrant(-1.0, 1.0) is Quadrant.Q2
    assert wce.quadrant(-1.0, -1.0) is Quadrant.Q3
    assert wce.quadrant(1.0, -1.0) is Quadrant.Q4
    # Eixo exato: sem sinal o quadrante e indefinido, e um "Q1" inventado
    # dispararia entrada fora do PDF. E um valor do dominio (AXIS), nao None.
    assert wce.quadrant(0.0, 1.0) is Quadrant.AXIS
    assert wce.quadrant(1.0, 0.0) is Quadrant.AXIS
    assert wce.quadrant(0.0, 0.0) is Quadrant.AXIS


def test_axis_exits_an_open_position_because_it_is_not_the_origin_quadrant():
    """Sair do quadrante para o eixo E sair dele (o artigo: "exits the quarter").

    O eixo nao e um quadrante, portanto nao pode ser o quadrante de origem.
    """
    wce = WCE2014Strategy()
    assert wce.should_exit(Quadrant.AXIS, "BUY") is True
    assert wce.should_exit(Quadrant.AXIS, "SELL") is True


# --- 4. ISOM: dx nao existe no PDF -> desativado, com warning ---------------

def test_isom_is_disabled_with_a_warning_when_dx_is_undefined():
    """O PDF nomeia `dx(%)` mas nao da o valor. Chutar um threshold seria
    inventar regra; o comportamento correto e desativar e avisar."""
    from loguru import logger as _logger

    sink: list[str] = []
    handler_id = _logger.add(lambda m: sink.append(m), level="WARNING")
    try:
        WCE2014Strategy().isom_allows(dx_percent=None)
    finally:
        _logger.remove(handler_id)

    assert any("ISOM" in m for m in sink), f"esperado WARNING de ISOM, veio {sink}"


def test_isom_does_not_filter_any_bar_when_dx_is_undefined():
    """Desativado tem que ser INOCENTE: nunca pode derrubar uma entrada."""
    wce = WCE2014Strategy()
    assert wce.isom_allows(dx_percent=None) is True


# --- 5. SL guardrail: vem do V26, NAO do PDF --------------------------------

def test_initial_sl_is_the_v26_formula_and_flagged_as_project_guardrail():
    """`guardrail_projeto=True` existe para que ninguem leia o stop como regra
    do artigo WCE — o PDF nao tem SL nenhum (decisoes_tecnicas.md §7.3)."""
    from strategy.pdf_strategies import V26Strategy

    wce = WCE2014Strategy()
    sl_points, sl = wce.initial_sl(
        current_price=2000.0, atr14=5.0, period_smooth=20.0, direction="BUY"
    )
    # calculate_initial_sl do V26: atr14 * min(2.0, 20/10) = 5 * 2.0 = 10
    assert sl_points == pytest.approx(10.0)
    assert sl == pytest.approx(1990.0)
    assert wce.SL_GUARDRAIL_PROJETO is True

    # Mesma formula, nova fonte de verdade: o V26.
    v26_points, v26_sl = V26Strategy(wce.settings).calculate_initial_sl(
        2000.0, 5.0, 20.0, "BUY"
    )
    assert (sl_points, sl) == pytest.approx((v26_points, v26_sl))

    decision = wce.generate_signal(_features([(1.0, -1.0), (1.0, 1.0)]))
    assert decision.metadata["guardrail_projeto"] is True


# --- 6. V26 intacto ---------------------------------------------------------

def _class_source(source: str, name: str) -> str:
    """Texto REAL das linhas de uma classe, do `class` ate a proxima classe.

    Hash do arquivo inteiro nao serve: ativar o WCE exige editar `pdf_strategies.py`
    e o hash quebraria a cada mudanca legitima no outro motor. Hash da AST
    tambem nao — `ast.dump` perde comentarios e docstrings, que sao justamente
    onde mora a distincao "isto e regra do PDF" vs "isto e guardrail".

    Este recorte pega o codigo-fonte como escrito: uma formula de SL alterada,
    um no trocado, um comentario removido — tudo muda o hash. Uma barra em
    branco ou um comentario acima da classe, nao.

    O fim do recorte e a PROXIMA classe de nivel superior (coluna 0), nao a
    proxima linha comecada por `class `: o banner de secao que antecede cada
    classe contem o proprio nome do motor ("MOTOR WCE 2014 ... (ACTIVE)"), e
    parar ali faria o VCE mudar de hash cada vez que o rotulo do WCE mudasse.
    """
    lines = source.splitlines()
    inicio = proxima = None
    for idx, line in enumerate(lines):
        if inicio is None and line.startswith(f"class {name}"):
            inicio = idx
        elif inicio is not None and re.match(r"^class \w", line):
            proxima = idx
            break
    if inicio is None:
        raise AssertionError(f"classe {name} nao existe mais — V26 foi removido?")
    return "\n".join(lines[inicio : proxima if proxima is not None else len(lines)])


def _class_digest(source: str, name: str) -> str:
    """SHA-256 do codigo-fonte real da classe."""
    return hashlib.sha256(_class_source(source, name).encode("utf-8")).hexdigest()


def test_v26_is_still_importable_and_unchanged_by_the_wce_activation():
    """Regra da spec: V26 NAO e removido, fica disponivel para comparacao.

    O hash e do CODIGO-FONTE REAL da classe (ver `_class_source`), nao da AST.
    """
    from strategy.pdf_strategies import V26Strategy, StrategyRouter

    assert V26Strategy is not None
    assert StrategyRouter is not None
    assert callable(V26Strategy.signal)
    assert callable(V26Strategy.manage_open_trade)

    # Caminho ancorado no pacote: um teste nao deve depender do CWD, senao
    # falha (ou passa) conforme de onde o pytest foi chamado.
    source = (
        Path(__file__).resolve().parents[1] / "strategy" / "pdf_strategies.py"
    ).read_text(encoding="utf-8")
    assert _class_digest(source, "V26Strategy") == _V26_DIGEST, (
        "V26Strategy mudou na ativacao do WCE. Se a mudanca e intencional, "
        "atualize _V26_DIGEST e justifique no handoff."
    )
    assert _class_digest(source, "Position") == _POSITION_DIGEST


def test_wce_activation_did_not_touch_dry_run_or_live_trading():
    """A tripla trava de seguranca continua DESARMADA com o WCE ativo.

    Nao basta afirmar `Settings().dry_run is True`: o que importa e que a
    porta de execucao real esteja fechada, verificada pelo mesmo metodo que
    o `Executor` usa no loop de trading. Um default True que o Executor
    ignorasse deixaria o teste verde com o live armado.
    """
    from config.settings import get_settings
    from core.executor import Executor

    s = get_settings()
    assert s.dry_run is True
    assert s.live_trading is False
    assert s.active_model == "v26"

    # O metodo real de guarda, no mesmo objeto de settings que o loop usa.
    assert Executor(settings=s).is_live_execution_armed() is False

    # E o oposto e verdade: se as duas flags virassem, a trava abriria. Sem
    # isto o teste acima passaria tambem num Settings que ignorasse dry_run.
    armado = s.model_copy(update={"dry_run": False, "live_trading": True})
    assert Executor(settings=armado).is_live_execution_armed() is True


def test_v26_is_primary_and_wce_stays_reachable():
    """O V26 voltou a ser oprimario; o WCE fica acessivel, nunca removido."""

    from config.settings import get_settings
    assert get_settings().active_model == "v26"
    from strategy.pdf_strategies import StrategyRouter
    from strategy.pdf_strategies import StrategyRouter

    router = StrategyRouter()
    assert router.v26 is not None and router.wce is not None

    # Alcancar o V26 nao pode custar uma decisao do WCE. O router tem de
    # continuar emitindo o sinal dos DOIS motores numa chamada so.
    feats = _features([(1.0, -1.0), (1.0, 1.0)])  # travessia Q4 -> Q1
    decisao = router.decide(feats, symbol="XAUUSD-VIP", current_price=2000.0)
    assert decisao["shadow_wce"] == "BUY", (
        "com WCE ativo, o router ainda precisa publicar o sinal do WCE"
    )


def test_should_exit_rejects_an_unknown_side_instead_of_never_exiting():
    """`return False` para side invalido significaria posicao aberta para
    sempre — silenciosamente. Falhar e o unico comportamento seguro."""
    with pytest.raises(ValueError, match="side invalido"):
        WCE2014Strategy().should_exit("Q1", "HOLD")


def test_active_model_governs_execution_in_the_live_path():
    """`active_model` precisa VALER no caminho vivo, não só no backtest.

    Defeito encontrado em 2026-09-26: o `decide()` executava o V26 fixo e
    ignorava `active_model`. Com o default virado para "wce", isso produzia
    um sistema que dizia executar o WCE e executava o V26.

    Este teste fixa o defeito nos DOIS lados: o default v26, e o fato de
    que apontar para "wce" troca mesmo o sinal que sai.
    """
    from config.settings import get_settings
    from strategy.pdf_strategies import StrategyRouter

    # Penultima barra em Q4, ultima em Q1 -> o WCE diz BUY.
    features = _features([(1.0, -1.0), (1.0, 1.0)])
    router = StrategyRouter()

    assert get_settings().active_model == "v26"
    out_v26 = router.decide(features=features, symbol="XAUUSD", current_price=2400.0)
    assert out_v26["modelo_ativo"] == "v26"

    monkey = router.settings.model_copy(update={"active_model": "wce"})
    router_wce = StrategyRouter(monkey)
    out_wce = router_wce.decide(features=features, symbol="XAUUSD", current_price=2400.0)

    assert out_wce["modelo_ativo"] == "wce"
    assert out_wce["signal"] == "BUY"
    assert out_wce["execute"] is True
    # O outro modelo continua sendo calculado e reportado — nenhum é removido.
    assert "shadow_wce" in out_wce


def test_wce_is_backtest_only_again_until_the_review_gates_are_met():
    """O WCE foi rebaixado de primário em 2026-09-26.

    Motivo: o `edge-strategy-reviewer` mostrou que o WCE medido é o artigo
    MENOS o ISOM usado como ENTRADA do Hilbert (nao como filtro — ver
    decisoes_tecnicas.md §9.6), mais um stop de outra fonte. O PDF report PF
    1.0, ou seja, break-even segundo os proprios autores. Promover a
    primário um hibrido com edge nao medido nao se sustenta.
    """
    from config.settings import get_settings
    from config.settings import get_settings
    from strategy.pdf_strategies import StrategyRouter

    assert get_settings().active_model == "v26"
    assert StrategyRouter().settings.wce_shadow is True


def test_v26_instance_is_reused_across_bars():
    """`initial_sl` nao pode construir V26Strategy a cada barra: num backtest
    de 35k barras isso e trabalho invisivel dentro do laco."""
    wce = WCE2014Strategy()
    wce.initial_sl(2000.0, 5.0, 20.0, "BUY")
    primeiro = wce._v26
    assert primeiro is not None
    wce.initial_sl(2010.0, 6.0, 20.0, "SELL")
    assert wce._v26 is primeiro
