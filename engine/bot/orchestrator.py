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
from engine.marketdata import binance
from engine.models import PriceQuote, TradeOrder, now_ms
from engine.risk.manager import RiskManager
from engine.signals.engine import generate_signal
from engine.trading import smart_exec
from engine.notify import notify as _notify
from engine.security.spending import SpendingLimiter
from engine.strategy.base import StrategyContext
from engine.strategy.config import default_manager
from engine.storage.db import store
from engine.trading.executor import Executor
from engine.trading.portfolio import Portfolio

log = logging.getLogger("orchestrator")

EventCb = Callable[[dict], None]

# Sinyaller için minimum geçmiş (mum) sayısı (göstergeler için).
WARMUP = 31

# Sinyal izleme listesi: RPC/DEX fiyatı OLMASA bile (paper mod) Binance
# (anahtarsız) klines/ticker ile sinyal üretilir. (chain_id, base, quote, binance)
SIGNAL_WATCHLIST: list[tuple[int, str, str, str]] = [
    (1, "WETH", "USDC", "ETHUSDT"),
    (1, "WBTC", "USDC", "BTCUSDT"),
    (56, "WBNB", "USDT", "BNBUSDT"),
    (137, "WMATIC", "USDC", "MATICUSDT"),
    (42161, "ARB", "USDC", "ARBUSDT"),
    (10, "OP", "USDC", "OPUSDT"),
    (1, "LINK", "USDC", "LINKUSDT"),
    (1, "UNI", "USDC", "UNIUSDT"),
]
_WL_BINANCE = {(c, b): bs for c, b, _q, bs in SIGNAL_WATCHLIST}
_WL_QUOTE = {(c, b): q for c, b, q, _bs in SIGNAL_WATCHLIST}


