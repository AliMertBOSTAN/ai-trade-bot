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
import time

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
from engine.marketdata import markets as market_markets
from engine.marketdata import news as market_news
from engine.util.logging import setup_logging

setup_logging()
# Yapılandırmayı başlangıçta doğrula: kritik hatada net mesajla DUR (fail-fast),
# diğer durumlarda uyar (sessiz yanlış davranış yok).
settings.validate_or_raise()

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
    # Eğitilmiş ML modeli varsa otomatik yükle (yoksa sessizce atla).
    try:
        import os
        from engine.signals import engine as _sig
        _mp = os.path.join(os.environ.get("DATA_DIR", "data"), "ml_model.json")
        if os.path.exists(_mp) and _sig.load_ml_model(_mp):
            import logging as _lg
            _lg.getLogger("ml").info("ML sinyal modeli yuklendi: %s", _mp)
    except Exception:
        pass
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


@app.get("/health")
def health():
    """Alt sistemlerin durum özeti (izleme/uptime için). Ağ-yoğun değildir."""
    st = bot.state()
    last_tick = st.get("lastTick", 0) or 0
    tick_age_s = (time.time() * 1000 - last_tick) / 1000 if last_tick else None

    llm_key = {
        "deepseek": settings.deepseek_api_key,
        "anthropic": settings.anthropic_api_key,
        "openai": settings.openai_api_key,
    }.get(settings.llm_provider, "")

    rpc_configured = sum(1 for url in settings.rpc.values() if url)
    checks = {
        "engine_running": st.get("status") == "running",
        "rpc_env_configured": rpc_configured > 0,
        "llm_ready": settings.llm_provider == "none" or bool(llm_key),
        "news_feeds": len(settings.news_feeds) >= 0,
        "wallet_ready_for_live": (not settings.is_live) or bool(settings.wallet_private_key),
    }
    critical_ok = checks["llm_ready"] and checks["wallet_ready_for_live"]
    status = "ok" if critical_ok else "degraded"

    return {
        "status": status,
        "mode": st.get("mode"),
        "engine_status": st.get("status"),
        "last_tick_ms": last_tick,
        "tick_age_seconds": round(tick_age_s, 1) if tick_age_s is not None else None,
        "llm_provider": settings.llm_provider,
        "rpc_env_configured_chains": rpc_configured,
        "enabled_chains": bot.enabled_chains,
        "news_feed_count": len(settings.news_feeds),
        "checks": checks,
        "version": app.version,
    }


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


@app.get("/strategies")
def strategies(): return bot.get_strategies()


@app.get("/strategies/signals")
def strategy_signals(): return bot.get_strategy_signals()


class StrategyConfigBody(BaseModel):
    name: str
    enabled: bool | None = None
    weight: float | None = None


@app.post("/strategies/config")
def strategies_config(body: StrategyConfigBody):
    """Stratejiyi aç/kapa ve/veya ağırlığını ayarla (kullanıcı kontrolü)."""
    return bot.set_strategy(body.name, enabled=body.enabled, weight=body.weight)


@app.get("/chains")
def chains():
    """İşlem yapılabilecek tüm zincirler + hangileri aktif (kullanıcı seçimi)."""
    return bot.get_chains()


class ChainConfigBody(BaseModel):
    chain_id: int | None = None
    active: bool | None = None
    chain_ids: list[int] | None = None  # toplu seçim (hepsi/alt küme)


@app.post("/chains/config")
def chains_config(body: ChainConfigBody):
    """Aktif zincirleri ayarla: tekli (chain_id+active) veya toplu (chain_ids)."""
    if body.chain_ids is not None:
        return bot.set_chains(body.chain_ids)
    if body.chain_id is not None and body.active is not None:
        return bot.set_chain(body.chain_id, body.active)
    return bot.get_chains()


@app.get("/portfolio")
def portfolio(): return bot.get_portfolio()


@app.get("/trades")
def trades(limit: int = 100): return bot.get_trades(limit)


@app.post("/trades/clear")
def trades_clear(): return bot.clear_trades()


class PaperResetBody(BaseModel):
    seed_usd: float | None = None


