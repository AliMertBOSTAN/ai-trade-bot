"""Makro & duyarlılık panelleri — anahtarsız kaynaklar.

Kaynaklar (hepsi ücretsiz, API anahtarı gerekmez):
  • Endeks/emtia/tahvil : Yahoo Finance chart API (birincil) → Stooq CSV (yedek)
  • Kripto Korku&Açgözlülük : alternative.me/fng
  • ABD Korku&Açgözlülük    : CNN dataviz (tarayıcı başlığı ile)
  • BTC günlük kapanış      : Yahoo BTC-USD → Binance klines (yedek)

Üretilen paneller:
  fear_greed()  — iki korku endeksi + 30 günlük seri
  indices()     — endeks şeridi (değer, %değişim, 14 günlük sparkline)
  risk_on_off() — göstergelerden 0..100 risk iştahı skoru (en az 3 gösterge şart)
  correlation() — BTC'nin makro varlıklarla 30/90 günlük getiri korelasyonu

Her fonksiyon fail-safe: kaynak düşerse o parça ok=False döner, panelin
geri kalanı çalışır. Yahoo bir sembolü vermezse Stooq denenir.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from engine.marketdata.http import get_json, get_text
from engine.marketdata.intel.cache import cached

log = logging.getLogger("intel.macro")

_FNG = "https://api.alternative.me/fng/"
_CNN = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
_YF = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
       "?range={rng}&interval=1d")
_STOOQ_HIST = "https://stooq.com/q/d/l/?s={sym}&i=d"

# Tarayıcı benzeri başlıklar: CNN ve Yahoo bot trafiğini aksi halde reddeder.
_BROWSER = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

# Yahoo sembolü -> (kısa ad, uzun ad, tür, stooq yedeği)
INDEX_MAP: dict[str, tuple[str, str, str, str | None]] = {
    "%5EGSPC":   ("SPX", "S&P 500", "equity", "^spx"),
    "%5ENDX":    ("NDX", "Nasdaq 100", "equity", "^ndx"),
    "%5EDJI":    ("DJI", "Dow Jones", "equity", "^dji"),
    "%5EVIX":    ("VIX", "Volatilite Endeksi", "vol", "^vix"),
    "DX-Y.NYB":  ("DXY", "Dolar Endeksi", "fx", "dx.f"),
    "%5ETNX":    ("US10Y", "ABD 10 Yıllık Faiz", "rate", "10usy.b"),
    "GC%3DF":    ("GOLD", "Altın (ons)", "metal", "gc.f"),
    "SI%3DF":    ("SILVER", "Gümüş (ons)", "metal", "si.f"),
    "CL%3DF":    ("WTI", "Ham Petrol", "energy", "cl.f"),
    "IBIT":      ("IBIT", "iShares Bitcoin ETF", "etf", "ibit.us"),
    "MSTR":      ("MSTR", "Strategy (MicroStrategy)", "equity", "mstr.us"),
}


def _f(x, default: float | None = None) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


# ----------------------------------------------------------------- fiyat seri
def _yahoo_series(sym: str, rng: str = "3mo") -> list[float]:
    """Yahoo chart API -> günlük kapanış listesi (boş gelirse [])."""
    d = get_json(_YF.format(sym=sym, rng=rng), ttl=600, headers=_BROWSER)
    res = ((d or {}).get("chart") or {}).get("result") or []
    if not res:
        return []
    r = res[0]
    quotes = ((r.get("indicators") or {}).get("quote") or [{}])[0]
    closes = [c for c in (quotes.get("close") or []) if c is not None]
    meta = r.get("meta") or {}
    live = _f(meta.get("regularMarketPrice"))
    # Yahoo'nun son gunluk mumu ZATEN bugunun (kismi) mumudur. Canli fiyati
    # EKLERSEK son iki eleman ayni gune ait olur ve "1 gunluk degisim" 0 cikar.
    # Bu yuzden son mumu canli fiyatla DEGISTIRIYORUZ.
    if live is not None and closes:
        closes[-1] = live
    elif live is not None:
        closes = [live]
    return [float(c) for c in closes]


def _stooq_series(sym: str, days: int = 120) -> list[float]:
    csv = get_text(_STOOQ_HIST.format(sym=sym), ttl=3600, headers=_BROWSER)
    lines = [ln for ln in csv.strip().splitlines() if ln.strip()]
    if len(lines) < 2 or not lines[0].lower().startswith("date"):
        return []
    out = []
    for ln in lines[1:]:
        c = ln.split(",")
        if len(c) < 5:
            continue
        v = _f(c[4])
        if v is not None:
            out.append(v)
    return out[-days:]


def _series(yahoo_sym: str, stooq_sym: str | None, rng: str = "3mo") -> list[float]:
    """Yahoo dene, boş/hatalıysa Stooq'a düş. İkisi de yoksa []."""
    try:
        s = _yahoo_series(yahoo_sym, rng)
        if len(s) >= 5:
            return s
    except Exception as e:  # noqa: BLE001
        log.debug("yahoo %s hata: %s", yahoo_sym, e)
    if stooq_sym:
        try:
            return _stooq_series(stooq_sym)
        except Exception as e:  # noqa: BLE001
            log.debug("stooq %s hata: %s", stooq_sym, e)
    return []


