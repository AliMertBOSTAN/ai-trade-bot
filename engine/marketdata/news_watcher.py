"""Sürekli haber izleyici — AI stratejistin "son dakika" gözü.

Arka planda düzenli aralıklarla (NEWS_POLL_INTERVAL_S, varsayılan 90 sn)
RSS akışlarını tarar; DAHA ÖNCE GÖRÜLMEMİŞ başlıkları yakalar ve her birini
değerlendirir:
  1) Anahtar-kelime katmanı (hızlı, LLM'siz): yön (-1..+1), etki (0..1),
     etkilenen tokenlar (alias tablosu) — her zaman çalışır.
  2) Opsiyonel LLM katmanı: yeni ve alakalı başlıklar varsa TEK toplu çağrıyla
     etkiyi netleştirir (NEWS_LLM_ASSESS=0 ile kapatılır). Bozuk/boş yanıtta
     anahtar-kelime sonucu geçerli kalır (fail-safe).

Sinyal motoru buradan iki şey okur:
  - fresh_bias(symbol): son NEWS_FRESH_WINDOW_MIN dakikadaki haberlerin
    recency-ağırlıklı skoru (karar güvenini modüle eder, LLM prompt'una girer)
  - guard(symbol): güçlü NEGATİF son-dakika haberde yeni ALIMI engelleyen fren

Hiçbir token/sembol sorulmaz: izleme evrenindeki tüm semboller alias
tablosuyla otomatik eşlenir; eşleşmeyen önemli haberler "piyasa geneli" sayılır.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from collections import deque
from typing import Callable

from engine.config.settings import settings
from engine.marketdata import news as market_news

log = logging.getLogger("marketdata.news_watcher")

# ---------------- yapılandırma (env) ----------------

def _poll_interval_s() -> float:
    """Tarama aralığı: 30..600 sn'ye kırpılır (varsayılan 90 = 1.5 dk)."""
    try:
        v = float(os.getenv("NEWS_POLL_INTERVAL_S", "90"))
    except ValueError:
        v = 90.0
    return max(30.0, min(600.0, v))


def _fresh_window_s() -> float:
    """Bir haberin 'taze' sayıldığı pencere (dk cinsinden env, sn döner)."""
    try:
        v = float(os.getenv("NEWS_FRESH_WINDOW_MIN", "45"))
    except ValueError:
        v = 45.0
    return max(5.0, min(240.0, v)) * 60.0


def _llm_assess_enabled() -> bool:
    return os.getenv("NEWS_LLM_ASSESS", "1").strip() not in ("0", "false", "no")


# ---------------- sembol eşleme (token sorulmaz) ----------------
# Watchlist sembolleri + yaygın takma adlar. WETH->ETH normalizasyonu
# sentiment() ile aynı mantık: baştaki W atılır.
_ALIASES: dict[str, tuple[str, ...]] = {
    "BTC": ("btc", "bitcoin", "wbtc", "satoshi"),
    "ETH": ("eth", "ethereum", "ether", "weth", "vitalik"),
    "BNB": ("bnb", "binance coin", "binance chain", "bsc"),
    "MATIC": ("matic", "polygon", "pol "),
    "ARB": ("arb ", "arbitrum"),
    "OP": ("op ", "optimism"),
    "LINK": ("link", "chainlink"),
    "UNI": ("uni ", "uniswap"),
    "SOL": ("sol ", "solana"),
    "XRP": ("xrp", "ripple"),
    "DOGE": ("doge", "dogecoin"),
}