class TradingBot:
    def __init__(self, risk: RiskConfig | None = None):
        self.risk = risk or settings.risk
        self.portfolio = Portfolio(settings.starting_cash_usd)
        # Snapshot varsa portföyü ve modu geri yükle (başka cihazda kaldığı yer).
        persisted_state = store.load_state()
        initial_mode = settings.trading_mode
        self._was_running_on_disk = False
        fresh_start = True
        if persisted_state:
            pf = persisted_state.get("portfolio")
            if pf:
                try:
                    self.portfolio.load_persist(pf)
                    fresh_start = False
                    log.info("Portföy snapshot'tan yüklendi: cash=%.2f, pos=%d",
                             self.portfolio.cash_usd, len(self.portfolio.positions))
                except Exception as e:
                    log.warning("Snapshot yüklenemedi, sıfırdan başlanıyor: %s", e)
            initial_mode = persisted_state.get("mode") or initial_mode
            self._was_running_on_disk = bool(persisted_state.get("was_running"))

        # Paper modu tohumlama: taze başlangıçta portföy PAPER_SEED_USD değerinde
        # PAPER_SEED_ASSET (ETH/WETH) ile başlar. İlk tick'te fiyat gelince uygulanır.
        self._seed_pending = (
            fresh_start and initial_mode == "paper"
            and settings.paper_seed_usd > 0)
        if self._seed_pending:
            self.portfolio.cash_usd = settings.paper_seed_usd

        self.executor = Executor(self.portfolio, self.risk, initial_mode)
        self.rm = RiskManager(self.risk)
        try:
            from engine.tuning.optimizer import load_all as _load_tuned
            self._tuned = _load_tuned()
        except Exception:
            self._tuned = {}
        self._peak_equity = 0.0
        import os as _os
        self._spending = SpendingLimiter(
            float(_os.getenv("MAX_DAILY_SPEND_USD", "0")))

        self.all_chains = list(settings.rpc.keys())   # tum aday zincirler
        self.enabled_chains = list(self.all_chains)    # kullanici-aktif alt kume
        self._load_chain_config()
        self.poll_interval = settings.poll_interval_ms / 1000.0

        self._history: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=200))
        self._latest_prices: list[PriceQuote] = []
        self._latest_arbs: list = []
        self._latest_signals: list = []
        # Çoklu-strateji yöneticisi: aynı anda N strateji, sermaye ağırlıklı.
        # STRATEGIES env'iyle yapılandırılır (örn. "hybrid:1,trend:1,mean_reversion:0.5").
        self.strategies = default_manager()
        self._load_strategy_config()
        self._strategy_signals: list = []

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
            try:
                _notify(f"Mod değişti → {mode.upper()}",
                        level=("warn" if mode == "live" else "info"))
            except Exception:
                pass
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
        self._maybe_seed(mark_prices)

        # --- sinyal + işlem ---
        # Sinyal evreni: DEX-fiyatlı tokenlar + izleme listesi. Böylece RPC
        # tanımlı olmasa (paper mod) bile Binance fiyatından sinyal üretilir.
        signals = []
        strat_signals: list = []
        total_equity = self.portfolio.equity_usd()
        if total_equity > self._peak_equity:
            self._peak_equity = total_equity
        universe = set(per_token.keys()) | set(_WL_BINANCE.keys())
        for (cid, base) in universe:
            hist_key = f"{cid}:agg:{base}"
            # Geçmişi Binance klines ile ön-doldur (4 dk ısınma beklemeden,
            # gerçek mumlarla anlamlı göstergeler; RPC gerektirmez).
            self._seed_history(hist_key, _WL_BINANCE.get((cid, base)))

            # Bu tick'in fiyatı: DEX ortalaması varsa onu, yoksa Binance ticker.
            price_now = self._tick_price(cid, base, per_token)
            if price_now is None or price_now <= 0:
                continue
            self._history[hist_key].append(price_now)

            closes = list(self._history[hist_key])
            if len(closes) < WARMUP:
                continue
            quote = next((q.quote for q in prices if q.chain_id == cid and q.base == base),
                         _WL_QUOTE.get((cid, base), "USD"))
            sig = generate_signal(cid, base, quote, closes)
            signals.append(sig)
            store.save_signal(sig)
            self._emit({"type": "signal", "signal": sig.to_dict()})
            self._maybe_trade(sig, prices)

            # --- çoklu-strateji değerlendirmesi (her birine sermaye dilimiyle) ---
            # Eklemeli: mevcut hibrit akışını değiştirmez; her etkin stratejinin
            # kendi kararını strateji-etiketli olarak üretir ve UI'a sunar.
            try:
                tech = sig.technical

                def _factory(_name, cash, _tech=tech, _closes=closes,
                             _cid=cid, _base=base, _quote=quote):
                    return StrategyContext(
                        base=_base, quote=_quote, chain_id=_cid, closes=_closes,
                        highs=_closes, lows=_closes, volumes=[0.0] * len(_closes),
                        tech=_tech, price=_closes[-1], cash_allocated=cash)

                for ss in self.strategies.evaluate(_factory, total_equity):
                    if ss.action != "HOLD":
                        strat_signals.append({
                            "strategy": ss.strategy, "base": base, "quote": quote,
                            "chainId": cid, "action": ss.action,
                            "confidence": round(ss.confidence, 3), "reason": ss.reason,
                        })
            except Exception as e:  # noqa: BLE001
                log.debug("strateji değerlendirme hatası %s: %s", base, e)
        self._latest_signals = signals
        self._strategy_signals = strat_signals[-50:]

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

    def _seed_history(self, hist_key: str, binance_symbol: str | None) -> None:
        """Geçmiş kısa ise Binance klines (anahtarsız) ile ön-doldur.

        Sinyaller 4 dk ısınma beklemeden ve RPC olmadan da gerçek mum verisiyle
        çalışsın diye. Yeterince veri varsa dokunmaz.
        """
        if binance_symbol is None or len(self._history[hist_key]) >= WARMUP:
            return
        try:
            candles = binance.klines(binance_symbol, interval="1h", limit=120)
            closes = [c["close"] for c in candles if c.get("close")]
            if len(closes) >= WARMUP:
                self._history[hist_key] = deque(closes, maxlen=200)
        except Exception as e:  # pragma: no cover - ağ hatası
            log.debug("klines seed başarısız (%s): %s", binance_symbol, e)

    def _maybe_seed(self, mark_prices: dict[str, float]) -> None:
        """Paper başlangıç tohumu: cash'i PAPER_SEED_USD değerinde ETH'ye çevirir.

        Sadece bir kez, fiyat geldiğinde çalışır. Live modda hiçbir şey yapmaz.
        """
        if not getattr(self, "_seed_pending", False):
            return
        if self.executor.mode != "paper":
            self._seed_pending = False
            return
        asset = settings.paper_seed_asset.upper()
        chain = settings.paper_seed_chain
        # Fiyat: tercih edilen zincir mark'ı, yoksa Binance ticker, yoksa bekle.
        price = mark_prices.get(f"{chain}:{asset}")
        if not price:
            bs = _WL_BINANCE.get((chain, asset))
            if bs:
                try:
                    price = float(binance.ticker_24h(bs)["price"])
                except Exception:
                    price = None
        if not price or price <= 0:
            return  # fiyat gelene kadar bekle (sonraki tick'te tekrar dener)

        usd = float(settings.paper_seed_usd)
        amount = usd / price
        self.portfolio.cash_usd = usd  # tohum öncesi net nakit
        order = TradeOrder(
            mode="paper", chain_id=chain, dex="seed", base=asset, quote="USD",
            side="BUY", amount=amount, price=price, filled_price=price,
            fee_usd=0.0, status="filled", venue_type="dex",
            reason=f"Paper başlangıç tohumu: ${usd:.0f} değerinde {asset}")
        self.portfolio.apply_fill(order)
        self.portfolio.mark(mark_prices)
        self._seed_pending = False
        store.save_trade(order)
        self._persist_state()
        self._emit({"type": "log", "level": "info",
                    "message": (f"Paper portföy ${usd:.0f} {asset} ile başlatıldı "
                                f"(≈{amount:.4f} {asset} @ ${price:,.2f})")})

    def _tick_price(self, cid: int, base: str, per_token: dict) -> float | None:
        """Bu tick için fiyat: DEX ortalaması varsa onu, yoksa Binance ticker."""
        plist = per_token.get((cid, base))
        if plist:
            return sum(plist) / len(plist)
        bs = _WL_BINANCE.get((cid, base))
        if bs:
            try:
                return float(binance.ticker_24h(bs)["price"])
            except Exception as e:  # pragma: no cover - ağ hatası
                log.debug("ticker başarısız (%s): %s", bs, e)
        return None

    def _maybe_trade(self, sig, prices: list[PriceQuote]) -> None:
        # Sembol bazli ayarlanmis esik varsa ek bir kapi olarak uygula (additif).
        tuned = self._tuned.get(sig.base.upper())
        if tuned and sig.confidence < tuned.get("min_confidence", 0.0):
            return
        decision = self.rm.evaluate(sig, self.portfolio.positions, self.portfolio.cash_usd)
        if not decision.approved:
            return
        # en likit DEX'i seç
        candidates = [q for q in prices if q.chain_id == sig.chain_id and q.base == sig.base]
        if not candidates:
            return
        # Akıllı yürütme: etkin maliyeti en düşük DEX + drawdown'a göre boyut.
        equity_now = self.portfolio.equity_usd()
        plan = smart_exec.plan_execution(
            candidates, decision.size_usd, sig.action,
            equity_now, max(self._peak_equity, equity_now))
        if plan is None:
            best = max(candidates, key=lambda q: q.liquidity_usd)
            exec_size = decision.size_usd
            exec_note = ""
        else:
            best = next((q for q in candidates if q.dex == plan.dex), candidates[0])
            exec_size = plan.size_usd
            exec_note = plan.note
            if plan.derisk_factor <= 0.0:
                self._emit({"type": "log", "level": "warn",
                            "message": "Drawdown sert eşiği - yeni alım durduruldu"})
                if sig.action == "BUY":
                    return

        # live modda gas tavanı kontrolü
        if self.executor.mode == "live":
            ok, gwei = self.rm.gas_ok(sig.chain_id)
            if not ok:
                self._emit({"type": "log", "level": "warn",
                            "message": f"Gas tavanı ({gwei:.0f} gwei) - işlem atlandı"})
                return
            # günlük harcama limiti (yalnızca yeni alım nosyoneli)
            if sig.action == "BUY" and not self._spending.allowed(exec_size):
                self._emit({"type": "log", "level": "warn",
                            "message": (f"Günlük harcama limiti ({self._spending.daily_limit_usd:.0f}$) "
                                        f"- kalan {self._spending.remaining():.0f}$, işlem atlandı")})
                return

        amount = (exec_size / best.price) if sig.action == "BUY" else (
            self.portfolio.positions[f"{sig.chain_id}:{sig.base}"].amount)
        # İşlem türü + pozisyon etkisi (UI'da net görünsün):
        has_pos = f"{sig.chain_id}:{sig.base}" in self.portfolio.positions
        if sig.action == "BUY":
            act_tr, pos_action = "ALIM", ("pozisyona ekleme" if has_pos else "pozisyon açılışı")
        else:
            act_tr, pos_action = "SATIM", "pozisyon kapanışı"
        # "Neden al/sat" gerekçesi: işlem türü + pozisyon + güven + kaynak + gösterge.
        reason = (f"{act_tr} · {pos_action} · güven %{round(sig.confidence * 100)} · "
                  f"{sig.source} · {sig.rationale}"
                  + (f" · {exec_note}" if exec_note else ""))
        order = TradeOrder(mode=self.executor.mode, chain_id=sig.chain_id,
                           dex=best.dex, base=sig.base, quote=sig.quote,
                           side=sig.action, amount=amount, price=best.price,
                           signal_id=sig.id, reason=reason,
                           venue_type="dex")  # zincir-üstü DEX (gas dahil); CEX değil
        filled = self.executor.execute(order)
        if filled.status == "filled" and filled.side == "SELL":
            self.rm.record_realized(self.portfolio.realized_pnl_usd)
        store.save_trade(filled)
        if filled.status == "filled":
            self._persist_state()
            if self.executor.mode == "live" and filled.side == "BUY":
                self._spending.record(filled.amount * (filled.filled_price or filled.price))
            if self.executor.mode == "live":
                try:
                    _notify(f"{filled.side} {filled.base} @ "
                            f"{filled.filled_price or filled.price} "
                            f"({filled.amount:.4f})", level="trade")
                except Exception:
                    pass
        self._emit({"type": "trade", "order": filled.to_api()})
        if self.rm.kill_switch_triggered():
            try:
                _notify("Günlük zarar limiti aşıldı — kill-switch aktif. "
                        "Yeni işlemler durduruldu.", level="error")
            except Exception:
                pass

    # ---- okuma erişimcileri (API için) ----
    def get_security(self) -> dict:
        eq = self.portfolio.equity_usd()
        return {
            "mode": self.executor.mode,
            "equity_usd": eq,
            "peak_equity_usd": max(self._peak_equity, eq),
            "daily_spent_usd": self._spending.spent_today(),
            "daily_spend_limit_usd": self._spending.daily_limit_usd,
            "daily_spend_remaining_usd": self._spending.remaining(),
            "day_realized_pnl_usd": self.rm.day_realized_pnl,
            "kill_switch": self.rm.kill_switch_triggered(),
            "trades_total": len(store.recent_trades(100000)),
        }

    def get_prices(self): return [q.to_dict() for q in self._latest_prices]
    def get_arbitrage(self): return [o.to_dict() for o in self._latest_arbs]
    def get_signals(self): return [s.to_dict() for s in self._latest_signals]
    def get_strategy_signals(self): return list(self._strategy_signals)
    # ---- strateji kullanici kontrolu ----
    def _strategy_cfg_path(self) -> str:
        import os
        return os.path.join(os.environ.get("DATA_DIR", "data"), "strategies.json")

    def _load_strategy_config(self) -> None:
        import json
        import os
        path = self._strategy_cfg_path()
        if not os.path.exists(path):
            return
        try:
            from engine.strategy.manager import StrategyManager
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f)
            if cfg:
                self.strategies = StrategyManager.from_config(cfg)
        except Exception as e:  # noqa: BLE001
            log.warning("strateji config yuklenemedi: %s", e)

    def _save_strategy_config(self) -> None:
        import json
        import os
        path = self._strategy_cfg_path()
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.strategies.to_config(), f, indent=2)
        except Exception as e:  # noqa: BLE001
            log.warning("strateji config kaydedilemedi: %s", e)

    # ---- ag (zincir) kullanici kontrolu ----
    def _chain_cfg_path(self) -> str:
        import os
        return os.path.join(os.environ.get("DATA_DIR", "data"), "chains.json")

    def _load_chain_config(self) -> None:
        import json
        import os
        path = self._chain_cfg_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                ids = json.load(f)
            sel = [int(c) for c in ids if int(c) in self.all_chains]
            if sel:
                self.enabled_chains = sel
        except Exception as e:  # noqa: BLE001
            log.warning("zincir config yuklenemedi: %s", e)

    def _save_chain_config(self) -> None:
        import json
        import os
        path = self._chain_cfg_path()
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.enabled_chains, f)
        except Exception as e:  # noqa: BLE001
            log.warning("zincir config kaydedilemedi: %s", e)

    def get_chains(self) -> dict:
        from engine.config.chains import CHAINS
        rows = []
        for cid in self.all_chains:
            ch = CHAINS.get(cid)
            rows.append({
                "chain_id": cid,
                "name": ch.name if ch else str(cid),
                "native": ch.native_symbol if ch else "",
                "active": cid in self.enabled_chains,
            })
        return {"chains": rows, "active_count": len(self.enabled_chains)}

    def set_chains(self, ids: list[int]) -> dict:
        """Islem yapilacak zincir kumesini ayarla (bos = hicbiri = duraklat)."""
        sel = [int(c) for c in ids if int(c) in self.all_chains]
        # tekrar edenleri ayikla, sirayi all_chains'e gore koru
        self.enabled_chains = [c for c in self.all_chains if c in set(sel)]
        self._save_chain_config()
        try:
            names = ", ".join(str(c) for c in self.enabled_chains) or "(hicbiri)"
            self._emit({"type": "log", "level": "info",
                        "message": f"Aktif aglar: {names}"})
        except Exception:
            pass
        return self.get_chains()

    def set_chain(self, chain_id: int, active: bool) -> dict:
        """Tek bir zinciri ac/kapa."""
        cur = set(self.enabled_chains)
        if active:
            cur.add(int(chain_id))
        else:
            cur.discard(int(chain_id))
        return self.set_chains(list(cur))

    def set_strategy(self, name: str, enabled=None, weight=None) -> dict:
        """Stratejiyi aç/kapa ve/veya ağırlığını ayarla; kalıcı kaydet."""
        ok = True
        if weight is not None:
            ok = self.strategies.set_weight(name, float(weight)) and ok
        if enabled is not None:
            ok = self.strategies.set_enabled(name, bool(enabled)) and ok
        if ok:
            self._save_strategy_config()
        return {"ok": ok, "strategies": self.get_strategies()}

    def get_strategies(self):
        """Aktif strateji yapılandırması + mevcut (kayıtlı) stratejiler."""
        from engine.strategy import registry
        import engine.strategy.strategies  # noqa: F401
        return {"active": self.strategies.describe(),
                "available": registry.available(),
                "catalog": self.strategies.available_info()}
    def get_portfolio(self): return self.portfolio.snapshot()
    def get_trades(self, limit=100): return store.recent_trades(limit)
    def clear_trades(self) -> dict:
        """İşlem geçmişini siler. Bellekteki son sinyal listesine dokunmaz."""
        deleted = store.clear_trades()
        return {"ok": True, "deleted": deleted}

    def reset_paper(self, seed_usd: float | None = None) -> dict:
        """Paper portföyü sıfırla ve PAPER_SEED_USD değerinde ETH ile yeniden tohumla.

        Live modda ÇALIŞMAZ (gerçek bakiye korunur). İşlem geçmişi + equity
        eğrisi temizlenir; bir sonraki tick'te fiyat gelince ETH tohumu uygulanır.
        """
        if self.executor.mode == "live":
            return {"ok": False, "reason": "Live modda sıfırlama yapılmaz"}
        usd = float(seed_usd) if seed_usd is not None else float(settings.paper_seed_usd)
        # Portföyü YERİNDE sıfırla (broker referansları geçerli kalsın).
        self.portfolio.positions.clear()
        self.portfolio.cash_usd = usd
        self.portfolio.realized_pnl_usd = 0.0
        self.rm.reset_daily()
        self._peak_equity = usd
        self._seed_pending = usd > 0
        store.clear_trades()
        try:
            store.clear_equity()
        except Exception:
            pass
        self._persist_state()
        self._emit({"type": "log", "level": "info",
                    "message": (f"Paper portföy sıfırlandı → ${usd:.0f} "
                                f"{settings.paper_seed_asset} ile başlatılıyor")})
        return {"ok": True, "seed_usd": usd, "asset": settings.paper_seed_asset}

    def get_equity_curve(self): return store.equity_curve()

    def active_symbol(self) -> str:
        """Chart'ın izleyeceği sembol: en son sinyal -> açık pozisyon -> ETH."""
        if self._latest_signals:
            return self._latest_signals[-1].base
        if self.portfolio.positions:
            return next(iter(self.portfolio.positions.values())).base
        return "ETH"


bot = TradingBot()
