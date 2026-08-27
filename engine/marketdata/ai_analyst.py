"""Otonom AI analist — kendi kendine tarar, kararını yazar, (izin varsa) işler.

İki tetikleyici:
  1. **Periyodik** — her `ANALYST_INTERVAL_MIN` dakikada (varsayılan 30) izleme
     listesindeki her sembol için tam analiz.
  2. **Olay** — arada bir (30 sn) ucuz kontroller yapılır; şu üç durumda ilgili
     sembol SIRA BEKLEMEDEN analiz edilir:
       · yapı skoru (intel bias) sert değişti  → `ANALYST_BIAS_DELTA` (0.25)
       · son-dakika haber akışa düştü          → news_watcher.breaking
       · likidasyon kaskadı / funding sıçraması → derivatives.summary

Sonuçlar bellekte + `data/ai_reports.json` içinde tutulur, WebSocket'e
`ai_analysis` olayı olarak yayınlanır ve `/analyst/auto/*` uçlarından okunur.

**Otopilot**: `HL_AI_AUTOPILOT=1` iken analistin ürettiği işlem planı
(`llm.trade`) Hyperliquid risk kapılarından geçirilir; onaylanırsa emir
gönderilir. Kapılar `engine/risk/hl_risk.py` içindedir ve elle emirle AYNI
kapılardır — AI'ın ayrıcalığı yoktur, aksine daha dar tavanları vardır.

Kapatmak için: ANALYST_AUTO=0 (tarama), HL_AI_AUTOPILOT=0 (işlem).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Callable

log = logging.getLogger("ai_analyst")

_EVENT_CHECK_S = 30.0
_MAX_REPORTS = 60


def _num(name: str, default: float, lo: float, hi: float) -> float:
    try:
        v = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


def _flag(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip().lower() not in ("0", "false", "no")


def watchlist() -> list[str]:
    """Taranacak semboller. .env ANALYST_WATCHLIST, yoksa makul bir varsayılan."""
    raw = os.getenv("ANALYST_WATCHLIST", "")
    syms = [s.strip().upper() for s in raw.split(",") if s.strip()]
    if syms:
        return syms[:20]
    return ["BTC", "ETH", "SOL", "HYPE", "BNB"]


class AIAnalyst:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._emit: Callable[[dict], None] | None = None
        self._lock = threading.RLock()
        self.reports: dict[str, dict] = {}      # sembol -> son rapor (özet)
        self.log: list[dict] = []               # son kararlar (zaman sıralı)
        self.last_scan: float = 0.0
        self.scans: int = 0
        self.errors: int = 0
        self.last_error: str | None = None
        self._last_bias: float | None = None
        self._queue: list[tuple[str, str]] = []  # (sembol, tetikleyici)
        self._loaded = False

    # ------------------------------------------------------------ kalıcılık
    def _path(self) -> str:
        return os.path.join(os.environ.get("DATA_DIR", "data"), "ai_reports.json")

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            with open(self._path(), encoding="utf-8") as f:
                raw = json.load(f)
            self.reports = raw.get("reports") or {}
            self.log = (raw.get("log") or [])[-_MAX_REPORTS:]
        except Exception:  # noqa: BLE001
            pass

    def _save(self) -> None:
        try:
            p = self._path()
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"reports": self.reports, "log": self.log[-_MAX_REPORTS:]},
                          f, ensure_ascii=False)
            os.replace(tmp, p)
        except Exception as e:  # noqa: BLE001
            log.warning("ai raporları yazılamadı: %s", e)

    # -------------------------------------------------------------- kontrol
    @staticmethod
    def enabled() -> bool:
        return _flag("ANALYST_AUTO", "0")

    @staticmethod
    def interval_s() -> float:
        return _num("ANALYST_INTERVAL_MIN", 30, 5, 1440) * 60

    def start(self, emit: Callable[[dict], None] | None = None) -> bool:
        if not self.enabled():
            log.info("otonom analist kapalı (ANALYST_AUTO=0)")
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._emit = emit
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="ai-analyst",
                                        daemon=True)
        self._thread.start()
        log.info("otonom analist başladı (%.0f dk, %d sembol)",
                 self.interval_s() / 60, len(watchlist()))
        return True

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> dict:
        from engine.risk import hl_risk
        return {
            "enabled": self.enabled(),
            "running": bool(self._thread and self._thread.is_alive()),
            "interval_min": round(self.interval_s() / 60),
            "watchlist": watchlist(),
            "depth": os.getenv("ANALYST_DEPTH", "normal"),
            "scans": self.scans, "errors": self.errors,
            "last_scan": self.last_scan, "last_error": self.last_error,
            "queued": [s for s, _ in self._queue],
            "autopilot": hl_risk.limits()["ai_enabled"],
            "autopilot_limits": {
                k: v for k, v in hl_risk.limits(for_ai=True).items()
                if k.startswith(("max_", "ai_", "min_", "cooldown"))
            },
        }

    # ------------------------------------------------------------ tetikleme
    def request(self, symbol: str, trigger: str = "manual") -> None:
        """Bir sembolü sıraya al (olay tetikleyicileri ve UI bunu çağırır)."""
        sym = symbol.upper()
        with self._lock:
            if sym not in [s for s, _ in self._queue]:
                self._queue.append((sym, trigger))

    def _detect_events(self) -> None:
        """Ucuz kontroller: yapı skoru sıçraması, son-dakika haber, kaskad."""
        # 1) intel yapı skoru sert değişti mi?
        try:
            from engine.marketdata.intel import bias as intel_bias
            b = intel_bias.market_bias()
            if b.get("ok"):
                cur = float(b["score"])
                if self._last_bias is not None:
                    delta = abs(cur - self._last_bias)
                    if delta >= _num("ANALYST_BIAS_DELTA", 0.25, 0.05, 2.0):
                        log.info("yapı skoru sıçradı (%.2f → %.2f) — tarama tetiklendi",
                                 self._last_bias, cur)
                        for s in watchlist()[:3]:
                            self.request(s, "yapi-skoru")
                self._last_bias = cur
        except Exception:  # noqa: BLE001
            pass

        # 2) son-dakika haber
        try:
            from engine.marketdata.news_watcher import watcher
            for sym in watchlist():
                fresh = watcher.fresh_bias(sym)
                if fresh.get("breaking"):
                    self.request(sym, "son-dakika-haber")
        except Exception:  # noqa: BLE001
            pass

        # 3) likidasyon kaskadı / aşırı funding
        try:
            from engine.marketdata import derivatives
            for sym in watchlist()[:5]:
                d = derivatives.summary(sym)
                sq = (d.get("squeeze") or {}) if d.get("ok") else {}
                if sq.get("cascade") or abs(d.get("funding", 0.0)) >= 0.001:
                    self.request(sym, "turev-uc-deger")
        except Exception:  # noqa: BLE001
            pass

    # ---------------------------------------------------------------- analiz
    def analyze_one(self, symbol: str, trigger: str = "manual") -> dict:
        """Tek sembol için tam analiz + (izin varsa) otopilot kararı."""
        from engine.marketdata import analyst as analyst_mod
        sym = symbol.upper()
        t0 = time.time()
        try:
            report = analyst_mod.analyze(sym, depth=os.getenv("ANALYST_DEPTH"))
        except Exception as e:  # noqa: BLE001
            self.errors += 1
            self.last_error = f"{sym}: {str(e)[:160]}"
            log.warning("otonom analiz hatası %s: %s", sym, e)
            return {"ok": False, "symbol": sym, "error": str(e)[:160]}

        llm_out = report.get("llm") or {}
        summary = {
            "symbol": sym,
            "ts": report.get("ts"),
            "trigger": trigger,
            "bias": llm_out.get("bias"),
            "confidence": llm_out.get("confidence"),
            "sentiment": llm_out.get("sentiment"),
            "horizon": llm_out.get("horizon"),
            "summary": llm_out.get("summary"),
            "macro_view": llm_out.get("macro_view"),
            "flow_view": llm_out.get("flow_view"),
            "chart_view": llm_out.get("chart_view"),
            "crowd_view": llm_out.get("crowd_view"),
            "levels": llm_out.get("levels"),
            "scenarios": llm_out.get("scenarios"),
            "conflicts": llm_out.get("conflicts"),
            "risks": llm_out.get("risks"),
            "trade": llm_out.get("trade"),
            "llm_used": report.get("llm_used", False),
            "heuristic": bool(llm_out.get("heuristic")),
            "took_s": round(time.time() - t0, 1),
        }

        # Karar HER ZAMAN üretilir (otopilot kapalıyken bile) — kullanıcı
        # "AI ne düşündü, neden açılmadı" sorusunu arayüzde görebilsin.
        try:
            decision = self.decide(summary)
        except Exception as e:  # noqa: BLE001
            log.warning("karar üretilemedi %s: %s", sym, e)
            decision = {"state": "BLOCKED", "label": "GİRME", "verdict": "avoid",
                        "symbol": sym, "reason": f"karar hatası: {str(e)[:120]}",
                        "autopilot": False, "executed": False,
                        "ts": int(time.time() * 1000)}
        summary["decision"] = decision
        # Geriye dönük uyumluluk: eski alan adı hâlâ dolduruluyor.
        summary["autopilot"] = {"acted": bool(decision.get("executed")),
                                "reason": decision.get("reason", ""),
                                "result": decision.get("result"),
                                "decision": decision.get("gate")}

        with self._lock:
            self._load()
            self.reports[sym] = summary
            self.log.append(summary)
            self.log = self.log[-_MAX_REPORTS:]
            self._save()
        if self._emit:
            try:
                self._emit({"type": "ai_analysis", **summary})
            except Exception:  # noqa: BLE001
                pass
        return summary

    # -------------------------------------------------------------- otopilot
    def decide(self, summary: dict, execute: bool | None = None) -> dict:
        """Analistin planını risk kapılarından geçir ve KARARI döndür.

        Otopilot kapalı olsa bile HER ZAMAN çalışır: kullanıcı "AI bu pair için
        ne düşündü, neden işlem açılmadı" sorusunun cevabını arayüzde görür.
        `execute=None` iken otopilot ayarına bakılır; `execute=False` kuru
        çalıştırmadır (hiçbir emir gönderilmez).

        Durum makinesi (state) → kullanıcıya gösterilen etiket:
            READY / ACTED        → POZİSYON AL
            NO_PLAN / LOW_CONF /
            HEURISTIC / NO_SCAN  → BEKLE
            BLOCKED / FAILED     → GİRME
        """
        from engine.risk import hl_risk
        from engine.trading.hl_broker import hl, normalize_symbol, universe

        sym = normalize_symbol(summary.get("symbol") or "")
        lim = hl_risk.limits(for_ai=True)
        autopilot = bool(lim["ai_enabled"])
        if execute is None:
            execute = autopilot

        trade = summary.get("trade") or {}
        side = str(trade.get("side") or "YOK").upper()
        conf = float(summary.get("confidence") or 0.0)

        def out(state: str, reason: str, **extra) -> dict:
            labels = {
                "READY": "POZİSYON AL", "ACTED": "POZİSYON ALINDI",
                "NO_PLAN": "BEKLE", "LOW_CONF": "BEKLE", "HEURISTIC": "BEKLE",
                "NO_SCAN": "BEKLE", "BLOCKED": "GİRME", "FAILED": "GİRME",
            }
            d = {
                "state": state,
                "label": labels.get(state, "BEKLE"),
                "verdict": ("enter" if state in ("READY", "ACTED")
                            else "avoid" if state in ("BLOCKED", "FAILED")
                            else "wait"),
                "symbol": sym, "side": side if side in ("LONG", "SHORT") else None,
                "confidence": round(conf, 3),
                "autopilot": autopilot, "executed": False,
                "reason": reason, "ts": int(time.time() * 1000),
            }
            d.update(extra)
            return d

        if side not in ("LONG", "SHORT"):
            return out("NO_PLAN", "Analist yön önermedi — kurulum net değil, bekle.")
        if summary.get("heuristic"):
            return out("HEURISTIC",
                       "LLM kapalı; sezgisel görüşle pozisyon açılmaz. "
                       ".env'de LLM_PROVIDER + API anahtarı tanımla.")
        if conf < lim["ai_min_confidence"]:
            return out("LOW_CONF",
                       f"Güven {conf:.2f} < eşik {lim['ai_min_confidence']:.2f} — bekle.")

        try:
            state = hl.state()
        except Exception as e:  # noqa: BLE001
            return out("BLOCKED", f"Hyperliquid durumu okunamadı: {str(e)[:110]}")

        # --- Kaldıraç: analistin KENDİ kararı, borsa ve risk tavanıyla kırpılır ---
        want_lev = int(trade.get("leverage") or 0)
        if want_lev <= 0:
            want_lev = 2  # analist vermediyse muhafazakâr taban
        exch_max = int((universe().get(sym) or {}).get("max_leverage", 20) or 20)
        want_lev = max(1, min(want_lev, exch_max))

        size_pct = max(1.0, min(50.0, float(trade.get("size_hint_pct") or 20)))
        free = float(state.get("cash_usd") or 0.0)
        notional = free * (size_pct / 100.0) * max(1, want_lev)

        intel_score = None
        try:
            from engine.marketdata.intel import bias as intel_bias
            b = intel_bias.combined(sym)
            if b.get("ok"):
                intel_score = float(b["score"])
        except Exception:  # noqa: BLE001
            pass

        # Otopilot şalteri EMİR GÖNDERMEYİ kontrol eder, risk değerlendirmesini
        # değil. Şalter kapalıyken de gerçek kapı sonucunu hesaplarız; yoksa
        # karar kartı her zaman "GİRME" gösterir ve kullanıcı yanlış anlar.
        gate = hl_risk.check(symbol=sym, side=side, notional_usd=notional,
                             leverage=want_lev, state=state, for_ai=True,
                             confidence=conf, intel_score=intel_score,
                             require_autopilot=bool(execute))
        plan = {
            "requested_leverage": want_lev,
            "exchange_max_leverage": exch_max,
            "size_hint_pct": size_pct,
            "requested_notional_usd": round(notional, 2),
            "approved_leverage": gate.leverage or None,
            "approved_notional_usd": round(gate.notional_usd, 2) if gate.approved else None,
            "leverage_note": trade.get("leverage_note"),
            "entry": trade.get("entry"), "stop": trade.get("stop"),
            "target": trade.get("target"),
            "rationale": trade.get("rationale"),
            "intel_score": intel_score,
        }

        if not gate.approved:
            log.info("AI kararı GİRME (%s %s): %s", sym, side, gate.reason)
            return out("BLOCKED", gate.reason, gate=gate.to_dict(), plan=plan)

        if not execute:
            why = ("Otopilot kapalı — kapı onayladı ama emir gönderilmedi. "
                   "Elle açabilir ya da .env'de HL_AI_AUTOPILOT=1 yapabilirsin."
                   if not autopilot else "Kuru çalıştırma — emir gönderilmedi.")
            return out("READY", why, gate=gate.to_dict(), plan=plan)

        res = hl.open(sym, side, notional_usd=gate.notional_usd,
                      leverage=gate.leverage, source="ai")
        if res.get("ok"):
            hl_risk.note_order(sym)
            log.info("AI POZİSYON AÇTI: %s %s %.2f$ %dx (%s)",
                     sym, side, gate.notional_usd, gate.leverage, res.get("mode"))
            d = out("ACTED", "Emir gönderildi.", gate=gate.to_dict(),
                    plan=plan, result=res)
            d["executed"] = True
            return d
        return out("FAILED", res.get("error") or "emir gönderilemedi",
                   gate=gate.to_dict(), plan=plan, result=res)

    def last_decision(self, symbol: str) -> dict:
        """Bir sembolün son kararı. Hiç taranmadıysa NO_SCAN döner."""
        from engine.trading.hl_broker import normalize_symbol
        sym = normalize_symbol(symbol)
        self._load()
        rep = self.reports.get(sym)
        if not rep:
            return {"state": "NO_SCAN", "label": "BEKLE", "verdict": "wait",
                    "symbol": sym, "side": None, "confidence": 0.0,
                    "autopilot": False, "executed": False,
                    "reason": "Bu pair için henüz analiz yapılmadı — “Bu pair’i tara”ya bas.",
                    "ts": 0}
        stored = rep.get("decision")
        if not stored:
            # Rapor var ama karar kaydı yok (eski ai_reports.json ya da karar
            # üretilirken hata olmuş). Kuru değerlendirmeyle ANINDA hesapla —
            # kart "karar üretilmedi" demek yerine gerçek durumu göstersin.
            try:
                stored = self.decide(rep, execute=False)
            except Exception as e:  # noqa: BLE001
                log.warning("karar yeniden hesaplanamadı %s: %s", sym, e)
                stored = {"state": "NO_PLAN", "label": "BEKLE", "verdict": "wait",
                          "reason": f"karar hesaplanamadı: {str(e)[:120]}"}
        d = dict(stored)
        d.setdefault("state", "NO_PLAN")
        d.setdefault("label", "BEKLE")
        d.setdefault("verdict", "wait")
        d.setdefault("symbol", sym)
        d.setdefault("confidence", float(rep.get("confidence") or 0.0))
        d.setdefault("autopilot", False)
        d.setdefault("executed", False)
        d.setdefault("ts", rep.get("ts") or 0)
        d["report"] = rep
        return d

    # ---------------------------------------------------------------- döngü
    def _loop(self) -> None:
        self._load()
        next_scan = 0.0
        while not self._stop.is_set():
            now = time.time()
            try:
                # Olay tetikleyicileri (ucuz)
                self._detect_events()

                # Sıradaki olay-tetikli işler
                with self._lock:
                    pending = self._queue[:3]
                    self._queue = self._queue[3:]
                for sym, trig in pending:
                    if self._stop.is_set():
                        break
                    self.analyze_one(sym, trig)

                # Periyodik tam tarama
                if now >= next_scan:
                    next_scan = now + self.interval_s()
                    for sym in watchlist():
                        if self._stop.is_set():
                            break
                        self.analyze_one(sym, "periyodik")
                    self.scans += 1
                    self.last_scan = time.time()
                    log.info("otonom tarama bitti: %d sembol", len(watchlist()))
            except Exception as e:  # noqa: BLE001
                self.errors += 1
                self.last_error = str(e)[:200]
                log.warning("otonom analist döngü hatası: %s", e)
            self._stop.wait(_EVENT_CHECK_S)


ai_analyst = AIAnalyst()
