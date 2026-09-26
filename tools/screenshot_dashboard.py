"""Captura headless do dashboard via streamlit.testing.v1.AppTest.

Gera `docs/dashboard_btcusd.png` com o painel BTCUSD renderizado.
Não abre browser, não precisa de kaleido, e usa um fake MT5 (o terminal
real não está aberto nesta máquina).

Uso:  python tools/screenshot_dashboard.py
"""

from __future__ import annotations

import sys
import time
import types
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# O console do Windows (cp1252) nao imprime emoji dos rotulos Streamlit.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# --- Dados sintéticos realistas -------------------------------------------
N_BARS = 300
rng = np.random.default_rng(42)
prices = 60000 + np.cumsum(rng.normal(0, 180, N_BARS))


def _frame(base: float, vol: float, seed: int) -> pd.DataFrame:
    r = np.random.default_rng(seed)
    closes = base + np.cumsum(r.normal(0, vol, N_BARS))
    opens = np.concatenate([[closes[0]], closes[:-1]])
    return pd.DataFrame(
        {
            "time": pd.date_range("2026-09-25", periods=N_BARS, freq="5min"),
            "open": opens,
            "high": np.maximum(opens, closes) + abs(r.normal(0, vol * 0.3, N_BARS)),
            "low": np.minimum(opens, closes) - abs(r.normal(0, vol * 0.3, N_BARS)),
            "close": closes,
            "tick_volume": r.integers(50, 400, N_BARS).astype(np.int64),
        }
    )


XAU = _frame(3350.0, 6.0, 7)
BTC = _frame(60000.0, 180.0, 42)


def _bars_for(symbol: str) -> pd.DataFrame:
    """Dados sintéticos do símbolo pedido."""
    return XAU if symbol.upper().startswith("XAU") else BTC


def install_fake_mt5() -> None:
    """Substitui MetaTrader5 por um dublê com dados de XAUUSD e BTCUSD."""
    from config.settings import Settings

    settings = Settings()

    fake = MagicMock()
    fake.positions_get.return_value = []
    fake.history_orders_get.return_value = []
    fake.copy_rates_from_pos.side_effect = lambda sym, tf, pos, n: _bars_for(sym)
    fake.symbol_info_tick.side_effect = lambda sym: (
        _bars_for(sym)["close"].iloc[-1]  # preço de referência
    )
    fake.terminal_info.return_value = MagicMock(connected=True)
    fake.last_error.return_value = (0, "ok")
    fake.TIMEFRAME_M5 = 5

    tick = MagicMock()
    tick.bid = 3350.42
    tick.ask = 3350.68
    tick.time = 1_700_000_000

    def _tick_for(sym):
        if sym.upper().startswith("BTC"):
            t = MagicMock()
            t.bid = float(BTC["close"].iloc[-1]) - 0.5
            t.ask = float(BTC["close"].iloc[-1]) + 0.5
            t.time = 1_700_000_000
            return t
        return tick

    fake.symbol_info_tick.side_effect = _tick_for

    acc = MagicMock()
    acc.login = 1045989
    acc.server = "Headway-Live"
    acc.currency = "USD"
    acc.balance = 10_000.0
    acc.equity = 10_042.30
    acc.profit = 42.30
    acc.leverage = 500
    acc.margin_free = 9_980.0
    acc.company = "Headway Markets"
    acc.trade_mode = 0
    fake.account_info.return_value = acc
    fake.ACCOUNT_TRADE_MODE_REAL = 2
    fake.ACCOUNT_TRADE_MODE_CONTEST = 1

    sys.modules["MetaTrader5"] = fake
    return settings


def main() -> int:
    install_fake_mt5()

    import core.market_data as market_data

    # fetch_ohlcv passa a servir o DataFrame direto (bypass do MT5 nativo)
    def _fetch_ohlcv(self, symbol=None, timeframe=None, n_bars=None):
        return _bars_for(symbol or "XAUUSD-VIP").copy()

    def _latest_price(self, symbol=None):
        return float(_bars_for(symbol or "XAUUSD-VIP")["close"].iloc[-1])

    market_data.MarketData.fetch_ohlcv = _fetch_ohlcv
    market_data.MarketData.get_latest_price = _latest_price
    market_data.MarketData.current_spread = lambda self, symbol=None: 0.26

    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "web" / "dashboard.py"), default_timeout=90)
    at.run()

    if at.exception:
        for exc in at.exception:
            print(f"EXCECAO NO APP: {exc.value}", file=sys.stderr)
        return 1

    out = ROOT / "docs" / "dashboard_btcusd.png"
    out.parent.mkdir(parents=True, exist_ok=True)

    # 1) Verificacao estrutural do app renderizado
    print("subheaders:", [s.value for s in at.subheader])
    txt = " ".join(el.value for el in at.markdown)
    captions = " ".join(c.value for c in at.caption)
    print("rotulo 'sem sinais' presente:", "sem sinais" in (txt + captions).lower())
    print("metricos:", [m.value for m in at.metric])
    print("erros:", [e.value for e in at.error])
    print("warnings:", [w.value for w in at.warning])

    # 2) Captura de imagem: AppTest nao tem screenshot nesta versao do
    #    Streamlit; usamos o modo headless do Edge instalado na maquina.
    import subprocess
    import time
    import urllib.request

    port = 8599
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run",
            str(ROOT / "web" / "dashboard.py"),
            "--server.port", str(port),
            "--server.headless", "true",
            "--browser.gatherUsageStats", "false",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://localhost:{port}", timeout=1)
                break
            except Exception:
                time.sleep(1)
        time.sleep(25)  # Streamlit + Plotly 6 seções: 25s para render completo

        edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
        subprocess.run(
            [
                str(edge), "--headless=new", "--disable-gpu",
                f"--screenshot={out}", f"--window-size=1600,3600",
                "--hide-scrollbars",
                f"http://localhost:{port}",
            ],
            check=False, timeout=180,
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    print(f"screenshot: {out} existe={out.exists()} bytes={out.stat().st_size if out.exists() else 0}")
    return 0 if out.exists() else 1


if __name__ == "__main__":
    raise SystemExit(main())
