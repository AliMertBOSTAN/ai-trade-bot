"""Otonom araştırmacı — "sen sormadan da okur, araştırır, not çıkarır".

Arka planda çalışan ikinci bir göz. `news_watcher` SON DAKİKA haberi yakalar;
bu modül ise **planlı** çalışır:

  1. `calendar` takvimini tazeler (BLS ICS + FOMC + kullanıcı olayları).
  2. Taze haber başlıklarını takvime **olay olarak** işler — bir başlıkta
     ileri tarihli kripto olayı (unlock / ETF kararı / ağ yükseltmesi) geçiyorsa
     o tarih takvime eklenir.
  3. **Ön-araştırma:** yaklaşan (varsayılan 48 saat) yüksek-etkili her olay için
     ilgili haberleri toplar, piyasa bağlamını (fiyat/oynaklık/funding/OI)
     ölçer ve LLM ile senaryo notu üretir. Not, olay yaklaştıkça tazelenir.
  4. **Sonuç okuması:** olay geçtikten sonra (varsayılan 45 dk) açıklanan
     veriyi ve piyasa tepkisini okuyup notu tamamlar.

Her not: WS'e `research` olayı olarak yayınlanır, Telegram/Discord'a bildirilir
ve `data/research.json`'a kalıcı yazılır. LLM yoksa **sayısal not** üretilir —
akış hiçbir koşulda durmaz (fail-safe).

Ortam değişkenleri:
  RESEARCH_WATCHER=0            kapatır
  RESEARCH_INTERVAL_MIN=30      döngü periyodu (5..360)
  RESEARCH_LOOKAHEAD_H=48       kaç saat ilerisi araştırılır (2..336)
  RESEARCH_MIN_IMPORTANCE=0.6   bu önemin altındaki olay araştırılmaz
  RESEARCH_REFRESH_H=8          aynı olay en fazla bu sıklıkla yeniden araştırılır
  RESEARCH_LLM=1                LLM sentezi (0 = yalnızca sayısal not)
  RESEARCH_NOTIFY=1             Telegram/Discord bildirimi
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable

from engine.marketdata import calendar as cal_mod
from engine.marketdata.calendar import CalendarEvent, calendar

log = logging.getLogger("marketdata.researcher")

_STORE_PATH = os.path.join("data", "research.json")
_MAX_NOTES = 200

RESEARCH_SYSTEM = (
    "Sen bir kripto makro araştırmacısısın. Yaklaşan bir ekonomik veri "
    "açıklaması / olay için KISA ve KARARA DÖNÜK bir hazırlık notu yazarsın. "
    "Spekülasyon yapma, elindeki başlıklara ve sayısal bağlama dayan. "
    "SADECE şu JSON'u döndür: {\"ozet\": \"1-2 cümle\", \"beklenti\": \"piyasa "
    "ne bekliyor (bilinmiyorsa 'belirsiz')\", \"senaryolar\": [{\"kosul\": \"...\", "
    "\"etki\": \"BTC/ETH için yön ve kabaca büyüklük\"}], \"bias\": -1..1 arası "
    "sayı (olay ÖNCESİ risk iştahı), \"izlenecek\": [\"seviye/veri\"], "
    "\"risk\": \"en büyük ters senaryo\"}"
)

OUTCOME_SYSTEM = (
    "Sen bir kripto makro araştırmacısısın. AÇIKLANMIŞ bir ekonomik veri / olay "
    "sonrası kısa bir sonuç notu yazarsın. SADECE şu JSON'u döndür: "
    "{\"ozet\": \"açıklanan veri ve piyasa tepkisi, 1-2 cümle\", "
    "\"surpriz\": \"beklentiye göre yukarı/aşağı/nötr\", \"bias\": -1..1 sayı "
    "(veri SONRASI yön eğilimi), \"devam\": \"tepkinin kalıcılığı hakkında not\"}"
)


# ------------------------------------------------------------------ ayarlar

def _flag(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip().lower() not in ("0", "false", "no")


def _num(name: str, default: float, lo: float, hi: float) -> float:
    try:
        v = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


# -------------------------------------------------------------- veri tipi

@dataclass
class ResearchNote:
    event_id: str
    title: str
    event_ts: int
    phase: str                 # "pre" | "post"
    created_ms: int
    summary: str = ""
    expectation: str = ""
    scenarios: list[dict] = field(default_factory=list)
    watch: list[str] = field(default_factory=list)
    risk: str = ""
    bias: float = 0.0
    surprise: str = ""
    headlines: list[dict] = field(default_factory=list)
    market: dict = field(default_factory=dict)
    author: str = "numeric"    # "llm" | "numeric"
    symbols: list[str] = field(default_factory=list)

    def to_api(self) -> dict:
        d = asdict(self)
        d["eventTsIso"] = datetime.fromtimestamp(
            self.event_ts / 1000, timezone.utc).isoformat()
        d["hoursToEvent"] = round((self.event_ts - time.time() * 1000) / 3_600_000, 2)
        return d


# --------------------------------------------------------------- yardımcılar

def _event_keywords(ev: CalendarEvent) -> list[str]:
    """Bu olayla ilgili haberleri bulmak için arama terimleri."""
    t = ev.raw_title.lower()
    words: list[str] = []
    table = {
        "consumer price index": ["cpi", "inflation", "enflasyon"],
        "employment situation": ["jobs report", "nonfarm", "payroll", "istihdam"],
        "producer price index": ["ppi", "producer price"],
        "personal income": ["pce", "inflation"],
        "fomc": ["fed", "fomc", "rate", "faiz", "powell"],
        "federal funds": ["fed", "fomc", "rate", "faiz"],
        "gross domestic": ["gdp", "büyüme"],
        "retail sales": ["retail sales"],
        "job openings": ["jolts", "job openings"],
    }
    for needle, terms in table.items():
        if needle in t:
            words.extend(terms)
    if ev.category == "crypto":
        words.extend([w for w in ev.raw_title.split() if len(w) > 4][:4])
        words.extend(s.lower() for s in ev.symbols)
    if not words:
        words = [w.lower() for w in ev.title.split() if len(w) > 3][:3]
    seen: list[str] = []
    for w in words:
        w = w.strip(",.:;()[]").lower()
        if w and w not in seen:
            seen.append(w)
    return seen[:8]


def _match_headlines(keywords: list[str], limit: int = 60) -> list[dict]:
    """Haber akışından anahtar kelimelere uyan başlıkları getir (fail-safe)."""
    try:
        from engine.marketdata import news as market_news
        items = market_news.fetch_headlines(limit=limit)
    except Exception as e:  # noqa: BLE001
        log.debug("araştırma haber çekimi başarısız: %s", e)
        return []
    out = []
    for i in items:
        blob = f"{i.get('title', '')} {i.get('summary', '')}".lower()
        if any(k in blob for k in keywords):
            out.append({"source": i.get("source", ""), "title": i.get("title", ""),
                        "link": i.get("link", ""), "ts": i.get("ts", 0)})
    return out[:10]


def _market_context(symbols: list[str] | None = None) -> dict:
    """Sayısal piyasa bağlamı: BTC/ETH 24s değişim, oynaklık, funding, OI."""
    syms = symbols or ["BTC", "ETH"]
    out: dict = {}
    for sym in syms[:3]:
        row: dict = {}
        pair = f"{sym.upper()}USDT"
        try:
            from engine.marketdata import binance
            t = binance.ticker_24h(pair)
            row["price"] = t.get("price")
            row["change24h_pct"] = t.get("change_pct_24h")
            kl = binance.klines(pair, interval="1h", limit=48)
            closes = [k["close"] for k in kl if k.get("close")]
            if len(closes) >= 24:
                rng = [abs(kl[i]["high"] - kl[i]["low"]) / max(kl[i]["close"], 1e-9)
                       for i in range(len(kl) - 24, len(kl))]
                row["atr24h_pct"] = round(100 * sum(rng) / len(rng), 3)
        except Exception as e:  # noqa: BLE001
            log.debug("piyasa bağlamı (%s) alınamadı: %s", sym, e)
        try:
            from engine.marketdata import derivatives
            d = derivatives.summary(sym)
            if d.get("ok"):
                row["funding_pct"] = d.get("funding_pct")
                row["oi_change_pct"] = d.get("oi_change_pct")
                row["ls_ratio"] = d.get("ls_ratio")
                sq = d.get("squeeze")
                # squeeze zengin bir sözlük döner; nota yalnızca yönü alırız.
                row["squeeze"] = (sq.get("direction") if isinstance(sq, dict)
                                  else sq)
        except Exception as e:  # noqa: BLE001
            log.debug("türev bağlamı (%s) alınamadı: %s", sym, e)
        if row:
            out[sym.upper()] = row
    return out


def _fmt_market(ctx: dict) -> str:
    lines = []
    for sym, row in ctx.items():
        parts = [f"{sym}: fiyat {row.get('price', '?')}"]
        if row.get("change24h_pct") is not None:
            parts.append(f"24s %{row['change24h_pct']}")
        if row.get("atr24h_pct") is not None:
            parts.append(f"oynaklık(ATR24s) %{row['atr24h_pct']}")
        if row.get("funding_pct") is not None:
            parts.append(f"funding %{row['funding_pct']}")
        if row.get("oi_change_pct") is not None:
            parts.append(f"OI değişim %{row['oi_change_pct']}")
        if row.get("squeeze"):
            parts.append(f"squeeze: {row['squeeze']}")
        lines.append(" · ".join(str(p) for p in parts))
    return "\n".join(lines) or "(piyasa verisi yok)"


def _clip(x, lo: float, hi: float, default: float = 0.0) -> float:
    try:
        return max(lo, min(hi, float(x)))
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------- araştırmacı

class Researcher:
    """Takvim güdümlü otonom araştırma döngüsü. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._notes: dict[str, ResearchNote] = {}   # "<event_id>|<phase>" -> not
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._emit: Callable[[dict], None] | None = None
        self._last_cycle_ts = 0.0
        self._cycles = 0
        self._load()

    # ---- kalıcılık ----
    def _load(self) -> None:
        try:
            with open(_STORE_PATH, encoding="utf-8") as f:
                rows = json.load(f)
        except FileNotFoundError:
            return
        except Exception as e:  # noqa: BLE001
            log.warning("research.json okunamadı: %s", e)
            return
        for row in rows if isinstance(rows, list) else []:
            try:
                note = ResearchNote(**row)
                self._notes[f"{note.event_id}|{note.phase}"] = note
            except Exception:  # noqa: BLE001
                continue
        log.info("araştırma notları yüklendi: %d", len(self._notes))

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(_STORE_PATH) or ".", exist_ok=True)
            with self._lock:
                rows = sorted((asdict(n) for n in self._notes.values()),
                              key=lambda r: r["created_ms"])[-_MAX_NOTES:]
            tmp = _STORE_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False)
            os.replace(tmp, _STORE_PATH)
        except Exception as e:  # noqa: BLE001
            log.debug("research.json yazılamadı: %s", e)

    # ---- yaşam döngüsü ----
    def start(self, emit: Callable[[dict], None] | None = None) -> bool:
        if not _flag("RESEARCH_WATCHER"):
            log.info("araştırmacı kapalı (RESEARCH_WATCHER=0)")
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._emit = emit
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="researcher",
                                        daemon=True)
        self._thread.start()
        log.info("araştırmacı başladı (periyot %.0f dk, ufuk %.0f saat)",
                 _num("RESEARCH_INTERVAL_MIN", 30, 5, 360),
                 _num("RESEARCH_LOOKAHEAD_H", 48, 2, 336))
        return True

    def stop(self) -> None:
        self._stop.set()

    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _loop(self) -> None:
        # İlk tur hemen (bot açılır açılmaz takvim + yaklaşan olay bilinsin).
        while not self._stop.is_set():
            try:
                self.cycle()
            except Exception:  # noqa: BLE001
                log.exception("araştırma döngüsü hatası")
            self._stop.wait(_num("RESEARCH_INTERVAL_MIN", 30, 5, 360) * 60.0)

    # ---- ana döngü ----
    def cycle(self, now_ms: int | None = None) -> dict:
        """Bir araştırma turu. Döner: {calendar_added, pre, post}."""
        now = int(now_ms if now_ms is not None else time.time() * 1000)
        added = 0
        try:
            added = calendar.refresh()
        except Exception as e:  # noqa: BLE001
            log.warning("takvim tazelenemedi: %s", e)

        added += self._ingest_news_events(now)

        lookahead = _num("RESEARCH_LOOKAHEAD_H", 48, 2, 336)
        min_imp = _num("RESEARCH_MIN_IMPORTANCE", 0.6, 0.0, 1.0)
        refresh_s = _num("RESEARCH_REFRESH_H", 8, 0.5, 72) * 3600_000

        pre = post = 0
        for ev in calendar.upcoming(hours=lookahead, min_importance=min_imp,
                                    now_ms=now):
            key = f"{ev.id}|pre"
            old = self._notes.get(key)
            if old is not None and (now - old.created_ms) < refresh_s:
                continue
            if self.research_event(ev, phase="pre", now_ms=now):
                pre += 1

        # sonuç okuması: olay geçti + arka pencere doldu
        post_wait = calendar.post_window_min() * 60_000
        for ev in calendar.recent(hours=lookahead, now_ms=now):
            if ev.importance < min_imp or now < ev.ts + post_wait:
                continue
            if f"{ev.id}|post" in self._notes:
                continue
            if self.research_event(ev, phase="post", now_ms=now):
                post += 1

        self._last_cycle_ts = now / 1000.0
        self._cycles += 1
        if pre or post:
            self._save()
        return {"calendar_added": added, "pre": pre, "post": post}

    def _ingest_news_events(self, now_ms: int) -> int:
        """Taze başlıklardan ileri tarihli kripto olaylarını takvime ekle."""
        try:
            from engine.marketdata import news as market_news
            items = market_news.fetch_headlines(limit=60)
        except Exception as e:  # noqa: BLE001
            log.debug("olay çıkarımı için haber alınamadı: %s", e)
            return 0
        n = 0
        for i in items:
            try:
                found = calendar.ingest_headline(
                    i.get("title", ""), url=i.get("link", ""), now_ms=now_ms)
            except Exception:  # noqa: BLE001
                continue
            for ev in found:
                n += 1
                log.info("haberden olay çıkarıldı: %s @ %s", ev.title,
                         datetime.fromtimestamp(ev.ts / 1000, timezone.utc).date())
        return n

    # ---- tek olay araştırması ----
    def research_event(self, ev: CalendarEvent, phase: str = "pre",
                       now_ms: int | None = None) -> ResearchNote | None:
        now = int(now_ms if now_ms is not None else time.time() * 1000)
        keywords = _event_keywords(ev)
        heads = _match_headlines(keywords)
        ctx = _market_context(ev.symbols or None)

        note = ResearchNote(
            event_id=ev.id, title=ev.title, event_ts=ev.ts, phase=phase,
            created_ms=now, headlines=heads, market=ctx,
            symbols=ev.symbols or ["BTC", "ETH"])

        filled = self._llm_fill(note, ev, phase) if _flag("RESEARCH_LLM") else False
        if not filled:
            self._numeric_fill(note, ev, phase)

        with self._lock:
            self._notes[f"{ev.id}|{phase}"] = note
            if len(self._notes) > _MAX_NOTES:
                oldest = sorted(self._notes.items(),
                                key=lambda kv: kv[1].created_ms)[:len(self._notes) - _MAX_NOTES]
                for k, _ in oldest:
                    self._notes.pop(k, None)
        self._publish(note)
        return note

    def _llm_fill(self, note: ResearchNote, ev: CalendarEvent, phase: str) -> bool:
        from engine.signals import llm as llm_layer
        when = datetime.fromtimestamp(ev.ts / 1000, timezone.utc)
        hours = (ev.ts - note.created_ms) / 3_600_000
        head_lines = "\n".join(
            f"- [{h['source']}] {h['title'][:150]}" for h in note.headlines) \
            or "(ilgili başlık bulunamadı)"
        prompt = (
            f"OLAY: {ev.title} ({ev.raw_title})\n"
            f"ZAMAN (UTC): {when:%Y-%m-%d %H:%M} "
            f"({'yaklaşıyor, ' + f'{hours:.1f} saat kaldı' if hours >= 0 else f'{abs(hours):.1f} saat önce açıklandı'})\n"
            f"ÖNEM: {ev.importance:.2f}/1.0 · KATEGORİ: {ev.category}\n\n"
            f"İLGİLİ BAŞLIKLAR:\n{head_lines}\n\n"
            f"PİYASA BAĞLAMI:\n{_fmt_market(note.market)}\n")
        system = RESEARCH_SYSTEM if phase == "pre" else OUTCOME_SYSTEM
        try:
            text = llm_layer.complete(system, prompt, max_tokens=500)
        except Exception as e:  # noqa: BLE001
            log.debug("araştırma LLM çağrısı başarısız: %s", e)
            return False
        if not text:
            return False
        try:
            data = json.loads(text[text.index("{"): text.rindex("}") + 1])
        except Exception:  # noqa: BLE001
            log.debug("araştırma LLM yanıtı çözümlenemedi")
            return False
        if not isinstance(data, dict):
            return False
        note.summary = str(data.get("ozet", ""))[:400]
        note.bias = _clip(data.get("bias", 0.0), -1.0, 1.0)
        note.author = "llm"
        if phase == "pre":
            note.expectation = str(data.get("beklenti", ""))[:200]
            note.risk = str(data.get("risk", ""))[:200]
            scen = data.get("senaryolar") or []
            note.scenarios = [
                {"kosul": str(s.get("kosul", ""))[:120],
                 "etki": str(s.get("etki", ""))[:120]}
                for s in scen if isinstance(s, dict)][:4]
            note.watch = [str(w)[:80] for w in (data.get("izlenecek") or [])][:5]
        else:
            note.surprise = str(data.get("surpriz", ""))[:60]
            note.risk = str(data.get("devam", ""))[:200]
        return bool(note.summary)

    def _numeric_fill(self, note: ResearchNote, ev: CalendarEvent, phase: str) -> None:
        """LLM yokken sayısal/kural tabanlı not (akış asla durmaz)."""
        hours = (ev.ts - note.created_ms) / 3_600_000
        ctx_line = _fmt_market(note.market)
        if phase == "pre":
            note.summary = (
                f"{ev.title} {hours:.1f} saat sonra (önem {ev.importance:.2f}). "
                f"{len(note.headlines)} ilgili başlık bulundu. Piyasa: {ctx_line}")
            note.expectation = "belirsiz (LLM kapalı — sayısal not)"
            note.watch = ["olay öncesi 90 dk giriş kapalı",
                          "olay sonrası ilk 45 dk oynaklık"]
            note.risk = ("Yüksek etkili veri: dar spread ve ani slippage riski."
                         if ev.importance >= 0.8 else "Orta etkili veri.")
            # bias: funding + 24s momentum karışımı (kaba risk iştahı ölçüsü)
            vals = [r.get("change24h_pct") for r in note.market.values()
                    if r.get("change24h_pct") is not None]
            note.bias = _clip((sum(vals) / len(vals) / 5.0) if vals else 0.0,
                              -1.0, 1.0)
            note.scenarios = [
                {"kosul": "veri beklentiden sıcak", "etki": "risk iştahı azalır"},
                {"kosul": "veri beklentiden soğuk", "etki": "risk iştahı artar"},
            ]
        else:
            note.summary = (f"{ev.title} açıklandı ({abs(hours):.1f} saat önce). "
                            f"Piyasa tepkisi: {ctx_line}")
            vals = [r.get("change24h_pct") for r in note.market.values()
                    if r.get("change24h_pct") is not None]
            avg = (sum(vals) / len(vals)) if vals else 0.0
            note.surprise = ("yukarı" if avg > 1.0 else
                             "aşağı" if avg < -1.0 else "nötr")
            note.bias = _clip(avg / 5.0, -1.0, 1.0)
        note.author = "numeric"

    # ---- yayın ----
    def _publish(self, note: ResearchNote) -> None:
        payload = note.to_api()
        if self._emit is not None:
            for evt in ({"type": "research", "note": payload},
                        {"type": "log", "level": "info",
                         "message": (f"Araştırma [{note.phase}] {note.title}: "
                                     f"{note.summary[:160]}")}):
                try:
                    self._emit(evt)
                except Exception:  # noqa: BLE001
                    pass
        if not _flag("RESEARCH_NOTIFY"):
            return
        try:
            from engine.notify import notify
            when = datetime.fromtimestamp(note.event_ts / 1000, timezone.utc)
            head = ("📅 YAKLAŞAN VERİ" if note.phase == "pre" else "✅ VERİ SONUCU")
            lines = [f"{head}: {note.title} — {when:%d.%m %H:%M} UTC",
                     note.summary[:400]]
            if note.expectation:
                lines.append(f"Beklenti: {note.expectation}")
            for s in note.scenarios[:2]:
                lines.append(f"• {s['kosul']} → {s['etki']}")
            if note.risk:
                lines.append(f"Risk: {note.risk}")
            lines.append(f"Eğilim (bias): {note.bias:+.2f} · kaynak: {note.author}")
            notify("\n".join(lines), level="info")
        except Exception:  # noqa: BLE001
            pass

    # ---- okuma ----
    def notes(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = sorted(self._notes.values(), key=lambda n: -n.created_ms)
        return [n.to_api() for n in rows[:limit]]

    def note_for(self, event_id: str, phase: str = "pre") -> dict | None:
        n = self._notes.get(f"{event_id}|{phase}")
        return n.to_api() if n else None

    def bias(self, symbol: str | None = None, now_ms: int | None = None) -> dict:
        """Aktif olay penceresindeki araştırma eğilimi (danışma amaçlı).

        Sinyal motoru bunu bilgi olarak okur; işlem KAPISI takvimin
        `guard()`/`size_factor()` fonksiyonlarıdır.
        """
        now = int(now_ms if now_ms is not None else time.time() * 1000)
        sym = (symbol or "").upper().lstrip("W")
        active = calendar.active_window(now_ms=now)
        rows = []
        for ev in active:
            if sym and ev.symbols and sym not in ev.symbols:
                continue
            n = self._notes.get(f"{ev.id}|pre") or self._notes.get(f"{ev.id}|post")
            if n:
                rows.append(n)
        if not rows:
            return {"score": 0.0, "count": 0, "titles": []}
        score = sum(n.bias for n in rows) / len(rows)
        return {"score": round(score, 3), "count": len(rows),
                "titles": [n.title for n in rows]}

    def status(self) -> dict:
        return {
            "running": self.running(),
            "enabled": _flag("RESEARCH_WATCHER"),
            "intervalMin": _num("RESEARCH_INTERVAL_MIN", 30, 5, 360),
            "lookaheadH": _num("RESEARCH_LOOKAHEAD_H", 48, 2, 336),
            "minImportance": _num("RESEARCH_MIN_IMPORTANCE", 0.6, 0.0, 1.0),
            "llm": _flag("RESEARCH_LLM"),
            "cycles": self._cycles,
            "lastCycleMs": int(self._last_cycle_ts * 1000),
            "noteCount": len(self._notes),
            "calendar": calendar.status(),
        }


# Modül-seviyesi tekil araştırmacı.
researcher = Researcher()

__all__ = ["Researcher", "ResearchNote", "researcher", "cal_mod"]
