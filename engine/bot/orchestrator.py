"""Bot orkestratörü - ana döngü.

Her tick:
 1. Tüm zincir/DEX fiyatlarını çeker (oracle)
 2. Token başına kapanış geçmişini günceller (indikatör beslemesi)
 3. Hibrit sinyal üretir, risk kapılarından geçirir, emir çalıştırır (mod switch)
 4. Zincirler arası arbitraj tarar
 5. Portföyü mark-to-market eder, her şeyi DB'ye yazar ve event yayınlar
Thread-safe; FastAPI sunucusu start/stop/setMode çağırır.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from typing import Callable

from engine.arbitrage.scanner import scan_arbitrage
from engine.config.settings import RiskConfig, settings
from engine.dex.oracle import fetch_all_prices
from engine.models import PriceQuote, TradeOrder, now_ms
from engine.risk.manager import RiskManager
from engine.signals.engine import generate_signal
from engine.storage.db import store
from engine.trading.executor import Executor
from engine.trading.portfolio import Portfolio

log = logging.getLogger("orchestrator")

EventCb = Callable[[dict], None]


class TradingBot:
    def __init__(self, risk: RiskConfig | None = None):
        self.risk = risk or settings.risk
        self.portfolio = Portfolio(settings.starting_cash_usd)
        # Snapshot varsa portföyü ve modu geri yükle (başka cihazda kaldığı yer).
        persisted_state = store.load_state()
        initial_mode = settings.trading_mode
        self._was_running_on_disk = False
        if persisted_state:
            pf = persisted_state.get("portfolio")
            if pf:
                try:
                    self.portfolio.load_persist(pf)
                    log.info("Portföy snapshot'tan yüklendi: cash=%.2f, pos=%d",
                             self.portfolio.cash_usd, len(self.portfolio.positions))
                except Exception as e:
                    log.warning("Snapshot yüklenemedi, sıfırdan başlanıyor: %s", e)
            initial_mode = persisted_state.get("mode") or initial_mode
            self._was_running_on_disk = bool(persisted_state.get("was_running"))

        self.executor = Executor(self.portfolio, self.risk, initial_mode)
        self.rm = RiskManager(self.risk)

        self.enabled_chains = list(settings.rpc.keys())
        self.poll_interval = settings.poll_interval_ms / 1000.0

        self._history: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=200))
        self._latest_prices: list[PriceQuote] = []
        self._latest_arbs: list = []
        self._latest_signals: list = []

        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._subs: list[EventCb] = []
        self.status = "stopped"
        self.last_tick = 0
        self.message = ""
        self._day_start = time.time()

    # ---- kalıcılık ----
    def _persist_state(self) -> None:
        try:
            store.save_state({
                "portfolio": self.portfolio.to_persist(),
                "mode": self.executor.mode,
                "was_running": self._running.is_set(),
                "updated_at": now_ms(),
            })
        except Exception as e:
            log.warning("state.json yazılamadı: %s", e)

    def maybe_resume(self) -> None:
        """state.json'da was_running=True ise botu otomatik başlatır."""
        if self._was_running_on_disk and not self._running.is_set():
            log.info("Önceki oturum çalışıyordu — otomatik devam ediliyor")
            self.start()

    # ---- pub/sub ----
    def subscribe(self, cb: EventCb) -> Callable[[], None]:
        self._subs.append(cb)
        return lambda: self._subs.remove(cb) if cb in self._subs else None

    def _emit(self, evt: dict) -> None:
        for cb in list(self._subs):
            try:
                cb(evt)
            except Exception:
                pass

    # ---- yaşam döngüsü ----
    def start(self) -> dict:
        if self._running.is_set():
            return self.state()
        self._running.set()
        self.status = "running"
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info("Bot başlatıldı (mod=%s)", self.executor.mode)
        self._persist_state()
        return self.state()

    def stop(self) -> dict:
        self._running.clear()
        self.status = "stopped"
        log.info("Bot durduruldu")
        self._persist_state()
        return self.state()

    def set_mode(self, mode: str) -> dict:
        try:
            self.executor.set_mode(mode)
            self.message = ""
            self._persist_state()
        except Exception as e:
            self.status = "error"
            self.message = str(e)
        return self.state()

    def state(self) -> dict:
        return {"status": self.status, "mode": self.executor.mode,
                "last_tick": self.last_tick, "message": self.message}

    # ---- ana döngü ----
    def _loop(self) -> None:
        while self._running.is_set():
            try:
                self._tick()
            except Exception as e:
                log.exception("Tick hatası")
                self.status = "error"
                self.message = str(e)
                self._emit({"type": "log", "level": "error", "message": str(e)})
            time.sleep(self.poll_interval)

    def _tick(self) -> None:
        # günlük kill-switch sayacını sıfırla
        if time.time() - self._day_start > 86400:
            self.rm.reset_daily()
            self._day_start = time.time()

        prices = fetch_all_prices(self.enabled_chains)
        self._latest_prices = prices

        # fiyat geçmişini güncelle (key: chainId:dex:base) ve mark için ortalama
        mark_prices: dict[str, float] = {}
        per_token: dict[tuple[int, str], list[float]] = defaultdict(list)
        for q in prices:
            self._history[f"{q.chain_id}:{q.dex}:{q.base}"].append(q.price)
            per_token[(q.chain_id, q.base)].append(q.price)
        for (cid, base), plist in per_token.items():
            mark_prices[f"{cid}:{base}"] = sum(plist) / len(plist)

        self.portfolio.mark(mark_prices)

        # --- sinyal + işlem ---
        signals = []
        for (cid, base), plist in per_token.items():
            avg = sum(plist) / len(plist)
            hist_key = f"{cid}:agg:{base}"
            self._history[hist_key].append(avg)
            closes = list(self._history[hist_key])
            if len(closes) < 31:
                continue
            quote = next((q.quote for q in prices if q.chain_id == cid and q.base == base), "USD")
            sig = generate_signal(cid, base, quote, closes)
            signals.append(sig)
            store.save_signal(sig)
            self._emit({"type": "signal", "signal": sig.to_dict()})
            self._maybe_trade(sig, prices)
        self._latest_signals = signals

        # --- arbitraj ---
        arbs = scan_arbitrage(prices, self.risk)
        self._latest_arbs = arbs
        for o in arbs[:10]:
            store.save_arbitrage(o)
            self._emit({"type": "arbitrage", "opp": o.to_dict()})

        # --- kayıt + event ---
        self.last_tick = now_ms()
        store.save_equity(self.last_tick, self.portfolio.equity_usd())
        self._emit({"type": "tick", "state": self.state()})

    def _maybe_trade(self, sig, prices: list[PriceQuote]) -> None:
        decision = self.rm.evaluate(sig, self.portfolio.positions, self.portfolio.cash_usd)
        if not decision.approved:
            return
        # en likit DEX'i seç
        candidates = [q for q in prices if q.chain_id == sig.chain_id and q.base == sig.base]
        if not candidates:
            return
        best = max(candidates, key=lambda q: q.liquidity_usd)

        # live modda gas tavanı kontrolü
        if self.executor.mode == "live":
            ok, gwei = self.rm.gas_ok(sig.chain_id)
            if not ok:
                self._emit({"type": "log", "level": "warn",
                            "message": f"Gas tavanı ({gwei:.0f} gwei) - işlem atlandı"})
                return

        amount = (decision.size_usd / best.price) if sig.action == "BUY" else (
            self.portfolio.positions[f"{sig.chain_id}:{sig.base}"].amount)
        # "Neden al/sat" gerekçesi: aksiyon + güven + kaynak + gösterge okuması.
        reason = (f"{sig.action} · güven %{round(sig.confidence * 100)} · "
                  f"{sig.source} · {sig.rationale}")
        order = TradeOrder(mode=self.executor.mode, chain_id=sig.chain_id,
                           dex=best.dex, base=sig.base, quote=sig.quote,
                           side=sig.action, amount=amount, price=best.price,
                           signal_id=sig.id, reason=reason)
        filled = self.executor.execute(order)
        if filled.status == "filled" and filled.side == "SELL":
            self.rm.record_realized(self.portfolio.realized_pnl_usd)
        store.save_trade(filled)
        if filled.status == "filled":
            self._persist_state()
        self._emit({"type": "trade", "order": filled.to_api()})

    # ---- okuma erişimcileri (API için) ----
    def get_prices(self): return [q.to_dict() for q in self._latest_prices]
    def get_arbitrage(self): return [o.to_dict() for o in self._latest_arbs]
    def get_signals(self): return [s.to_dict() for s in self._latest_signals]
    def get_portfolio(self): return self.portfolio.snapshot()
    def get_trades(self, limit=100): return store.recent_trades(limit)
    def get_equity_curve(self): return store.equity_curve()

    def active_symbol(self) -> str:
        """Chart'ın izleyeceği sembol: en son sinyal -> açık pozisyon -> ETH."""
        if self._latest_signals:
            return self._latest_signals[-1].base
        if self.portfolio.positions:
            return next(iter(self.portfolio.positions.values())).base
        return "ETH"


bot = TradingBot()