def btc_daily_closes(limit: int = 120) -> list[float]:
    """BTC günlük kapanışları — Yahoo BTC-USD, olmazsa Binance klines."""
    s = _series("BTC-USD", None, rng="6mo")
    if len(s) >= 40:
        return s[-limit:]
    raw = get_json("https://api.binance.com/api/v3/klines"
                   f"?symbol=BTCUSDT&interval=1d&limit={limit}", ttl=1800)
    return [float(r[4]) for r in raw]


# ---------------------------------------------------------------- korku endeksi
def _crypto_fng(limit: int = 30) -> dict:
    d = get_json(f"{_FNG}?limit={limit}&format=json", ttl=600)
    rows = d.get("data") or []
    if not rows:
        return {"ok": False}
    series = [{"t": int(r["timestamp"]) * 1000, "value": int(r["value"])}
              for r in reversed(rows) if r.get("value") is not None]
    if not series:
        return {"ok": False}
    now = series[-1]
    prev_d = series[-2]["value"] if len(series) > 1 else now["value"]
    prev_w = series[-8]["value"] if len(series) > 7 else now["value"]
    return {"ok": True, "value": now["value"],
            "label": rows[0].get("value_classification", ""),
            "change_1d": now["value"] - prev_d,
            "change_7d": now["value"] - prev_w,
            "series": series}


def _us_fng() -> dict:
    d = get_json(_CNN, ttl=1800,
                 headers={**_BROWSER, "Referer": "https://edition.cnn.com/"})
    fg = d.get("fear_and_greed") or {}
    hist = (d.get("fear_and_greed_historical") or {}).get("data") or []
    series = [{"t": int(r["x"]), "value": round(float(r["y"]))}
              for r in hist[-30:] if r.get("y") is not None]
    val = _f(fg.get("score"))
    if val is None:
        return {"ok": False}
    return {"ok": True, "value": round(val), "label": fg.get("rating", ""),
            "change_1d": round(val - (_f(fg.get("previous_close")) or val)),
            "change_7d": round(val - (_f(fg.get("previous_1_week")) or val)),
            "series": series}


def fear_greed() -> dict:
    """Kripto + ABD korku/açgözlülük endeksleri (her biri bağımsız fail-safe)."""
    def _build() -> dict:
        out: dict = {}
        for name, fn in (("crypto", _crypto_fng), ("us", _us_fng)):
            try:
                out[name] = fn()
            except Exception as e:  # noqa: BLE001
                log.warning("%s F&G alınamadı: %s", name, e)
                out[name] = {"ok": False, "error": str(e)[:120]}
        out["ok"] = any(v.get("ok") for v in out.values() if isinstance(v, dict))
        return out
    return cached("macro:fng", 600, _build)


# ------------------------------------------------------------------- endeksler
def _index_row(item: tuple[str, tuple]) -> dict:
    ysym, (short, long_name, kind, ssym) = item
    closes = _series(ysym, ssym)
    if len(closes) < 2:
        return {"symbol": short, "name": long_name, "kind": kind, "ok": False}
    last = closes[-1]
    prev = closes[-2]
    wk = closes[-6] if len(closes) > 5 else prev
    mo = closes[-22] if len(closes) > 21 else wk
    return {
        "symbol": short, "name": long_name, "kind": kind, "ok": True,
        "value": round(last, 4),
        "change_pct": round((last - prev) / prev * 100, 2) if prev else None,
        "change_pct_7d": round((last - wk) / wk * 100, 2) if wk else None,
        "change_pct_30d": round((last - mo) / mo * 100, 2) if mo else None,
        "spark": [round(c, 4) for c in closes[-14:]],
    }


def indices() -> dict:
    """Endeks şeridi: değer, 1g/7g/30g % değişim, 14 günlük sparkline."""
    def _build() -> dict:
        items = list(INDEX_MAP.items())
        with ThreadPoolExecutor(max_workers=6) as ex:
            rows = list(ex.map(_index_row, items))
        return {"ok": any(r.get("ok") for r in rows), "rows": rows}
    return cached("macro:indices", 300, _build)


# ----------------------------------------------------------------- risk on/off
# En az bu kadar gösterge yoksa skor yayınlanmaz (tek göstergeden 100 çıkmasın).
MIN_COMPONENTS = 3