@app.post("/portfolio/reset")
def portfolio_reset(body: PaperResetBody | None = None):
    """Paper portföyü sıfırla ve PAPER_SEED_USD değerinde ETH ile yeniden başlat."""
    seed = body.seed_usd if body else None
    return bot.reset_paper(seed_usd=seed)


@app.get("/equity")
def equity(): return bot.get_equity_curve()


@app.get("/summary")
def summary(hours: float = 24.0):
    """Son `hours` saatlik PnL/işlem özetini döndürür (bildirim göndermez)."""
    from engine.notify.summary import build_summary
    text = build_summary(bot.get_trades(500), bot.get_equity_curve(), hours)
    return {"text": text, "channels": _notify_channels()}


@app.post("/notify/test")
def notify_test():
    """Etkin bildirim kanallarına test mesajı yollar (anahtarsızsa log'a)."""
    from engine.notify import notify as _do_notify
    return {"delivery": _do_notify("Test bildirimi — ai-trade-bot", "info")}


@app.post("/notify/summary")
def notify_summary(hours: float = 24.0):
    """Günlük özeti üretip bildirim kanallarına gönderir (zamanlanabilir)."""
    from engine.notify.summary import send_daily_summary
    from engine.storage.db import store
    return send_daily_summary(store, hours)


def _notify_channels():
    from engine.notify import channels_enabled
    return channels_enabled()


@app.get("/security")
def security(): return bot.get_security()


@app.post("/backup")
def backup():
    """Veritabanını yedekler (en yeni 5 saklanır). Zamanlanabilir."""
    from engine.storage.db import store
    path = store.backup()
    return {"ok": True, "path": path}


@app.get("/metrics")
def metrics():
    """Sade Prometheus-uyumlu metrikler (gözlemlenebilirlik + güvenlik)."""
    from fastapi.responses import PlainTextResponse
    s = bot.get_security()
    lines = [
        "# HELP atb_equity_usd Güncel portföy değeri",
        "# TYPE atb_equity_usd gauge",
        f"atb_equity_usd {s['equity_usd']:.4f}",
        "# TYPE atb_peak_equity_usd gauge",
        f"atb_peak_equity_usd {s['peak_equity_usd']:.4f}",
        "# TYPE atb_daily_spent_usd gauge",
        f"atb_daily_spent_usd {s['daily_spent_usd']:.4f}",
        "# TYPE atb_day_realized_pnl_usd gauge",
        f"atb_day_realized_pnl_usd {s['day_realized_pnl_usd']:.4f}",
        "# TYPE atb_kill_switch gauge",
        f"atb_kill_switch {1 if s['kill_switch'] else 0}",
        "# TYPE atb_trades_total counter",
        f"atb_trades_total {s['trades_total']}",
        "# TYPE atb_live_mode gauge",
        f"atb_live_mode {1 if s['mode'] == 'live' else 0}",
    ]
    return PlainTextResponse("\n".join(lines) + "\n")


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


@app.get("/markets")
def markets():
    """Botun gördüğü TÜM enstrümanlar tek çatıda (Keşfet ekranı).

    DEX fiyatları bellekteki son değerlerden (hızlı), CEX (Binance) canlı çekilir.
    Yanıt ayrıca piyasa kaydını (MARKETS) döndürür; ileride BIST/ABD gibi
    piyasalar status="coming_soon" ile burada görünür.
    """
    return market_markets.all_markets(bot.get_prices())


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


@app.get("/whales/{symbol}")
def whales_endpoint(symbol: str, min_usd: float = 25000.0):
    """Balina takibi: büyük emir baskısı (alım/satım) + emir defteri duvarları."""
    from engine.marketdata import whales as whales_mod
    return whales_mod.summary(symbol, min_usd=min_usd)


@app.get("/wallet")
def wallet_get():
    """Aktif cüzdanın public adresi (özel anahtar ASLA dönmez)."""
    from engine.trading import wallet as wallet_mod
    return wallet_mod.get_wallet()


class WalletBody(BaseModel):
    address: str = ""


@app.post("/wallet")
def wallet_connect(body: WalletBody):
    """Uygulama içinden public adres bağla/temizle (izleme; imza yapmaz)."""
    from fastapi import HTTPException
    from engine.trading import wallet as wallet_mod
    try:
        return wallet_mod.set_watch_address(body.address)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
