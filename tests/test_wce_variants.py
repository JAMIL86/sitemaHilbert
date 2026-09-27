"""Testes das variantes WCE 2014 (bloco experimental).

O que estes testes NAO fazem, e por que:

- Nao testam se a variante da dinheiro. Isso e medido por
  `python -m backtest.engine --model ... --with-costs` e lido do relatorio
  em `backtest/reports/wce_variants/`. Um teste que affirmasse "a variante
  lucra" seria um teste do mercado, nao do codigo.
- Nao usam o PDF para justificar numero. TP e SL **nao vem do WCE 2014**:
  o artigo escreve "closed when the signal exits the quarter" e nao menciona
  nenhum dos dois. Todo valor aqui e parametro de pesquisa, e o numero de
  onde veio esta em `docs/handoff.md` §14.3.

O que eles fazem: travam a MECANICA. Um TP de 50 pts tem de fechar a posicao
a +0,50 USD do preco de entrada; se um dia o `_target_hit` deixar de ser
chamado no loop, ou o `tp` deixar de chegar ao `Trade`, estes testes
quebram — e o backtest comecaria a devolver "0 TPs atingidos" sem que ninguem
percebesse. Foi exatamente o que aconteceu: `*_points` estava sendo somado ao
preco como se fosse USD, de modo que "50 pontos" virava alvo a +50,00 USD e
NENHUM TP disparava. A variante ficava silenciosamente identica a A, e o
relatorio mostraria so "0 TPs" — sem a causa. Um teste de contrato nao
teria detectado isso; o de comportamento detecta.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.engine import POINTS_TO_PRICE, WCE_VARIANTS, BacktestEngine


# --- fixtures ---------------------------------------------------------------

#: Path real do dataset. Os testes usam um SLICE deste arquivo, e nao uma
#: serie sintetica: o WCE decide por TRAVESSIA de quadrante do Hilbert, e
#: uma serie sintetica (dente-de-serra, aleatoria) simplesmente nao produz
#: travessias de quadrante — a variante devolvia 0 trades e os testes
#: "passavam" por vacuuo, sem exercitar nada. Um slice de 5.000 barras do
#: preco real produz ~107 entradas e roda em ~15 s.
CSV = "backtest/data/XAUUSD-VIP_M5_2026-03-30_2026-09-25.csv"
N_BARRAS = 5000


def _barras() -> pd.DataFrame:
    df = pd.read_csv(CSV)
    return df.iloc[:N_BARRAS].reset_index(drop=True)


def _engine(model: str) -> BacktestEngine:
    """Engine sem custos: aqui o que se testa e o preco de saida, nao o P&L."""
    return BacktestEngine(model=model, initial_balance=10_000.0, costs=None)


@pytest.fixture(scope="module")
def barras() -> pd.DataFrame:
    """CSV lido uma vez por modulo — 5.000 barras por teste seria lento."""
    return _barras()


# --- Teste 1: TP fecha em +50 pts ------------------------------------------

def test_wce_quadrant_tp_fecha_em_50_pontos(barras):
    """A variante TP tem de encerrar no alvo, e o alvo fica a +50 pts.

    Este e o teste que teria pegado a conversao de unidades. Com
    `*_points` somados ao preco como se fossem USD, o alvo ficava a
    +50,00 USD e NENHUM trade encerrava por TP — a variante ficava
    silenciosamente identica a A. A forma de falha era invisivel num
    relatorio, que so mostraria "0 TPs atingidos" sem explicar por que.
    Por isso o teste exige que o alvo sejaalcancavel E que de fato
    dispare; alem disso confere a distancia exata em cada trade.
    """
    variante = WCE_VARIANTS["wce_quadrant_tp"]
    assert variante.use_tp is True
    assert variante.use_sl is False
    assert variante.tp_points == 50.0

    trades = _engine("wce_quadrant_tp").run(barras).trades
    assert trades, "o slice real produz entradas de quadrante"

    for t in trades:
        assert t.tp is not None, "variante com use_tp=True nao pode ter trade sem TP"
        distancia = t.tp - t.entry_price if t.direction == "BUY" else t.entry_price - t.tp
        assert distancia == pytest.approx(0.50, abs=1e-6), (
            f"alvo a {distancia:.4f} USD da entrada, esperado 0,50 (50 pts)"
        )

    assert any(t.exit_reason == "TP" for t in trades), (
        "nenhum TP disparou — o alvo esta fora do alcance das barras "
        "(foi assim que a conversao de unidades quebrou, em silencio)"
    )


def test_tp_de_500_pontos_sera_inalcancavel_neste_dataset():
    """Trava a UNIDADE dos `*_points` das variantes — a causa dos "0 TPs".

    Este teste ja foi escrito com outra premissa: affirmava que 500 pontos
    (5,00 USD) seria geometricamente inalcancavel, comparando a mediana de
    close com o maximo do dataset. A premissa era FALSA — 4393,66 + 5,00
    cabe folgadamente. E o proprio sintoma a desmentiu: com 50 pontos
    (0,50 USD, bem dentro da amplitude mediana de 4,34 USD por barra M5)
    o TP continuava sem disparar.

    A causa era outra: `*_points` estava sendo somado ao preco como se
    fosse USD, de modo que "50 pontos" virava alvo a +50,00 USD. Um numero
    100x maior que o pretendido produz o mesmo sintoma de "nenhum TP
    atingido", e por isso esta forma de falha precisa ser travada por
    DISTANCIA, e nao por uma propriedade do mercado.
    """
    df = pd.read_csv("backtest/data/XAUUSD-VIP_M5_2026-03-30_2026-09-25.csv")
    amplitude = float((df["high"] - df["low"]).median())

    # O alvo pretendido (0,50 USD) tem de caber na barra tipica; o alvo
    # efetivamente usado (+50,00 USD, 11x a amplitude mediana) jamais
    # caberia em barra nenhuma. E por isso que ele nunca disparou.
    assert amplitude > 1.0, (
        f"amplitude mediana caiu para {amplitude:.2f} USD; o dataset mudou "
        "e a escala dos parametros de pesquisa precisa ser revisada"
    )
    assert POINTS_TO_PRICE == 0.01, "1 pt = 0,01 USD no XAUUSD-VIP"
    assert 50.0 * POINTS_TO_PRICE == 0.50
    assert 0.50 < amplitude, "alvo de 0,50 USD tem de caber na barra tipica"
    assert 50.0 > amplitude, "50,00 USD nao caberia — e por isso nao disparava"

    assert WCE_VARIANTS["wce_quadrant_tp"].tp_points == 50.0


# --- Teste 2: TP/SL fecha em +50 ou -250 pts --------------------------------

def test_wce_quadrant_tp_sl_tem_sl_fixo_de_250_e_tp_de_50(barras):
    """C carrega os dois alvos, e o SL e FIXO (2,50 USD) em toda entrada.

    O SL fixo e deliberado: o stop ATR do V26 varia por barra, e um SL que
    varia nao distinguiria o efeito do SL do efeito da formula ATR.
    """
    variante = WCE_VARIANTS["wce_quadrant_tp_sl"]
    assert variante.use_sl is True
    assert variante.use_tp is True
    assert variante.sl_points == 250.0
    assert variante.tp_points == 50.0

    trades = _engine("wce_quadrant_tp_sl").run(barras).trades
    assert trades, "variante C deveria produzir trades neste fixture"
    for t in trades:
        assert t.tp is not None
        assert t.sl > 0.0, "variante com use_sl=True nao pode ter trade sem stop"
        if t.direction == "BUY":
            assert t.sl == pytest.approx(t.entry_price - 2.50, abs=1e-6)
            assert t.tp == pytest.approx(t.entry_price + 0.50, abs=1e-6)
        else:
            assert t.sl == pytest.approx(t.entry_price + 2.50, abs=1e-6)
            assert t.tp == pytest.approx(t.entry_price - 0.50, abs=1e-6)


def test_sl_de_250_nao_e_o_stop_atr_do_v26(barras):
    """O SL de C nao pode variar por barra — se variar, e o ATR do V26.

    Dois trades de entradas diferentes precisam ter a MESMA distancia de
    stop em pontos. Um stop ATR produziria distancias diferentes.
    """
    trades = _engine("wce_quadrant_tp_sl").run(barras).trades
    distancias = {round(t.sl_points, 6) for t in trades}
    assert distancias <= {250.0}, f"SL variou por barra: {distancias}"


# --- Teste 3: A fecha SO no quadrante ---------------------------------------

def test_wce_quadrant_so_encerra_por_quadrante(barras):
    """A e o artigo literal: nenhum TP, nenhum SL, so a saida por quadrante.

    Este e o teste que carrega o peso da promessa. Se A algum dia adquirir um
    alvo, o numero de 894 trades deixa de ser "o artigo puro" e vira uma
    quinta via de pesquisa — e o relatorio passa a mentir sobre a origem da
    regra.
    """
    variante = WCE_VARIANTS["wce_quadrant"]
    assert variante.use_sl is False
    assert variante.use_tp is False

    trades = _engine("wce_quadrant").run(barras).trades

    assert trades
    for t in trades:
        assert t.tp is None, "variante A nao pode ter take profit"
        assert t.sl == 0.0, "variante A nao pode ter stop"
        assert t.sl_points == 0.0
        assert t.exit_reason in ("QUADRANT", "END"), (
            f"saida inesperada {t.exit_reason!r}: A so fecha no quadrante "
            "ou no fim da janela"
        )


def test_saida_por_stop_ou_alvo_esta_ausente_na_variante_a(barras):
    """Redundante com o teste acima por intencao: a redundancia e o alarme.

    Se o engine voltar a testar TP/SL antes do quadrante mesmo com A, o
    primeiro teste falha no `exit_reason`; este falha no `tp is None`. Dois
    lugares para o mesmo defeito, porque ele ja passou despercebido uma vez
    (a variante com TP=500 era silenciosamente igual a A).
    """
    reasons = {t.exit_reason for t in _engine("wce_quadrant").run(barras).trades}
    assert not (reasons & {"SL", "TP", "TRAIL"}), (
        f"variante A encerrou {reasons} — regra que o artigo nao escreve"
    )


# --- contrato das variantes -------------------------------------------------

@pytest.mark.parametrize("nome", sorted(WCE_VARIANTS))
def test_variante_declara_sua_origem(nome: str):
    """Toda variante tem de dizer de onde vem cada parametro.

    Um `description` vazio permitiria que um TP de pesquisa aparecesse num
    relatorio sem que ninguem dissesse que nao vem do PDF.
    """
    v = WCE_VARIANTS[nome]
    assert v.description, f"variante {nome} sem descricao de origem"
    assert v.name == nome
    assert v.sl_points >= 0 and v.tp_points >= 0
    if not v.use_sl:
        assert v.sl_points == 0.0
    if not v.use_tp:
        assert v.tp_points == 0.0