def risk_on_off() -> dict:
    """0..100 risk iştahı skoru — "Piyasa Risk Modu" paneli.

    Her gösterge +1 (risk-on) / -1 (risk-off) / 0 (nötr) oy verir; skor
    oyların ortalamasının 0..100'e ölçeklenmiş halidir. 50 = nötr.
    """
    def _build() -> dict:
        idx = indices()
        fng = fear_greed()
        by = {r["symbol"]: r for r in idx.get("rows", []) if r.get("ok")}
        comps: list[dict] = []

        def add(name, label, val, positive, detail):
            comps.append({"name": name, "label": label, "value": val,
                          "positive": positive, "detail": detail})

        v = (by.get("VIX") or {}).get("value")
        if v is not None:
            add("vix", "VIX", v, True if v < 18 else (False if v > 25 else None),
                "düşük volatilite = risk-on" if v < 18 else
                ("yüksek volatilite = risk-off" if v > 25 else "nötr bant"))
        c = (by.get("DXY") or {}).get("change_pct_7d")
        if c is not None:
            add("dxy", "DXY (7g)", c, True if c < -0.5 else (False if c > 0.5 else None),
                "zayıf dolar risk varlıklarını destekler" if c < -0.5 else
                ("güçlü dolar risk iştahını kısar" if c > 0.5 else "yatay dolar"))
        c = (by.get("US10Y") or {}).get("change_pct_7d")
        if c is not None:
            add("us10y", "ABD 10Y (7g)", c,
                True if c < -2 else (False if c > 2 else None),
                "faiz geriliyor" if c < -2 else
                ("faiz yükseliyor" if c > 2 else "faiz yatay"))
        for key, lab in (("SPX", "S&P 500 (7g)"), ("NDX", "Nasdaq 100 (7g)")):
            c = (by.get(key) or {}).get("change_pct_7d")
            if c is not None:
                add(key.lower(), lab, c,
                    True if c > 0.5 else (False if c < -0.5 else None),
                    "hisse momentumu pozitif" if c > 0.5 else
                    ("hisse momentumu negatif" if c < -0.5 else "yatay"))
        g7 = (by.get("GOLD") or {}).get("change_pct_7d")
        s7 = (by.get("SPX") or {}).get("change_pct_7d")
        if g7 is not None and s7 is not None:
            diff = s7 - g7
            add("gold_vs_spx", "Hisse − Altın (7g)", round(diff, 2),
                True if diff > 1 else (False if diff < -1 else None),
                "sermaye güvenli limandan çıkıyor" if diff > 1 else
                ("güvenli limana kaçış" if diff < -1 else "dengeli"))
        for key, lab, src in (("crypto", "Kripto F&G", fng.get("crypto") or {}),
                              ("us", "ABD F&G", fng.get("us") or {})):
            if src.get("ok"):
                v = src["value"]
                add(f"{key}_fng", lab, v,
                    True if v > 55 else (False if v < 35 else None),
                    "iştah var" if v > 55 else ("korku var" if v < 35 else "nötr"))

        if len(comps) < MIN_COMPONENTS:
            return {"ok": False, "score": 50, "mode": "veri yetersiz",
                    "components": comps, "total": len(comps),
                    "reason": f"en az {MIN_COMPONENTS} gösterge gerekli"}
        votes = [1 if c["positive"] else (-1 if c["positive"] is False else 0)
                 for c in comps]
        score = round(50 + 50 * (sum(votes) / len(votes)))
        mode = "Risk On" if score >= 62 else "Risk Off" if score <= 38 else "Nötr"
        return {"ok": True, "score": score, "mode": mode,
                "positive": sum(1 for x in votes if x > 0),
                "negative": sum(1 for x in votes if x < 0),
                "total": len(votes), "components": comps}
    return cached("macro:riskonoff", 300, _build)


# ------------------------------------------------------------------ korelasyon
def _pearson(a: list[float], b: list[float]) -> float | None:
    """Getiri (yüzde değişim) korelasyonu — fiyat seviyesi değil."""
    n = min(len(a), len(b))
    if n < 12:
        return None
    a, b = a[-n:], b[-n:]
    ra = [(a[i] - a[i - 1]) / a[i - 1] for i in range(1, n) if a[i - 1]]
    rb = [(b[i] - b[i - 1]) / b[i - 1] for i in range(1, n) if b[i - 1]]
    m = min(len(ra), len(rb))
    if m < 10:
        return None
    ra, rb = ra[-m:], rb[-m:]
    ma, mb = sum(ra) / m, sum(rb) / m
    cov = sum((ra[i] - ma) * (rb[i] - mb) for i in range(m))
    va = sum((x - ma) ** 2 for x in ra) ** 0.5
    vb = sum((x - mb) ** 2 for x in rb) ** 0.5
    if va == 0 or vb == 0:
        return None
    return round(cov / (va * vb), 3)


def correlation() -> dict:
    """BTC'nin makro varlıklarla 30 ve 90 günlük getiri korelasyonu."""
    def _build() -> dict:
        try:
            btc = btc_daily_closes(120)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:120], "rows": []}
        if len(btc) < 35:
            return {"ok": False, "error": "BTC serisi kısa", "rows": []}

        def one(item):
            ysym, (short, long_name, _kind, ssym) = item
            if short == "US10Y":
                return None
            closes = _series(ysym, ssym, rng="6mo")
            if len(closes) < 35:
                return None
            return {"symbol": short, "name": long_name,
                    "corr_30d": _pearson(btc[-31:], closes[-31:]),
                    "corr_90d": _pearson(btc[-91:], closes[-91:])}

        with ThreadPoolExecutor(max_workers=6) as ex:
            rows = [r for r in ex.map(one, INDEX_MAP.items()) if r]
        return {"ok": bool(rows), "base": "BTC", "rows": rows}
    return cached("macro:corr", 3600, _build)
