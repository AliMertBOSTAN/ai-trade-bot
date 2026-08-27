"""Ekonomik veri takvimi — makro (ABD) + kripto olayları.

Bot, kullanıcı sormasa bile ÖNCEDEN hangi verinin ne zaman açıklanacağını
bilir. Bu modül üç kaynağı birleştirir (hepsi ANAHTARSIZ, fail-safe):

  1. **BLS ICS akışı** (`https://www.bls.gov/schedule/news_release/bls.ics`)
     — TÜFE (CPI), ÜFE (PPI), İstihdam Raporu (NFP), JOLTS, ECI... Gerçek,
     resmi yayın tarih/saatleri (US-Eastern). Ek ICS akışları
     `CALENDAR_ICS_FEEDS` ile eklenebilir (virgülle ayrılmış URL).
  2. **Statik FOMC tablosu** (2026-2027) — faiz kararı 14:00 ET. Fed'in
     parasal politika RSS akışı ile "gerçekleşti mi" doğrulaması yapılır.
  3. **Kullanıcı/haber kaynaklı olaylar** — `data/calendar_custom.json` ve
     haber başlıklarından çıkarılan tarihli kripto olayları (unlock, ETF
     kararı, ağ yükseltmesi). `add_event()` ile programatik eklenir.

Kullanım (sinyal/risk yolu):
  * `upcoming(hours=48)`  → yaklaşan olaylar (araştırmacı bunu okur)
  * `guard(now=None)`     → yüksek-etkili olay penceresindeysek gerekçe döner
                            (yeni ALIM engellenir; satış/çıkış ASLA engellenmez)
  * `size_factor(now)`    → orta-etkili pencerede pozisyon boyutu çarpanı

Ağ yoksa/akış bozuksa modül SESSİZCE boş listeye düşmez: statik FOMC tablosu
ve önbellek (`data/calendar_cache.json`) devrede kalır.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

log = logging.getLogger("marketdata.calendar")

# ---------------------------------------------------------------- kaynaklar

BLS_ICS = "https://www.bls.gov/schedule/news_release/bls.ics"
FED_MONETARY_RSS = "https://www.federalreserve.gov/feeds/press_monetary.xml"

_CACHE_PATH = os.path.join("data", "calendar_cache.json")
_CUSTOM_PATH = os.path.join("data", "calendar_custom.json")

# Yayın TTL: takvim günde bir tazelenir (yayın tarihleri sık değişmez).
_REFRESH_TTL_S = 6 * 3600

# ABD Doğu saati ofseti: ICS "US-Eastern" yerel saat verir. DST kuralı
# (Mart 2. Pazar - Kasım 1. Pazar) ile UTC'ye çevrilir.


def _second_sunday(year: int, month: int) -> datetime:
    d = datetime(year, month, 1, tzinfo=timezone.utc)
    sundays = 0
    while True:
        if d.weekday() == 6:
            sundays += 1
            if sundays == 2:
                return d
        d += timedelta(days=1)


def _first_sunday(year: int, month: int) -> datetime:
    d = datetime(year, month, 1, tzinfo=timezone.utc)
    while d.weekday() != 6:
        d += timedelta(days=1)
    return d


def _et_offset_hours(dt_naive: datetime) -> int:
    """ABD Doğu saati UTC ofseti (EDT=-4, EST=-5)."""
    y = dt_naive.year
    dst_start = _second_sunday(y, 3).replace(hour=2)
    dst_end = _first_sunday(y, 11).replace(hour=2)
    ref = dt_naive.replace(tzinfo=timezone.utc)
    return -4 if dst_start <= ref < dst_end else -5


def _et_to_epoch_ms(stamp: str) -> int:
    """'20260812T083000' (US-Eastern) -> epoch ms (UTC)."""
    dt = datetime.strptime(stamp[:15], "%Y%m%dT%H%M%S")
    off = _et_offset_hours(dt)
    return int((dt.replace(tzinfo=timezone.utc) - timedelta(hours=off)).timestamp() * 1000)


# ------------------------------------------------------------ önem haritası
# Kripto fiyatını oynatma gücü: 1.0 = en yüksek (CPI/FOMC), 0.3 = düşük.
_IMPORTANCE: list[tuple[str, float, str]] = [
    # (başlıkta aranan alt dize [küçük harf], önem, normalize ad)
    ("consumer price index", 1.0, "TÜFE (CPI)"),
    ("employment situation", 1.0, "İstihdam Raporu (NFP)"),
    ("fomc", 1.0, "FOMC Faiz Kararı"),
    ("federal funds", 1.0, "FOMC Faiz Kararı"),
    ("personal income and outlays", 0.85, "PCE Enflasyon"),
    ("pce", 0.85, "PCE Enflasyon"),
    ("producer price index", 0.7, "ÜFE (PPI)"),
    ("gross domestic product", 0.7, "GSYH (GDP)"),
    ("retail sales", 0.6, "Perakende Satışlar"),
    ("job openings", 0.55, "JOLTS Açık Pozisyonlar"),
    ("employment cost index", 0.5, "İstihdam Maliyet Endeksi"),
    ("real earnings", 0.35, "Reel Kazançlar"),
    ("import", 0.3, "İthalat/İhracat Fiyatları"),
    ("productivity", 0.3, "Verimlilik"),
]

# Kripto-özel olay anahtar kelimeleri (haberden tarih çıkarımı için)
_CRYPTO_TERMS: list[tuple[str, float, str]] = [
    ("unlock", 0.7, "Token Unlock"),
    ("kilit açılım", 0.7, "Token Unlock"),
    ("etf", 0.8, "ETF Kararı/Akışı"),
    ("halving", 0.9, "Halving"),
    ("hard fork", 0.7, "Ağ Yükseltmesi"),
    ("upgrade", 0.6, "Ağ Yükseltmesi"),
    ("mainnet", 0.6, "Mainnet"),
    ("listing", 0.5, "Borsa Listeleme"),
    ("sec ", 0.75, "SEC Kararı"),
    ("mica", 0.6, "Düzenleme (MiCA)"),
]

# FOMC faiz kararı tarihleri (kararın açıklandığı GÜN, 14:00 ET).
# Kaynak: federalreserve.gov toplantı takvimi. Yıl geçtikçe güncellenir;
# ICS/RSS ile çelişirse canlı kaynak kazanır.
_FOMC_DECISION_DAYS: tuple[str, ...] = (
    # 2026
    "20260128", "20260318", "20260429", "20260617",
    "20260729", "20260916", "20261028", "20261209",
    # 2027 (Fed'in ilan ettiği takvim; teyit için RSS kullanılır)
    "20270127", "20270317", "20270428", "20270616",
    "20270728", "20270915", "20271027", "20271208",
)


def _classify(title: str) -> tuple[float, str, str]:
    """Başlıktan (önem, normalize ad, kategori) çıkar."""
    t = (title or "").lower()
    for needle, imp, label in _IMPORTANCE:
        if needle in t:
            return imp, label, "macro"
    for needle, imp, label in _CRYPTO_TERMS:
        if needle in t:
            return imp, label, "crypto"
    return 0.25, (title or "").strip()[:60], "other"


# ---------------------------------------------------------------- veri tipi

@dataclass
class CalendarEvent:
    id: str
    title: str          # normalize ad (TÜFE (CPI) vb.)
    raw_title: str      # kaynaktaki ham başlık
    ts: int             # epoch ms (UTC) — yayın anı
    category: str       # macro | crypto | other
    importance: float   # 0..1
    source: str         # bls | fomc | custom | news
    url: str = ""
    symbols: list[str] = field(default_factory=list)  # boş = piyasa geneli

    def to_api(self) -> dict:
        d = asdict(self)
        d["tsIso"] = datetime.fromtimestamp(self.ts / 1000, timezone.utc).isoformat()
        d["inHours"] = round((self.ts - time.time() * 1000) / 3_600_000, 2)
        return d


# ------------------------------------------------------------- ICS ayrıştır

_ICS_EVENT_RE = re.compile(r"BEGIN:VEVENT(.*?)END:VEVENT", re.S)


def parse_ics(text: str, source: str = "bls") -> list[CalendarEvent]:
    """Minimal ICS ayrıştırıcı — yalnızca DTSTART + SUMMARY + UID okur.

    Harici bağımlılık YOK. Bozuk kayıt atlanır (fail-safe).
    """
    out: list[CalendarEvent] = []
    # ICS satır katlaması (folding): satır başı boşluk = önceki satırın devamı
    unfolded = re.sub(r"\r?\n[ \t]", "", text or "")
    for block in _ICS_EVENT_RE.findall(unfolded):
        m_start = re.search(r"DTSTART[^:]*:(\d{8}T\d{6})", block)
        m_sum = re.search(r"SUMMARY:(.+)", block)
        if not m_start or not m_sum:
            continue
        raw_title = m_sum.group(1).strip().replace("\\,", ",")
        try:
            ts = _et_to_epoch_ms(m_start.group(1))
        except Exception:  # noqa: BLE001
            continue
        imp, label, cat = _classify(raw_title)
        uid_m = re.search(r"UID:(.+)", block)
        uid = (uid_m.group(1).strip() if uid_m
               else f"{source}:{m_start.group(1)}:{raw_title[:20]}")
        out.append(CalendarEvent(id=uid, title=label, raw_title=raw_title, ts=ts,
                                 category=cat, importance=imp, source=source,
                                 url="https://www.bls.gov/schedule/news_release/"))
    return out


def _fomc_events() -> list[CalendarEvent]:
    """Statik FOMC faiz kararı olayları (14:00 ET)."""
    out: list[CalendarEvent] = []
    for day in _FOMC_DECISION_DAYS:
        try:
            ts = _et_to_epoch_ms(f"{day}T140000")
        except Exception:  # noqa: BLE001
            continue
        out.append(CalendarEvent(
            id=f"fomc:{day}", title="FOMC Faiz Kararı",
            raw_title="FOMC Statement / Federal Funds Rate decision",
            ts=ts, category="macro", importance=1.0, source="fomc",
            url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"))
    return out


# ------------------------------------------------------- haberden tarih çıkar

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "ocak": 1, "şubat": 2, "subat": 2, "mart": 3, "nisan": 4, "mayıs": 5,
    "mayis": 5, "haziran": 6, "temmuz": 7, "ağustos": 8, "agustos": 8,
    "eylül": 9, "eylul": 9, "ekim": 10, "kasım": 11, "kasim": 11, "aralık": 12,
    "aralik": 12,
}
_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))
# "August 12", "12 August", "Aug 12, 2026", "12 Ağustos"
_DATE_RE = re.compile(
    rf"\b(?:(\d{{1,2}})\s+({_MONTH_ALT})|({_MONTH_ALT})\s+(\d{{1,2}}))"
    rf"(?:[,\s]+(\d{{4}}))?\b", re.I)


def extract_event_dates(title: str, now_ms: int | None = None) -> list[int]:
    """Bir haber başlığındaki GELECEK tarihleri epoch ms olarak çıkarır.

    Yıl yazılmamışsa en yakın gelecek yıl varsayılır. Geçmişteki tarihler
    (30 günden eski) elenir — "dün açıklanan" haberleri olay sanmayalım.
    """
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    ref = datetime.fromtimestamp(now / 1000, timezone.utc)
    out: list[int] = []
    for m in _DATE_RE.finditer(title or ""):
        day_s, mon_a, mon_b, day_s2, year_s = m.groups()
        mon_name = (mon_a or mon_b or "").lower()
        day = int(day_s or day_s2 or 0)
        mon = _MONTHS.get(mon_name, 0)
        if not (1 <= day <= 31 and 1 <= mon <= 12):
            continue
        year = int(year_s) if year_s else ref.year
        try:
            dt = datetime(year, mon, day, 13, 0, tzinfo=timezone.utc)
        except ValueError:
            continue
        if not year_s and (dt - ref).days < -30:
            try:
                dt = dt.replace(year=year + 1)
            except ValueError:
                continue
        ts = int(dt.timestamp() * 1000)
        if ts >= now - 30 * 86400_000:
            out.append(ts)
    return sorted(set(out))


# ------------------------------------------------------------------ takvim

class EconomicCalendar:
    """Olay deposu + tazeleme + pencere kapıları. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._events: dict[str, CalendarEvent] = {}
        self._last_refresh = 0.0
        self._last_error = ""
        self._seed_static()
        self._load_cache()
        self._load_custom()

    # ---- yapılandırma (env, çalışma anında okunur) ----
    @staticmethod
    def guard_enabled() -> bool:
        return os.getenv("CALENDAR_GUARD", "1").strip().lower() not in ("0", "false", "no")

    @staticmethod
    def _f(name: str, default: float, lo: float, hi: float) -> float:
        try:
            v = float(os.getenv(name, str(default)))
        except (TypeError, ValueError):
            v = default
        return max(lo, min(hi, v))

    def pre_window_min(self) -> float:
        return self._f("CALENDAR_PRE_MIN", 90.0, 0.0, 1440.0)

    def post_window_min(self) -> float:
        return self._f("CALENDAR_POST_MIN", 45.0, 0.0, 1440.0)

    def block_importance(self) -> float:
        """Bu önemin ÜSTÜNDEKİ olaylar yeni alımı bloklar."""
        return self._f("CALENDAR_BLOCK_IMPORTANCE", 0.8, 0.0, 1.0)

    def derisk_importance(self) -> float:
        """Bu önemin üstündekiler pozisyonu küçültür (bloklamaz)."""
        return self._f("CALENDAR_DERISK_IMPORTANCE", 0.5, 0.0, 1.0)

    def derisk_factor(self) -> float:
        return self._f("CALENDAR_DERISK_FACTOR", 0.5, 0.1, 1.0)

    # ---- yükleme ----
    def _seed_static(self) -> None:
        for ev in _fomc_events():
            self._events[ev.id] = ev

    def _load_cache(self) -> None:
        try:
            with open(_CACHE_PATH, encoding="utf-8") as f:
                raw = json.load(f)
            for row in raw.get("events", []):
                ev = CalendarEvent(**row)
                self._events.setdefault(ev.id, ev)
            self._last_refresh = float(raw.get("fetchedAt", 0.0))
            log.info("takvim önbelleği yüklendi: %d olay", len(raw.get("events", [])))
        except FileNotFoundError:
            pass
        except Exception as e:  # noqa: BLE001
            log.debug("takvim önbelleği okunamadı: %s", e)

    def _load_custom(self) -> None:
        """Kullanıcı tanımlı olaylar: data/calendar_custom.json.

        Biçim: [{"title": "...", "ts": 1786...,  "importance": 0.8,
                 "category": "crypto", "symbols": ["BTC"]}]
        """
        try:
            with open(_CUSTOM_PATH, encoding="utf-8") as f:
                rows = json.load(f)
        except FileNotFoundError:
            return
        except Exception as e:  # noqa: BLE001
            log.warning("calendar_custom.json okunamadı: %s", e)
            return
        for i, row in enumerate(rows if isinstance(rows, list) else []):
            try:
                ts = int(row["ts"])
                title = str(row.get("title", "Özel olay"))
                self.add_event(CalendarEvent(
                    id=str(row.get("id") or f"custom:{i}:{ts}"), title=title,
                    raw_title=title, ts=ts,
                    category=str(row.get("category", "crypto")),
                    importance=float(row.get("importance", 0.6)),
                    source="custom", url=str(row.get("url", "")),
                    symbols=[str(s).upper() for s in row.get("symbols", [])]))
            except Exception:  # noqa: BLE001
                continue

    def _save_cache(self) -> None:
        try:
            os.makedirs(os.path.dirname(_CACHE_PATH) or ".", exist_ok=True)
            with self._lock:
                rows = [asdict(e) for e in self._events.values()
                        if e.source in ("bls", "ics", "news")]
            tmp = _CACHE_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"fetchedAt": time.time(), "events": rows}, f)
            os.replace(tmp, _CACHE_PATH)
        except Exception as e:  # noqa: BLE001
            log.debug("takvim önbelleği yazılamadı: %s", e)

    # ---- tazeleme ----
    def ics_feeds(self) -> list[str]:
        extra = [u.strip() for u in os.getenv("CALENDAR_ICS_FEEDS", "").split(",")
                 if u.strip()]
        return [BLS_ICS] + [u for u in extra if u != BLS_ICS]

    def refresh(self, force: bool = False, fetcher=None) -> int:
        """ICS akışlarını çek ve olay deposunu güncelle. Eklenen olay sayısını döner.

        `fetcher`: test edilebilirlik için (url)->str. Varsayılan: engine http.
        """
        now = time.time()
        if not force and (now - self._last_refresh) < _REFRESH_TTL_S:
            return 0
        if fetcher is None:
            from engine.marketdata.http import get_text as fetcher  # type: ignore

        added = 0
        ok_any = False
        for url in self.ics_feeds():
            try:
                text = fetcher(url)
            except Exception as e:  # noqa: BLE001
                self._last_error = f"{url}: {e}"
                log.warning("takvim akışı alınamadı (%s): %s", url, e)
                continue
            if not text or "BEGIN:VEVENT" not in text:
                self._last_error = f"{url}: boş/geçersiz ICS"
                continue
            ok_any = True
            src = "bls" if url == BLS_ICS else "ics"
            for ev in parse_ics(text, source=src):
                with self._lock:
                    if ev.id not in self._events:
                        added += 1
                    self._events[ev.id] = ev

        self._seed_static()  # FOMC tablosu her zaman devrede
        self._prune()        # önce buda, SONRA yaz (önbellek şişmesin)
        if ok_any:
            self._last_refresh = now
            self._last_error = ""
            self._save_cache()
        log.info("takvim tazelendi: +%d olay (toplam %d)", added, len(self._events))
        return added

    def _prune(self, keep_days: int = 30) -> None:
        """Çok eski olayları at (bellek + JSON boyutu)."""
        cutoff = (time.time() - keep_days * 86400) * 1000
        with self._lock:
            for k in [k for k, e in self._events.items() if e.ts < cutoff]:
                self._events.pop(k, None)

    # ---- haber kaynaklı olay ekleme ----
    def ingest_headline(self, title: str, url: str = "", source: str = "news",
                        now_ms: int | None = None) -> list[CalendarEvent]:
        """Bir haber başlığından tarihli KRİPTO olayı çıkar ve ekle.

        Yalnızca kripto-özel terim İÇEREN ve gelecek tarih barındıran
        başlıklar olay olur (gürültüyü kesmek için).
        """
        t = (title or "").lower()
        hit = next(((imp, label) for needle, imp, label in _CRYPTO_TERMS
                    if needle in t), None)
        if hit is None:
            return []
        dates = extract_event_dates(title, now_ms)
        if not dates:
            return []
        imp, label = hit
        out: list[CalendarEvent] = []
        for ts in dates:
            ev = CalendarEvent(
                id=f"news:{ts}:{label}:{abs(hash(title)) % 10 ** 8}",
                title=label, raw_title=title.strip()[:200], ts=ts,
                category="crypto", importance=imp, source=source, url=url,
                symbols=_symbols_in(title))
            self.add_event(ev)
            out.append(ev)
        return out

    def add_event(self, ev: CalendarEvent) -> None:
        with self._lock:
            self._events[ev.id] = ev

    # ---- okuma ----
    def all_events(self) -> list[CalendarEvent]:
        with self._lock:
            return sorted(self._events.values(), key=lambda e: e.ts)

    def upcoming(self, hours: float = 48.0, min_importance: float = 0.0,
                 now_ms: int | None = None) -> list[CalendarEvent]:
        now = int(now_ms if now_ms is not None else time.time() * 1000)
        end = now + int(hours * 3_600_000)
        return [e for e in self.all_events()
                if now <= e.ts <= end and e.importance >= min_importance]

    def recent(self, hours: float = 24.0, now_ms: int | None = None) -> list[CalendarEvent]:
        now = int(now_ms if now_ms is not None else time.time() * 1000)
        start = now - int(hours * 3_600_000)
        return [e for e in self.all_events() if start <= e.ts <= now]

    def next_event(self, min_importance: float = 0.7,
                   now_ms: int | None = None) -> CalendarEvent | None:
        rows = self.upcoming(hours=24 * 30, min_importance=min_importance,
                             now_ms=now_ms)
        return rows[0] if rows else None

    # ---- risk kapıları ----
    def active_window(self, now_ms: int | None = None,
                      min_importance: float | None = None) -> list[CalendarEvent]:
        """Şu anda ön/arka penceresinde olduğumuz olaylar (önemine göre)."""
        now = int(now_ms if now_ms is not None else time.time() * 1000)
        pre = self.pre_window_min() * 60_000
        post = self.post_window_min() * 60_000
        thr = self.derisk_importance() if min_importance is None else min_importance
        return [e for e in self.all_events()
                if e.importance >= thr and (e.ts - pre) <= now <= (e.ts + post)]

    def guard(self, symbol: str | None = None,
              now_ms: int | None = None) -> str | None:
        """Yeni ALIM freni: yüksek-etkili veri penceresindeysek gerekçe döner.

        Satış/çıkış ASLA engellenmez (bu fonksiyon yalnızca girişte çağrılır).
        `CALENDAR_GUARD=0` ile tamamen kapatılır.
        """
        if not self.guard_enabled():
            return None
        now = int(now_ms if now_ms is not None else time.time() * 1000)
        rows = self.active_window(now_ms=now, min_importance=self.block_importance())
        if symbol:
            sym = symbol.upper().lstrip("W")
            rows = [e for e in rows if not e.symbols or sym in e.symbols]
        if not rows:
            return None
        ev = max(rows, key=lambda e: e.importance)
        mins = (ev.ts - now) / 60_000
        when = (f"{abs(mins):.0f} dk sonra" if mins >= 0 else f"{abs(mins):.0f} dk önce")
        return f"veri penceresi: {ev.title} ({when})"

    def size_factor(self, symbol: str | None = None,
                    now_ms: int | None = None) -> tuple[float, str]:
        """Orta-etkili olay penceresinde pozisyon boyutu çarpanı (0.1..1.0)."""
        if not self.guard_enabled():
            return 1.0, ""
        now = int(now_ms if now_ms is not None else time.time() * 1000)
        rows = self.active_window(now_ms=now)
        if symbol:
            sym = symbol.upper().lstrip("W")
            rows = [e for e in rows if not e.symbols or sym in e.symbols]
        rows = [e for e in rows if e.importance < self.block_importance()]
        if not rows:
            return 1.0, ""
        ev = max(rows, key=lambda e: e.importance)
        return self.derisk_factor(), f"{ev.title} penceresi — boyut küçültüldü"

    def status(self) -> dict:
        evs = self.all_events()
        nxt = self.next_event(min_importance=0.7)
        return {
            "eventCount": len(evs),
            "lastRefreshMs": int(self._last_refresh * 1000),
            "lastError": self._last_error,
            "guardEnabled": self.guard_enabled(),
            "preWindowMin": self.pre_window_min(),
            "postWindowMin": self.post_window_min(),
            "nextHighImpact": nxt.to_api() if nxt else None,
            "activeWindow": [e.to_api() for e in self.active_window()],
            "feeds": self.ics_feeds(),
        }


def _symbols_in(text: str) -> list[str]:
    """Başlıkta geçen bilinen token sembolleri (news_watcher alias tablosu)."""
    try:
        from engine.marketdata.news_watcher import _ALIASES
    except Exception:  # noqa: BLE001
        return []
    t = f" {(text or '').lower()} "
    out = [sym for sym, aliases in _ALIASES.items()
           if any(a in t for a in aliases)]
    return sorted(out)


# Modül-seviyesi tekil takvim (orchestrator/app/researcher paylaşır).
calendar = EconomicCalendar()
