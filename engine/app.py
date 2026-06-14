"""FastAPI + WebSocket sunucusu.

Electron UI (TypeScript) buraya bağlanır:
  - REST: /state, /prices, /arbitrage, /signals, /portfolio, /trades, /equity
          /marketdata, /news, /analyst  (açık CEX/DEX verisi + haber + LLM yorum)
  - POST: /start, /stop, /mode, /backtest
  - WS:   /ws  (tick/signal/trade/arbitrage/log event akışı)

Çalıştır:  uvicorn engine.app:app --port 8787
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from engine.backtest.backtester import run_backtest
from engine.bot.orchestrator import bot
from engine.config.chains import CHAINS
from engine.config.settings import settings
from engine.dex import gas as gas_mod
from engine.marketdata import aggregator as market_aggregator
from engine.marketdata import analyst as market_analyst
from engine.marketdata import chart as market_chart
from engine.marketdata import news as market_news

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(title="AI Trade Bot Engine", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

# WS event köprüsü: orchestrator senkron thread'den event yayınlar;
# bunları asyncio kuyruğuna aktarıp bağlı tüm soketlere dağıtırız.
_loop: asyncio.AbstractEventLoop | None = None
_clients: set[WebSocket] = set()
_queue: asyncio.Queue | None = None


def _on_event(evt: dict) -> None:
    if _loop and _queue:
        _loop.call_soon_threadsafe(_queue.put_nowait, evt)


@app.on_event("startup")
async def _startup() -> None:
    global _loop, _queue
    _loop = asyncio.get_running_loop()
    _queue = asyncio.Queue()
    bot.subscribe(_on_event)
    asyncio.create_task(_broadcaster())
    # Önceki oturum çalışır durumdaysa snapshot'tan kaldığı yerden devam et.
    bot.maybe_resume()


async def _broadcaster() -> None:
    assert _queue is not None
    while True:
        evt = await _queue.get()
        dead = []
        for ws in _clients:
            try:
                await ws.send_json(evt)
            except Exception:
                dead.append(ws)
        for ws in dead:
            _clients.discard(ws)


# ---------- REST ----------
@app.get("/state")
def state(): return bot.state()


@app.get("/config")
def config():
    return {
        "mode": bot.executor.mode,
        "poll_interval_ms": settings.poll_interval_ms,
        "enabled_chains": bot.enabled_chains,
        "starting_cash_usd": settings.starting_cash_usd,
        "llm_provider": settings.llm_provider,
        "risk": settings.risk.__dict__,
    }


@app.get("/prices")
def prices(): return bot.get_prices()


@app.get("/arbitrage")
def arbitrage(): return bot.get_arbitrage()


@app.get("/signals")
def signals(): return bot.get_signals()


@app.get("/portfolio")
def portfolio(): return bot.get_portfolio()


@app.get("/trades")
def trades(limit: int = 100): return bot.get_trades(limit)


@app.get("/equity")
def equity(): return bot.get_equity_curve()


@app.post("/start")
def start(): return bot.start()


@app.post("/stop")
def stop(): return bot.stop()


class ModeBody(BaseModel):
    mode: str


@app.post("/mode")
def set_mode(body: ModeBody): return bot.set_mode(body.mode)


class BacktestBody(BaseModel):
    base: str
    quote: str = "USD"
    candles: list[dict]
    starting_cash_usd: float = 10000.0


@app.post("/backtest")
def backtest(body: BacktestBody):
    return run_backtest(body.candles, body.base, body.quote,
                        body.starting_cash_usd, settings.risk)


# ---------- Açık piyasa verisi + haber + LLM analist ----------
# Ağ çağrıları bloklayıcı olduğundan threadpool'da koşturulur (def, async değil).

@app.get("/marketdata/{symbol}")
def marketdata(symbol: str):
    """CEX (Binance) + DEX (Uniswap vb.) karşılaştırmalı anlık veri."""
    return market_aggregator.snapshot(symbol)


@app.get("/marketdata")
def marketdata_multi(symbols: str = "ETH,BTC"):
    """Virgülle ayrılmış sembol listesi için toplu anlık veri."""
    return market_aggregator.multi_snapshot(
        [s.strip() for s in symbols.split(",") if s.strip()])


@app.get("/chart")
def chart(symbol: str | None = None, interval: str = "1h", limit: int = 200):
    """TA chart beslemesi: OHLCV + custom indikatör overlay'leri + al/sat işaretleri.

    symbol verilmezse bot'un aktif sembolü (son sinyal/pozisyon) izlenir.
    """
    base = symbol or bot.active_symbol()
    return market_chart.chart_feed(base, interval=interval, limit=min(limit, 1000))


@app.get("/news")
def get_news(limit: int = 30, q: str | None = None):
    """Anlık kripto haber başlıkları (RSS). q ile filtrelenebilir."""
    return market_news.fetch_headlines(limit=limit, query=q)


@app.get("/gas")
def gas():
    """Zincir başına canlı gas fiyatı (gwei) + tek swap maliyeti (USD)."""
    out = []
    for cid in bot.enabled_chains:
        ch = CHAINS.get(cid)
        if ch is None:
            continue
        out.append({
            "chain_id": cid,
            "chain": ch.name,
            "gwei": round(gas_mod.gas_price_gwei(cid), 3),
            "swap_usd": round(gas_mod.gas_cost_usd(cid, gas_mod.GAS_UNITS_SWAP), 4),
        })
    return out


@app.get("/analyst/{symbol}")
def analyst(symbol: str, q: str | None = None):
    """LLM piyasa analisti: CEX/DEX verisi + haberleri karşılaştırıp yorumlar.

    LLM key .env'de yapılandırılmamışsa yalnızca sayısal rapor döner.
    """
    return market_analyst.analyze(symbol, news_query=q)


# ---------- WebSocket ----------
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    _clients.add(ws)
    try:
        await ws.send_json({"type": "tick", "state": bot.state()})
        while True:
            await ws.receive_text()  # client ping/keepalive
    except WebSocketDisconnect:
        _clients.discard(ws)
    except Exception:
        _clients.discard(ws)