# Piyasa GENELİNİ oynatan yüksek-etki terimleri (EN+TR) ve ağırlıkları.
_IMPACT_TERMS: dict[str, float] = {
    # düzenleyici / makro
    "sec": 0.5, "etf": 0.5, "fed": 0.5, "faiz": 0.5, "rate cut": 0.6,
    "rate hike": 0.6, "regulation": 0.4, "regülasyon": 0.4, "yasak": 0.6,
    "ban": 0.6, "lawsuit": 0.5, "dava": 0.5, "approval": 0.5, "onay": 0.5,
    # güvenlik / kriz
    "hack": 0.8, "hacked": 0.8, "exploit": 0.8, "saldırı": 0.7,
    "bankrupt": 0.8, "iflas": 0.8, "insolven": 0.7, "halted": 0.6,
    "depeg": 0.7, "rug": 0.6, "dolandırıcılık": 0.6, "fraud": 0.6,
    # piyasa yapısı
    "listing": 0.4, "listelen": 0.4, "delist": 0.6, "halving": 0.5,
    "liquidation": 0.5, "likidasyon": 0.5, "whale": 0.3, "balina": 0.3,
    "all-time high": 0.5, "ath": 0.4, "crash": 0.7, "çöküş": 0.7,
    "flash crash": 0.8, "outage": 0.5, "kesinti": 0.4,
}

# Genel kripto bağlamı: LLM'e gitmeye değer mi ön-filtresi için.
_CRYPTO_HINTS = ("crypto", "kripto", "coin", "token", "blockchain", "defi",
                 "stablecoin", "exchange", "borsa", "nft", "web3")

_BREAKING_IMPACT = 0.55       # bu eşik üstü etki = "son dakika" (breaking)
_GUARD_WINDOW_S = 15 * 60     # negatif breaking sonrası alım freni süresi
_GUARD_SCORE = -0.25          # frenin devreye girdiği skor eşiği
_LLM_MIN_GAP_S = 60.0         # iki LLM değerlendirmesi arası asgari süre
_MAX_LLM_ITEMS = 8            # tek toplu çağrıda değerlendirilecek başlık

ASSESS_SYSTEM = (
    "Sen bir kripto piyasa haber analistisin. Sana YENİ haber başlıkları "
    "verilir. Her başlık için piyasa etkisini değerlendir. SADECE şu JSON "
    'şemasında yanıt ver: {"items": [{"i": <indeks>, "score": -1.0..1.0, '
    '"impact": 0.0..1.0, "tokens": ["BTC", ...], "note": "kısa Türkçe not"}]}. '
    "score: fiyat yönü beklentisi (negatif=düşürücü). impact: haberin gücü "
    "(0=önemsiz, 1=piyasayı oynatır). tokens: doğrudan etkilenen semboller "
    "(genel makro haberse boş bırak). Emin değilsen impact düşük ver."
)


def _fingerprint(item: dict) -> str:
    """Haber kimliği: link varsa link, yoksa kaynak+başlık hash'i."""
    key = (item.get("link") or "").strip() or (
        f"{item.get('source', '')}|{item.get('title', '')}")
    return hashlib.sha1(key.encode("utf-8", errors="replace")).hexdigest()


def _match_tokens(text: str) -> list[str]:
    low = " " + text.lower() + " "
    out = []
    for sym, aliases in _ALIASES.items():
        if any(a in low for a in aliases):
            out.append(sym)
    return out


def _assess_keyword(item: dict) -> dict:
    """LLM'siz değerlendirme: yön + etki + etkilenen tokenlar."""
    text = f"{item.get('title', '')} {item.get('summary', '')}"
    bull, bear = market_news._score_text(text)
    total = bull + bear
    score = (bull - bear) / total if total else 0.0

    low = text.lower()
    impact = 0.0
    hits: list[str] = []
    for term, w in _IMPACT_TERMS.items():
        if term in low:
            impact = max(impact, w)
            hits.append(term)
    # Yön kelimesi yoğunluğu da etkiyi biraz besler (çok başlıkta geçen
    # sıradan kelimeler tek başına breaking yapmaz).
    impact = min(1.0, impact + min(0.2, 0.05 * total))

    tokens = _match_tokens(text)
    relevant = bool(tokens) or bool(hits) or any(h in low for h in _CRYPTO_HINTS)
    return {
        "score": round(score, 3),
        "impact": round(impact, 3),
        "tokens": tokens,
        "note": ("; ".join(hits[:3]) if hits else ""),
        "relevant": relevant,
        "assessor": "keyword",
    }


