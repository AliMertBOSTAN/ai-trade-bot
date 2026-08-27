"""Spot ETF akışları (BTC / ETH) — kurumsal talep göstergesi.

Birincil kaynak: CoinGlass (COINGLASS_API_KEY) → gerçek net akış (USD).
Anahtar yoksa ÜCRETSİZ VEKİL hesaplanır: ABD spot ETF'lerinin (IBIT, FBTC,
GBTC, ARKB…) günlük getirisi × dolar hacmi toplanarak net alım/satım baskısının
YÖNÜ ve göreli şiddeti tahmin edilir.

Vekil, gerçek net akışın dolar tutarını VERMEZ; panelde `source: "proxy"` ve
açık bir not ile işaretlenir. Kaynak: Yahoo Finance chart API (anahtarsız).
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from engine.marketdata.http import get_json
from engine.marketdata.intel import coinglass
from engine.marketdata.intel.cache import cached

log = logging.getLogger("intel.etf")

_YF = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
       "?range=2mo&interval=1d")
_BROWSER = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"),
    "Accept": "application/json,text/plain,*/*",
}

# ABD spot BTC / ETH ETF'leri
BTC_ETFS = ["IBIT", "FBTC", "GBTC", "ARKB", "BITB", "HODL", "BRRR", "BTCO"]
ETH_ETFS = ["ETHA", "FETH", "ETHE", "ETHW", "QETH"]


def _f(x, d: float | None = None) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def _yahoo_ohlcv(sym: str) -> list[dict]:
    """[{t, close, volume}] — günlük. Hata/boş -> []."""
    d = get_json(_YF.format(sym=sym), ttl=3600, headers=_BROWSER)
    res = ((d or {}).get("chart") or {}).get("result") or []
    if not res:
        return []
    r = res[0]
    ts = r.get("timestamp") or []
    q = ((r.get("indicators") or {}).get("quote") or [{}])[0]
    closes, vols = q.get("close") or [], q.get("volume") or []
    out = []
    for i, t in enumerate(ts):
        c = _f(closes[i] if i < len(closes) else None)
        v = _f(vols[i] if i < len(vols) else None)
        if c is None or v is None:
            continue
        out.append({"t": int(t) * 1000, "close": c, "volume": v})
    return out


def _proxy(asset: str) -> dict:
    """Yönlü dolar hacmi ile net akış VEKİLİ (dolar tutarı değil, şiddet)."""
    syms = BTC_ETFS if asset == "bitcoin" else ETH_ETFS

    def one(s: str):
        try:
            return s, _yahoo_ohlcv(s)
        except Exception as e:  # noqa: BLE001
            log.debug("%s ETF verisi yok: %s", s, e)
            return s, []

    per_day: dict[int, float] = {}
    used: list[str] = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for s, rows in ex.map(one, syms):
            if len(rows) < 3:
                continue
            used.append(s)
            for i in range(1, len(rows)):
                prev, cur = rows[i - 1], rows[i]
                if prev["close"] <= 0:
                    continue
                ret = (cur["close"] - prev["close"]) / prev["close"]
                per_day[cur["t"]] = (per_day.get(cur["t"], 0.0)
                                     + ret * cur["volume"] * cur["close"])
    if not per_day:
        return {"ok": False, "source": "proxy", "asset": asset, "rows": [],
                "etfs": [], "bias": 0.0,
                "reason": "ETF fiyat/hacim verisi alınamadı"}
    rows = [{"t": t, "flow_proxy_usd": round(v, 0)}
            for t, v in sorted(per_day.items())][-30:]
    last5 = sum(r["flow_proxy_usd"] for r in rows[-5:])
    avg = (sum(abs(r["flow_proxy_usd"]) for r in rows) / len(rows)) or 1.0
    bias = max(-1.0, min(1.0, last5 / (avg * 5)))
    return {"ok": True, "source": "proxy", "asset": asset, "rows": rows,
            "etfs": used, "flow_5d": round(last5, 0), "bias": round(bias, 3),
            "note": ("5 günlük net ALIM baskısı" if last5 > 0
                     else "5 günlük net SATIŞ baskısı"),
            "disclaimer": ("CoinGlass anahtarı yok — yön/şiddet vekili "
                           "(dolar tutarı DEĞİL)")}


def flows(asset: str = "bitcoin") -> dict:
    """ETF net akışı. CoinGlass varsa gerçek dolar, yoksa vekil."""
    def _build() -> dict:
        if coinglass.enabled():
            cg = coinglass.etf_flow_history(asset)
            if cg.get("ok") and cg.get("rows"):
                rows = [{"t": r["t"], "flow_usd": r["flow_usd"]} for r in cg["rows"]]
                last5 = sum(r["flow_usd"] for r in rows[-5:])
                last30 = sum(r["flow_usd"] for r in rows[-30:])
                avg = (sum(abs(r["flow_usd"]) for r in rows[-30:]) / 30) or 1.0
                return {"ok": True, "source": "coinglass", "asset": asset,
                        "rows": rows, "flow_1d": rows[-1]["flow_usd"] if rows else 0,
                        "flow_5d": round(last5, 0), "flow_30d": round(last30, 0),
                        "bias": round(max(-1.0, min(1.0, last5 / (avg * 5))), 3),
                        "note": ("kurumsal giriş sürüyor" if last5 > 0
                                 else "kurumsal çıkış var")}
            log.info("coinglass ETF akışı boş — vekile düşülüyor")
        return _proxy(asset)
    return cached(f"etf:{asset}", 1800, _build)


def summary() -> dict:
    """BTC + ETH ETF akış özeti (bias BTC'den alınır)."""
    out: dict = {}
    for asset in ("bitcoin", "ethereum"):
        try:
            out[asset] = flows(asset)
        except Exception as e:  # noqa: BLE001
            out[asset] = {"ok": False, "reason": str(e)[:140], "rows": []}
    btc = out.get("bitcoin") or {}
    out["ok"] = bool(btc.get("ok"))
    out["source"] = btc.get("source")
    out["bias"] = btc.get("bias", 0.0)
    out["note"] = btc.get("note")
    out["disclaimer"] = btc.get("disclaimer")
    return out
