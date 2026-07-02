"""Bot orkestratörü — ana döngü.

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
from engine.models import PriceQuote, TradeOrder, TradeSignal, now_ms
from engine.risk.manager import RiskManager
from engine.signals.engine import generate_signal
from engine.trading import smart_exec
from engine.notify import notify as _notify
from engine.security.spending import SpendingLimiter
from engine.strategy.base import StrategyContext
from engine.strategy.config import default_manager
from engine.sizing.position_sizing import atr_based_size
from engine.strategy.regime import Cooldown
from engine.strategy.router import select_active
from engine.trading.exits import ExitManager, ExitState
from engine.storage.db import store
from engine.trading.executor import Executor
from engine.trading.portfolio import Portfolio

log = logging.getLogger("orchestrator")

# Genel strateji profilleri: tek tıkla ağırlık seti + pozisyon giriş eşiği.
# Eşik (min_confidence) altındaki sinyaller pozisyon AÇAMAZ.
STRATEGY_PRESETS: dict[str, dict] = {
    "safe": {
        "title": "Güvenli",
        "min_confidence": 0.80,
        # sabırlı/seçici stratejiler: hibrit + trend + dip alımı
        "weights": {"hybrid": 1.5, "trend": 1.0,
                    "pullback": 0.75, "mean_reversion": 0.5},
        "disabled": ["breakout", "momentum", "squeeze", "sentiment"],
    },
    "balanced": {
        "title": "Dengeli",
        "min_confidence": 0.73,
        "weights": {"hybrid": 1.0, "trend": 1.0, "mean_reversion": 1.0,
                    "breakout": 1.0, "pullback": 1.0},
        "disabled": ["momentum", "squeeze", "sentiment"],
    },
    "aggressive": {
        "title": "Agresif",
        "min_confidence": 0.62,
        # hızlı/fırsatçı stratejiler de açık: ivme + sıkışma + haber
        "weights": {"breakout": 1.5, "trend": 1.25, "momentum": 1.25,
                    "squeeze": 1.0, "hybrid": 1.0,
                    "mean_reversion": 1.0, "sentiment": 0.75},
        "disabled": [],
    },
}

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
        # Rejim yönlendirme + aşırı-işlem freni:
        #  - _last_regimes: token -> son tespit edilen rejim (UI gösterimi)
        #  - _cooldown: aynı sembolde art arda YENİ ALIM açmayı sınırlar
        self._last_regimes: dict[str, str] = {}
        self._cooldown = Cooldown(
            float(_os.getenv("TRADE_COOLDOWN_S", "900")))
        # ATR tabanlı çıkış yönetimi: trailing stop + kısmi kâr + başabaş.
        # EXIT_STYLE=fixed ile eski sabit %5/%10 SL/TP'ye dönülebilir.
        self._exit_mgr = ExitManager()
        self._exit_states: dict[str, ExitState] = {}
        self._exit_style = _os.getenv("EXIT_STYLE", "atr").strip().lower()
        # İşlem başına risk (sermaye oranı) — ATR boyutlama TAVANI (0 = kapalı).
        # Yüksek oynaklıkta pozisyonu otomatik küçültür (volatilite hedefleme).
        self._risk_pct = float(_os.getenv("RISK_PCT_PER_TRADE", "0.01"))
        # Kullanıcı risk ayarları (giriş eşiği + profil) — data/risk.json'dan.
        self._preset = "custom"
        self._load_risk_config()
        # Sıfırlamada kullanıcı tutarı: _maybe_seed env yerine bunu kullanır.
        self._seed_usd_override: float | None = None

        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._subs: list[EventCb] = []
        self.status = "stopped"
        self.last_tick = 0
        self.message = ""
        self._day_start = time.time()

        # GÜVENLİK: günlük kill-switch + harcama sayaçları restart'ta
        # SIFIRLANMASIN — çöken/yeniden başlatılan bot günlük zarar limitini
        # atlatamaz. Aynı UTC günü içindeyse snapshot'tan geri yüklenir.
        try:
            rd = (persisted_state or {}).get("risk_day") or {}
            if int(rd.get("day_index", -1)) == int(time.time() // 86400):
                self.rm.day_realized_pnl = float(rd.get("day_realized_pnl", 0.0))
                self._spending._spent = max(0.0, float(rd.get("spent_today", 0.0)))
                self._day_start = float(rd.get("day_start", time.time()))
                if self.rm.kill_switch_triggered():
                    log.warning("Kill-switch snapshot'tan AKTİF yüklendi "
                                "(günlük zarar %.2f$)", self.rm.day_realized_pnl)
        except Exception as e:  # noqa: BLE001
            log.warning("günlük sayaç geri yüklenemedi: %s", e)

    # ---- kalıcılık ----
    def _persist_state(self) -> None:
        try:
            store.save_state({
                "portfolio": self.portfolio.to_persist(),
                "mode": self.executor.mode,
                "was_running": self._running.is_set(),
                "updated_at": now_ms(),
                # günlük koruma sayaçları (restart'a dayanıklı kill-switch)
                "risk_day": {
                    "day_index": int(time.time() // 86400),
                    "day_realized_pnl": self.rm.day_realized_pnl,
                    "spent_today": self._spending.spent_today(),
                    "day_start": self._day_start,
                },
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
            # binance_symbol: LLM'e danisilirken 24s istatistik + funding +
            # balina baglami bu sembol uzerinden cekilir (varsa).
            sig = generate_signal(cid, base, quote, closes,
                                  binance_symbol=_WL_BINANCE.get((cid, base)))
            signals.append(sig)
            store.save_signal(sig)
            self._emit({"type": "signal", "signal": sig.to_dict()})

            # --- rejim tespiti + strateji yönlendirme ---
            # İŞLEMLER strateji çatısından geçer: kullanıcı hangi stratejileri
            # açtıysa YALNIZCA onlar işlem açabilir; rejim yönlendirici (router)
            # mevcut piyasa rejimine uymayan stratejileri o tick için eler.
            tech = sig.technical
            regime, regime_weights = select_active(self.strategies, tech)
            self._last_regimes[f"{cid}:{base}"] = regime
            traded_this_token = False
            # Haber freni: guclu NEGATIF son-dakika haberde yeni ALIM acilmaz
            # (satis/cikislar etkilenmez). Izleyici kapaliysa None doner.
            try:
                from engine.marketdata.news_watcher import watcher as _nw
                buy_guard = _nw.guard(base)
            except Exception:  # noqa: BLE001
                buy_guard = None
            try:
                def _factory(_name, cash, _tech=tech, _closes=closes,
                             _cid=cid, _base=base, _quote=quote):
                    return StrategyContext(
                        base=_base, quote=_quote, chain_id=_cid, closes=_closes,
                        highs=_closes, lows=_closes, volumes=[0.0] * len(_closes),
                        tech=_tech, price=_closes[-1], cash_allocated=cash,
                        news_score=float((sig.breakdown or {}).get("newsScore", 0.0)))

                for ss in self.strategies.evaluate(_factory, total_equity):
                    if ss.action == "HOLD":
                        continue
                    # Hibrit stratejinin İŞLEM kararı, LLM+haber+ML katmanlı zengin
                    # sinyaldir (generate_signal) — plain kural kopyası değil.
                    if ss.strategy == "hybrid":
                        trade_sig = sig
                    else:
                        trade_sig = TradeSignal(
                            chain_id=cid, base=base, quote=quote,
                            action=ss.action, confidence=ss.confidence,
                            technical=tech, rationale=ss.reason,
                            source=f"strateji:{ss.strategy}")
                    status = "sinyal"
                    if ss.strategy not in regime_weights:
                        status = "rejim dışı"           # router eledi
                    elif trade_sig.confidence < self.risk.min_confidence:
                        status = "eşik altı"
                    elif ss.action == "BUY" and buy_guard:
                        status = f"haber freni: {buy_guard}"
                    elif (ss.action == "BUY"
                          and not self._cooldown.ready(f"{cid}:{base}")):
                        status = "cooldown"
                    elif traded_this_token:
                        status = "aynı tick'te işlendi"  # çifte giriş koruması
                    else:
                        cash_slice = regime_weights[ss.strategy] * min(
                            total_equity, self.portfolio.cash_usd + 1e-9)
                        filled = self._maybe_trade(
                            trade_sig, prices, cash_usd=cash_slice,
                            strategy=ss.strategy)
                        if filled:
                            status = "işlem açıldı" if ss.action == "BUY" else "işlem"
                            traded_this_token = True
                            if ss.action == "BUY":
                                self._cooldown.mark(f"{cid}:{base}")
                        else:
                            status = "risk reddi"
                    strat_signals.append({
                        "strategy": ss.strategy, "base": base, "quote": quote,
                        "chainId": cid, "action": ss.action,
                        "confidence": round(trade_sig.confidence, 3),
                        "reason": ss.reason, "regime": regime, "status": status,
                    })
            except Exception as e:  # noqa: BLE001
                log.debug("strateji değerlendirme hatası %s: %s", base, e)

        # --- stop-loss / take-profit: açık pozisyonları HER tick denetle ---
        self._check_exits(mark_prices, prices)

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

        override = getattr(self, "_seed_usd_override", None)
        usd = float(override) if override is not None else float(settings.paper_seed_usd)
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

    def _maybe_trade(self, sig, prices: list[PriceQuote],
                     cash_usd: float | None = None, strategy: str = "") -> bool:
        """Sinyali risk kapılarından geçirip emre dönüştürür.

        cash_usd: bu stratejiye tahsis edilen nakit dilimi (None = tüm nakit).
        Dönüş: emir 'filled' olduysa True.
        """
        # Sembol bazli ayarlanmis esik varsa ek bir kapi olarak uygula (additif).
        tuned = self._tuned.get(sig.base.upper())
        if tuned and sig.confidence < tuned.get("min_confidence", 0.0):
            return False
        avail_cash = self.portfolio.cash_usd if cash_usd is None else min(
            cash_usd, self.portfolio.cash_usd)
        decision = self.rm.evaluate(sig, self.portfolio.positions, avail_cash)
        if not decision.approved:
            return False
        # en likit DEX'i seç
        candidates = [q for q in prices if q.chain_id == sig.chain_id and q.base == sig.base]
        if not candidates and self.executor.mode == "paper":
            # RPC/DEX fiyatı yok (watchlist tokenı) → paper modda Binance
            # fiyatıyla simüle et. Live modda ASLA: gerçek emir DEX ister.
            px = sig.technical.price or 0.0
            if px > 0:
                candidates = [PriceQuote(
                    chain_id=sig.chain_id, dex="paper-binance", base=sig.base,
                    quote=sig.quote, price=px, liquidity_usd=0.0)]
        if not candidates:
            return False
        # Risk-tabanlı boyut tavanı: sermayenin RISK_PCT_PER_TRADE'i kadar
        # zararı 2×ATR stop mesafesinde göze alan nominal. Oynaklık yüksekse
        # pozisyon otomatik küçülür; risk kapısının boyutunu yalnızca KISAR.
        base_size = decision.size_usd
        equity_now = self.portfolio.equity_usd()
        atr = float(getattr(sig.technical, "atr", 0.0) or 0.0)
        if sig.action == "BUY" and self._risk_pct > 0 and atr > 0:
            cap = atr_based_size(equity_now, self._risk_pct,
                                 sig.technical.price or 0.0, atr)
            if cap > 0:
                base_size = min(base_size, cap)
            if base_size < 10:
                self._emit({"type": "log", "level": "info",
                            "message": (f"{sig.base}: oynaklık yüksek — ATR boyutu "
                                        f"(${base_size:.0f}) çok küçük, alım atlandı")})
                return False

        # Akıllı yürütme: etkin maliyeti en düşük DEX + drawdown'a göre boyut.
        plan = smart_exec.plan_execution(
            candidates, base_size, sig.action,
            equity_now, max(self._peak_equity, equity_now))
        if plan is None:
            best = max(candidates, key=lambda q: q.liquidity_usd)
            exec_size = base_size
            exec_note = ""
        else:
            best = next((q for q in candidates if q.dex == plan.dex), candidates[0])
            exec_size = plan.size_usd
            exec_note = plan.note
            if plan.derisk_factor <= 0.0:
                self._emit({"type": "log", "level": "warn",
                            "message": "Drawdown sert eşiği - yeni alım durduruldu"})
                if sig.action == "BUY":
                    return False

        # live modda gas tavanı kontrolü
        if self.executor.mode == "live":
            ok, gwei = self.rm.gas_ok(sig.chain_id)
            if not ok:
                self._emit({"type": "log", "level": "warn",
                            "message": f"Gas tavanı ({gwei:.0f} gwei) - işlem atlandı"})
                return False
            # günlük harcama limiti (yalnızca yeni alım nosyoneli)
            if sig.action == "BUY" and not self._spending.allowed(exec_size):
                self._emit({"type": "log", "level": "warn",
                            "message": (f"Günlük harcama limiti ({self._spending.daily_limit_usd:.0f}$) "
                                        f"- kalan {self._spending.remaining():.0f}$, işlem atlandı")})
                return False

        amount = (exec_size / best.price) if sig.action == "BUY" else (
            self.portfolio.positions[f"{sig.chain_id}:{sig.base}"].amount)
        # İşlem türü + pozisyon etkisi (UI'da net görünsün):
        has_pos = f"{sig.chain_id}:{sig.base}" in self.portfolio.positions
        if sig.action == "BUY":
            act_tr, pos_action = "ALIM", ("pozisyona ekleme" if has_pos else "pozisyon açılışı")
        else:
            act_tr, pos_action = "SATIM", "pozisyon kapanışı"
        # "Neden al/sat" gerekçesi: işlem türü + pozisyon + strateji + güven + gösterge.
        strat_note = f"strateji: {strategy} · " if strategy else ""
        reason = (f"{act_tr} · {pos_action} · {strat_note}"
                  f"güven %{round(sig.confidence * 100)} · "
                  f"{sig.source} · {sig.rationale}"
                  + (f" · {exec_note}" if exec_note else ""))
        order = TradeOrder(mode=self.executor.mode, chain_id=sig.chain_id,
                           dex=best.dex, base=sig.base, quote=sig.quote,
                           side=sig.action, amount=amount, price=best.price,
                           signal_id=sig.id, reason=reason,
                           venue_type="dex")  # zincir-üstü DEX (gas dahil); CEX değil
        prev_realized = self.portfolio.realized_pnl_usd
        filled = self.executor.execute(order)
        if filled.status == "filled" and filled.side == "SELL":
            # DELTA kaydet (kümülatif değil): günlük kill-switch sayacı doğru işler.
            self.rm.record_realized(self.portfolio.realized_pnl_usd - prev_realized)
        store.save_trade(filled)
        if filled.status == "filled":
            key = f"{sig.chain_id}:{sig.base}"
            if filled.side == "BUY":
                pos = self.portfolio.positions.get(key)
                if pos is not None and atr > 0:
                    st = self._exit_states.get(key)
                    if st is None:
                        self._exit_states[key] = ExitState(
                            entry=pos.avg_entry, atr=atr)
                    else:  # pozisyona ekleme: girişi/ATR'yi güncelle
                        st.entry = pos.avg_entry
                        st.atr = atr
            elif key not in self.portfolio.positions:
                self._exit_states.pop(key, None)  # pozisyon kapandı
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
        return filled.status == "filled"

    def _check_exits(self, mark_prices: dict[str, float],
                     prices: list[PriceQuote]) -> None:
        """Açık pozisyonlarda çıkış kurallarını HER tick uygular.

        EXIT_STYLE=atr (varsayılan): ATR tabanlı trailing stop + başabaşa çekme
        + kademeli kâr alma (TP1'de pozisyonun yarısı) — oynaklığa uyarlıdır ve
        kârı korur. Sabit %5 stop, felaket freni olarak her durumda devrededir.
        EXIT_STYLE=fixed: eski sabit %5 SL / %10 TP davranışı.
        """
        for key, pos in list(self.portfolio.positions.items()):
            if pos.amount <= 0:
                continue  # spot long-only; short çıkışları perp katmanında
            price = mark_prices.get(key)
            if not price:
                hist = self._history.get(f"{pos.chain_id}:agg:{pos.base}")
                price = hist[-1] if hist else None
            if not price or price <= 0:
                continue

            hit: str | None = None
            sell_amount = pos.amount
            st = self._exit_states.get(key) if self._exit_style == "atr" else None
            if st is not None and st.atr > 0:
                d = self._exit_mgr.update(st, price)
                if d.action == "EXIT":
                    hit = d.reason
                elif d.action == "PARTIAL":
                    hit = d.reason
                    sell_amount = pos.amount * d.fraction
                else:
                    # Emniyet freni: ATR stopu ne derse desin sabit %5'lik
                    # felaket stopu bağımsız çalışır (yarı kalan pozisyon dahil).
                    fb = self.rm.check_stop_take(pos, price)
                    if fb == "stop-loss":
                        hit = fb
            else:
                hit = self.rm.check_stop_take(pos, price)
            if not hit or sell_amount <= 0:
                continue

            candidates = [q for q in prices
                          if q.chain_id == pos.chain_id and q.base == pos.base]
            best = max(candidates, key=lambda q: q.liquidity_usd) if candidates else None
            # Çıkış DEX'i: canlı modda GERÇEK bir DEX adı şart (sahte
            # "paper-binance" live broker'da bulunamaz). Teklif yoksa
            # pozisyonun açıldığı DEX'e, o da yoksa zincirin ilk DEX'ine düş.
            exit_dex = best.dex if best else (pos.dex or "paper-binance")
            if self.executor.mode == "live" and best is None:
                from engine.config.chains import get_chain
                try:
                    ch = get_chain(pos.chain_id)
                    valid = {d.name for d in ch.dexes}
                    if exit_dex not in valid and ch.dexes:
                        exit_dex = ch.dexes[0].name
                except Exception:  # noqa: BLE001
                    pass
            closing = sell_amount >= pos.amount * 0.999
            order = TradeOrder(
                mode=self.executor.mode, chain_id=pos.chain_id,
                dex=exit_dex,
                base=pos.base, quote="USD", side="SELL",
                amount=sell_amount, price=best.price if best else price,
                reason=(f"SATIM · {'pozisyon kapanışı' if closing else 'kısmi kâr alma'}"
                        f" · {hit} (giriş ${pos.avg_entry:,.2f} → ${price:,.2f})"),
                venue_type="dex")
            prev_realized = self.portfolio.realized_pnl_usd
            filled = self.executor.execute(order)
            if filled.status == "filled":
                self.rm.record_realized(
                    self.portfolio.realized_pnl_usd - prev_realized)
                if key not in self.portfolio.positions:
                    self._exit_states.pop(key, None)
                self._persist_state()
            store.save_trade(filled)
            self._emit({"type": "trade", "order": filled.to_api()})
            self._emit({"type": "log", "level": "info",
                        "message": (f"{hit} tetiklendi → {pos.base} "
                                    f"{'kapatıldı' if closing else 'kısmen satıldı'}")})

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
            self._preset = "custom"  # elle ayar → profil "özel"
            self._save_strategy_config()
            self._save_risk_config()
        return {"ok": ok, "strategies": self.get_strategies()}

    def get_strategies(self):
        """Aktif strateji yapılandırması + mevcut (kayıtlı) stratejiler."""
        from engine.strategy import registry
        import engine.strategy.strategies  # noqa: F401
        return {"active": self.strategies.describe(),
                "available": registry.available(),
                "catalog": self.strategies.available_info(),
                # token -> son tespit edilen piyasa rejimi (UI: rejim rozeti)
                "regimes": dict(self._last_regimes),
                "min_confidence": self.risk.min_confidence,
                "preset": self._preset,
                "presets": {k: {"title": v["title"],
                                "min_confidence": v["min_confidence"]}
                            for k, v in STRATEGY_PRESETS.items()}}

    def get_portfolio(self): return self.portfolio.snapshot()
    def get_trades(self, limit=100): return store.recent_trades(limit)

    def clear_trades(self) -> dict:
        """İşlem geçmişini siler. Bellekteki son sinyal listesine dokunmaz."""
        deleted = store.clear_trades()
        return {"ok": True, "deleted": deleted}

    def reset_paper(self, seed_usd: float | None = None,
                    cash_only: bool = False) -> dict:
        """Paper portföyü sıfırla ve İSTENEN tutarla yeniden başlat.

        cash_only=False: tutar ETH tohumuna çevrilir (ilk tick'te).
        cash_only=True:  portföy tamamen NAKİT başlar (tohum yok).
        Live modda ÇALIŞMAZ (gerçek bakiye korunur). İşlem geçmişi + equity
        eğrisi temizlenir.
        """
        if self.executor.mode == "live":
            return {"ok": False, "reason": "Live modda sıfırlama yapılmaz"}
        usd = float(seed_usd) if seed_usd is not None else float(settings.paper_seed_usd)
        if usd <= 0:
            return {"ok": False, "reason": "Tutar pozitif olmalı"}
        # Portföyü YERİNDE sıfırla (broker referansları geçerli kalsın).
        self.portfolio.positions.clear()
        self.portfolio.cash_usd = usd
        self.portfolio.realized_pnl_usd = 0.0
        self.rm.reset_daily()
        self._peak_equity = usd
        self._exit_states.clear()
        self._seed_pending = (not cash_only) and usd > 0
        self._seed_usd_override = usd if self._seed_pending else None
        store.clear_trades()
        try:
            store.clear_equity()
        except Exception:
            pass
        self._persist_state()
        asset = "nakit (USD)" if cash_only else settings.paper_seed_asset
        self._emit({"type": "log", "level": "info",
                    "message": (f"Paper portföy sıfırlandı → ${usd:,.0f} "
                                f"{asset} ile başlatılıyor")})
        return {"ok": True, "seed_usd": usd,
                "asset": "USD" if cash_only else settings.paper_seed_asset}

    def get_equity_curve(self): return store.equity_curve()

    # ---- kullanıcı risk ayarları (giriş eşiği + genel strateji profili) ----
    def _risk_cfg_path(self) -> str:
        import os
        return os.path.join(os.environ.get("DATA_DIR", "data"), "risk.json")

    def _load_risk_config(self) -> None:
        import json
        import os
        path = self._risk_cfg_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f)
            mc = float(cfg.get("min_confidence", self.risk.min_confidence))
            self._apply_min_confidence(mc)
            self._preset = str(cfg.get("preset", "custom"))
        except Exception as e:  # noqa: BLE001
            log.warning("risk config yuklenemedi: %s", e)

    def _save_risk_config(self) -> None:
        import json
        import os
        path = self._risk_cfg_path()
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"min_confidence": self.risk.min_confidence,
                           "preset": self._preset}, f, indent=2)
        except Exception as e:  # noqa: BLE001
            log.warning("risk config kaydedilemedi: %s", e)

    def _apply_min_confidence(self, value: float) -> float:
        """Eşiği tüm risk tüketicilerine uygula (0.40..0.99 aralığına kırpılır)."""
        import dataclasses
        v = max(0.40, min(0.99, float(value)))
        self.risk = dataclasses.replace(self.risk, min_confidence=v)
        self.rm.risk = self.risk
        self.executor.risk = self.risk
        return v

    def set_min_confidence(self, value: float, _from_preset: bool = False) -> dict:
        """Pozisyon giriş eşiğini çalışma anında ayarla; kalıcı kaydet."""
        v = self._apply_min_confidence(value)
        if not _from_preset:
            self._preset = "custom"  # elle ayar → profil "özel"
        self._save_risk_config()
        self._emit({"type": "log", "level": "info",
                    "message": f"Pozisyon giriş eşiği → %{round(v * 100)}"})
        return {"ok": True, "min_confidence": v, "preset": self._preset}

    def apply_preset(self, name: str) -> dict:
        """Genel strateji profili uygula: ağırlıklar + giriş eşiği tek adımda."""
        preset = STRATEGY_PRESETS.get(name)
        if preset is None:
            return {"ok": False,
                    "reason": f"Bilinmeyen profil: {name}",
                    "available": list(STRATEGY_PRESETS)}
        for sname, w in preset["weights"].items():
            self.strategies.set_weight(sname, float(w))
            self.strategies.set_enabled(sname, True)
        for sname in preset["disabled"]:
            self.strategies.set_enabled(sname, False)
        self._save_strategy_config()
        self._apply_min_confidence(float(preset["min_confidence"]))
        self._preset = name
        self._save_risk_config()
        self._emit({"type": "log", "level": "info",
                    "message": (f"Strateji profili → {preset['title']} "
                                f"(eşik %{round(self.risk.min_confidence * 100)})")})
        return {"ok": True, "preset": name, "strategies": self.get_strategies()}

    # ---- AI destekli strateji danışmanı ----
    def get_strategy_advice(self) -> dict:
        """Strateji performansı + rejimden AI (veya kural-tabanlı) öneri üretir.

        Öneri UYGULANMAZ; UI gösterir, kullanıcı onaylarsa apply çağrılır.
        """
        from engine.strategy import advisor
        trades = store.recent_trades(100000)
        stats = advisor.per_strategy_stats(trades)
        config = self.strategies.to_config()
        regimes = advisor.regime_summary(self._last_regimes)
        try:
            perf = self.get_performance()
        except Exception:  # noqa: BLE001
            perf = None
        advice = advisor.get_advice(stats, config, regimes,
                                    self.risk.min_confidence, perf)
        # UI karşılaştırması için mevcut durumu iliştir
        current = {c["name"]: c for c in config}
        for s in advice["strategies"]:
            cur = current.get(s["name"], {})
            s["current_enabled"] = bool(cur.get("enabled", False))
            s["current_weight"] = float(cur.get("weight", 0.0))
        advice["current_min_confidence"] = self.risk.min_confidence
        advice["stats"] = stats
        return advice

    def apply_strategy_advice(self, strategies: list[dict],
                              min_confidence: float | None = None) -> dict:
        """Onaylanan öneriyi uygular (ağırlık/aç-kapa + eşik); kalıcı kaydeder."""
        from engine.strategy import registry as _reg
        import engine.strategy.strategies  # noqa: F401
        applied = 0
        for item in strategies or []:
            name = str(item.get("name", ""))
            if not _reg.is_registered(name):
                continue
            if "weight" in item and item["weight"] is not None:
                self.strategies.set_weight(name, float(item["weight"]))
            if "enabled" in item and item["enabled"] is not None:
                self.strategies.set_enabled(name, bool(item["enabled"]))
            applied += 1
        self._save_strategy_config()
        if min_confidence is not None:
            self._apply_min_confidence(float(min_confidence))
        self._preset = "ai"  # profil rozeti: AI önerisiyle ayarlandı
        self._save_risk_config()
        self._emit({"type": "log", "level": "info",
                    "message": (f"AI strateji önerisi uygulandı "
                                f"({applied} strateji, eşik "
                                f"%{round(self.risk.min_confidence * 100)})")})
        return {"ok": True, "applied": applied,
                "strategies": self.get_strategies()}

    def live_preflight(self) -> dict:
        """Canlıya geçiş ÖN-UÇUŞ kontrolü — yalnızca OKUMA, hiçbir tx göndermez.

        Kontroller: imzalayıcı cüzdan, zincir başına RPC + gas + bakiyeler,
        LLM yapılandırması, risk limitleri. UI, Live'a geçmeden bunu gösterir.
        """
        from engine.config.chains import CHAINS
        from engine.dex.abis import ERC20_ABI
        from engine.trading import wallet as wallet_mod
        from engine.web3x.provider import cs, get_web3

        w = wallet_mod.get_wallet()
        addr = w.get("address") if w.get("source") == "signer" else None

        chains_out: list[dict] = []
        any_rpc = False
        funded = False
        for cid in self.enabled_chains:
            ch = CHAINS.get(cid)
            if ch is None:
                continue
            row: dict = {"chain_id": cid, "name": ch.name, "rpc_ok": False,
                         "gas_gwei": None, "gas_ok": None,
                         "stable_symbol": ch.stable.symbol,
                         "stable_balance": None, "native_symbol": ch.native_symbol,
                         "native_balance": None}
            try:
                w3 = get_web3(cid)
                if w3 is not None and w3.is_connected():
                    row["rpc_ok"] = True
                    any_rpc = True
                    gwei = w3.eth.gas_price / 1e9
                    row["gas_gwei"] = round(gwei, 2)
                    row["gas_ok"] = gwei <= self.risk.max_gas_gwei
                    if addr:
                        erc20 = w3.eth.contract(address=cs(ch.stable.address),
                                                abi=ERC20_ABI)
                        bal = erc20.functions.balanceOf(cs(addr)).call()
                        row["stable_balance"] = round(
                            bal / 10 ** ch.stable.decimals, 2)
                        row["native_balance"] = round(
                            w3.eth.get_balance(cs(addr)) / 1e18, 6)
                        if (row["stable_balance"] or 0) >= 10 and \
                                (row["native_balance"] or 0) > 0:
                            funded = True
            except Exception as e:  # noqa: BLE001
                row["error"] = str(e)[:150]
            chains_out.append(row)

        llm_key = {"deepseek": settings.deepseek_api_key,
                   "anthropic": settings.anthropic_api_key,
                   "openai": settings.openai_api_key}.get(settings.llm_provider, "")
        checks = {
            "signer_wallet": addr is not None,
            "rpc_available": any_rpc,
            "funded_chain": funded,
            "llm_ready": settings.llm_provider == "none" or bool(llm_key),
            "kill_switch_clear": not self.rm.kill_switch_triggered(),
        }
        return {
            "ready": all(checks.values()),
            "checks": checks,
            "wallet_address": addr,
            "chains": chains_out,
            "limits": {
                "min_confidence": self.risk.min_confidence,
                "max_position_usd": self.risk.max_position_usd,
                "max_daily_loss_usd": self.risk.max_daily_loss_usd,
                "max_gas_gwei": self.risk.max_gas_gwei,
                "daily_spend_limit_usd": self._spending.daily_limit_usd,
                "slippage_bps": self.risk.slippage_bps,
            },
            "llm_provider": settings.llm_provider,
        }

    def get_performance(self) -> dict:
        """Risk-ayarlı performans özeti: Sharpe, Sortino, MaxDD, Calmar,
        kazanma oranı, profit factor, expectancy (equity + işlem geçmişinden)."""
        from engine.analytics import metrics as M
        eq = [row["equity"] for row in store.equity_curve(2000)]
        trades = store.recent_trades(100000)
        pnls = M.pnls_from_trades(trades)
        # Yıllıklandırma: equity örnekleri tick aralığıyla yazılır.
        poll_s = max(self.poll_interval, 1.0)
        ppy = int(365 * 24 * 3600 / poll_s)
        out = M.summarize(eq, pnls, periods_per_year=ppy)
        out.update({
            "equity_usd": round(self.portfolio.equity_usd(), 2),
            "cash_usd": round(self.portfolio.cash_usd, 2),
            "realized_pnl_usd": round(self.portfolio.realized_pnl_usd, 2),
            "day_realized_pnl_usd": round(self.rm.day_realized_pnl, 2),
            "open_positions": len(self.portfolio.positions),
            "exit_style": self._exit_style,
            "risk_pct_per_trade": self._risk_pct,
        })
        return out

    def active_symbol(self) -> str:
        """Chart'ın izleyeceği sembol: en son sinyal -> açık pozisyon -> ETH."""
        if self._latest_signals:
            return self._latest_signals[-1].base
        if self.portfolio.positions:
            return next(iter(self.portfolio.positions.values())).base
        return "ETH"


bot = TradingBot()