class NewsWatcher:
    """Thread'li haber izleyici. start() ile çalışır, stop() ile durur.

    Durum bellek-içidir; API/sinyal motoru kilitli erişimcilerden okur.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._seen: dict[str, float] = {}          # fingerprint -> ilk görülme
        self._events: deque[dict] = deque(maxlen=200)  # değerlendirilen haberler
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._emit: Callable[[dict], None] | None = None
        self._llm_last_ts = 0.0
        self._last_poll_ts = 0.0
        self._primed = False   # ilk tarama: mevcut arşiv "yeni" sayılmaz

    # ---------------- yaşam döngüsü ----------------
    def start(self, emit: Callable[[dict], None] | None = None) -> bool:
        """İzleyiciyi başlat (idempotent). emit: WS event köprüsü."""
        with self._lock:
            if emit is not None:
                self._emit = emit
            if self._running.is_set():
                return False
            self._running.set()
            self._thread = threading.Thread(target=self._loop, daemon=True,
                                            name="news-watcher")
            self._thread.start()
        log.info("Haber izleyici başladı (aralık %.0f sn, LLM=%s)",
                 _poll_interval_s(), "açık" if self._use_llm() else "kapalı")
        return True

    def stop(self) -> None:
        self._running.clear()

    def running(self) -> bool:
        return self._running.is_set()

    def _loop(self) -> None:
        while self._running.is_set():
            try:
                self.poll_once()
            except Exception as e:  # noqa: BLE001 — izleyici asla ölmez
                log.warning("haber taraması hatası: %s", e)
            # Kısa adımlarla uyu: stop() en geç ~1 sn'de etkili olur.
            deadline = time.time() + _poll_interval_s()
            while self._running.is_set() and time.time() < deadline:
                time.sleep(1.0)

    # ---------------- tarama ----------------
    def poll_once(self, now: float | None = None) -> list[dict]:
        """Tek tarama: yeni başlıkları bul, değerlendir, event yayınla.

        Dönüş: bu turda YENİ görülen (değerlendirilmiş) haberler.
        """
        now = time.time() if now is None else now
        # RSS cache TTL'i tarama aralığının altında kalsın ki her tur taze veri gelsin.
        ttl = max(15.0, _poll_interval_s() * 0.5)
        headlines = self._fetch(limit=40, ttl=ttl)

        fresh_items: list[dict] = []
        with self._lock:
            first_run = not self._primed
            for h in headlines:
                fp = _fingerprint(h)
                if fp in self._seen:
                    continue
                self._seen[fp] = now
                if first_run:
                    continue  # açılıştaki arşiv "yeni haber" değildir
                item = dict(h)
                item["first_seen"] = now
                fresh_items.append(item)
            self._primed = True
            self._last_poll_ts = now
            # seen sözlüğünü sınırla (en eskileri at)
            if len(self._seen) > 2000:
                for fp, _ts in sorted(self._seen.items(),
                                      key=lambda kv: kv[1])[:500]:
                    self._seen.pop(fp, None)

        if not fresh_items:
            return []

        # 1) anahtar-kelime değerlendirmesi (her zaman)
        for item in fresh_items:
            item.update(_assess_keyword(item))

        # 2) opsiyonel LLM netleştirmesi (tek toplu çağrı, fail-safe)
        relevant = [i for i in fresh_items if i["relevant"]]
        if relevant and self._use_llm() and (now - self._llm_last_ts) >= _LLM_MIN_GAP_S:
            self._llm_last_ts = now
            self._llm_refine(relevant[:_MAX_LLM_ITEMS])

        for item in fresh_items:
            item["breaking"] = bool(item["impact"] >= _BREAKING_IMPACT
                                    and item["relevant"])

        with self._lock:
            self._events.extend(fresh_items)

        self._publish(fresh_items)
        return fresh_items

    def _fetch(self, limit: int, ttl: float) -> list[dict]:
        """RSS başlıklarını çek (test edilebilirlik için ayrı metod)."""
        # fetch_headlines kendi içinde akış-başına fail-safe'tir.
        from engine.marketdata.http import get_text  # noqa: F401 (cache ttl notu)
        return market_news.fetch_headlines(limit=limit)

    def _use_llm(self) -> bool:
        if not _llm_assess_enabled() or settings.llm_provider == "none":
            return False
        key = {"deepseek": settings.deepseek_api_key,
               "anthropic": settings.anthropic_api_key,
               "openai": settings.openai_api_key}.get(settings.llm_provider, "")
        return bool(key)

    def _llm_refine(self, items: list[dict]) -> None:
        """Yeni başlıkları TEK LLM çağrısıyla netleştir; hatada dokunma."""
        from engine.signals import llm as llm_layer
        lines = ["YENİ HABER BAŞLIKLARI:"]
        for idx, item in enumerate(items):
            lines.append(f"{idx}. [{item.get('source', '?')}] {item.get('title', '')}"
                         + (f" — {item['summary'][:140]}" if item.get("summary") else ""))
        lines.append("Her başlık için JSON değerlendirmeni ver.")
        text = llm_layer.complete(ASSESS_SYSTEM, "\n".join(lines), max_tokens=500)
        if not text:
            return
        try:
            raw = json.loads(text[text.index("{"): text.rindex("}") + 1])
            rows = raw.get("items") or []
        except Exception:  # noqa: BLE001 — bozuk yanıt: keyword sonucu kalır
            log.debug("haber LLM yanıtı çözümlenemedi")
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                item = items[int(row.get("i", -1))]
            except (ValueError, TypeError, IndexError):
                continue
            try:
                score = max(-1.0, min(1.0, float(row.get("score", item["score"]))))
                impact = max(0.0, min(1.0, float(row.get("impact", item["impact"]))))
            except (TypeError, ValueError):
                continue
            toks = [str(t).upper().lstrip("W") for t in (row.get("tokens") or [])
                    if isinstance(t, (str,))]
            item["score"] = round(score, 3)
            # etki yalnızca YUKARI netleşebilir mi? Hayır: LLM 'önemsiz' de
            # diyebilmeli — ama tam sıfırlamasın (keyword tabanı korunur).
            item["impact"] = round(max(impact, item["impact"] * 0.4), 3)
            if toks:
                item["tokens"] = sorted(set(item["tokens"]) | set(toks))
            if row.get("note"):
                item["note"] = str(row["note"])[:160]
            item["assessor"] = "llm"

    def _publish(self, items: list[dict]) -> None:
        emit = self._emit
        for item in items:
            if emit is not None:
                try:
                    emit({"type": "news", "item": self._to_api(item)})
                except Exception:  # noqa: BLE001
                    pass
            if item["breaking"]:
                msg = (f"SON DAKİKA ({item.get('source', '?')}): "
                       f"{item.get('title', '')[:120]} · skor {item['score']:+.2f}"
                       + (f" · {', '.join(item['tokens'])}" if item["tokens"] else ""))
                log.warning(msg)
                if emit is not None:
                    try:
                        emit({"type": "log", "level": "warn", "message": msg})
                    except Exception:  # noqa: BLE001
                        pass

    # ---------------- okuma erişimcileri ----------------
    @staticmethod
    def _to_api(item: dict) -> dict:
        return {
            "source": item.get("source", ""),
            "title": item.get("title", ""),
            "link": item.get("link", ""),
            "ts": item.get("ts", 0),
            "firstSeen": int(item.get("first_seen", 0) * 1000),
            "score": item.get("score", 0.0),
            "impact": item.get("impact", 0.0),
            "tokens": item.get("tokens", []),
            "note": item.get("note", ""),
            "breaking": item.get("breaking", False),
            "assessor": item.get("assessor", "keyword"),
        }

    def recent_events(self, limit: int = 30) -> list[dict]:
        with self._lock:
            rows = list(self._events)[-limit:]
        return [self._to_api(i) for i in reversed(rows)]

    def _fresh(self, now: float) -> list[dict]:
        win = _fresh_window_s()
        with self._lock:
            return [i for i in self._events
                    if now - i.get("first_seen", 0) <= win]

    def fresh_bias(self, symbol: str, now: float | None = None) -> dict:
        """Sembol için taze haber bias'ı (recency-ağırlıklı).

        Sembole eşleşen haber yoksa yüksek-etkili PİYASA GENELİ haberlere
        düşer (yarı ağırlıkla). Dönüş:
          {score, count, breaking, headlines, market}
        """
        now = time.time() if now is None else now
        sym = symbol.upper().lstrip("W")
        fresh = self._fresh(now)
        matched = [i for i in fresh if sym in i.get("tokens", [])]
        market = False
        if not matched:
            matched = [i for i in fresh
                       if i.get("relevant") and not i.get("tokens")
                       and i.get("impact", 0.0) >= 0.3]
            market = True

        if not matched:
            return {"score": 0.0, "count": 0, "breaking": False,
                    "headlines": [], "market": market}

        win = _fresh_window_s()
        num = den = 0.0
        breaking = False
        for i in matched:
            age = max(0.0, now - i.get("first_seen", now))
            recency = max(0.1, 1.0 - age / win)      # yeni haber daha ağır
            w = recency * (0.3 + i.get("impact", 0.0))
            num += w * i.get("score", 0.0)
            den += w
            breaking = breaking or bool(i.get("breaking"))
        score = (num / den) if den else 0.0
        if market:
            score *= 0.5  # genel haber, sembole özgü haberden zayıf sinyaldir
        return {
            "score": round(score, 3),
            "count": len(matched),
            "breaking": breaking,
            "headlines": [i.get("title", "")[:140] for i in
                          sorted(matched, key=lambda x: -x.get("impact", 0))[:5]],
            "market": market,
        }

    def fresh_for(self, symbol: str, limit: int = 5,
                  now: float | None = None) -> list[dict]:
        """LLM prompt'u için taze başlıklar: sembole eşleşen + yüksek-etkili
        genel haberler, etkiye göre sıralı; age_min alanı eklidir."""
        now = time.time() if now is None else now
        sym = symbol.upper().lstrip("W")
        rows = [i for i in self._fresh(now)
                if sym in i.get("tokens", [])
                or (i.get("relevant") and not i.get("tokens")
                    and i.get("impact", 0.0) >= 0.3)]
        rows.sort(key=lambda i: (-float(i.get("impact", 0.0)),
                                 -float(i.get("first_seen", 0.0))))
        out = []
        for i in rows[:limit]:
            d = self._to_api(i)
            d["age_min"] = max(0.0, (now - i.get("first_seen", now)) / 60.0)
            out.append(d)
        return out

    def guard(self, symbol: str, now: float | None = None) -> str | None:
        """Yeni ALIM freni: son 15 dk'da güçlü NEGATİF breaking haber varsa
        gerekçe metni döner (yoksa None). Satışları asla engellemez."""
        now = time.time() if now is None else now
        sym = symbol.upper().lstrip("W")
        with self._lock:
            rows = [i for i in self._events
                    if now - i.get("first_seen", 0) <= _GUARD_WINDOW_S
                    and i.get("breaking")
                    and i.get("score", 0.0) <= _GUARD_SCORE
                    and (sym in i.get("tokens", []) or not i.get("tokens"))]
        if not rows:
            return None
        worst = min(rows, key=lambda i: i.get("score", 0.0))
        return (f"negatif son-dakika haber ({worst.get('source', '?')}: "
                f"{worst.get('title', '')[:80]})")

    def status(self) -> dict:
        with self._lock:
            events = len(self._events)
        return {
            "running": self.running(),
            "intervalS": _poll_interval_s(),
            "freshWindowMin": _fresh_window_s() / 60.0,
            "llmAssess": self._use_llm(),
            "lastPollMs": int(self._last_poll_ts * 1000),
            "eventCount": events,
        }


# Modül-seviyesi tekil izleyici (orchestrator/app/sinyal motoru paylaşır).
watcher = NewsWatcher()
