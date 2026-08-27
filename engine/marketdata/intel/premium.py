"""Coinbase Premium Endeksi — ABD kurumsal talep göstergesi (anahtarsız).

Coinbase (ABD) ile offshore borsa (Binance → OKX → Kraken yedekli) BTC fiyatı
arasındaki fark. Pozitif prim = ABD tarafında agresif alım (ETF/kurumsal talep);
negatif prim = ABD tarafında satış baskısı.

Çoklu-borsa yedeği neden var: Binance bazı ülkelerden/IP'lerden HTTP 451 döner.
İlk çalışan offshore kaynak kullanılır ve panelde `venue` alanında gösterilir.
"""
from __future__ import annotations

import logging

from engine.marketdata.http import get_json
from engine.marketdata.intel.cache import cached

log = logging.getLogger("intel.premium")

_CB_TICKER = "https://api.exchange.coinbase.com/products/{p}/ticker"
_CB_SPOT = "https://api.coinbase.com/v2/prices/{p}/spot"
_CB_CANDLES = "https://api.exchange.coinbase.com/products/{p}/candles?granularity=3600"
_BN_PRICE = "https://api.binance.com/api/v3/ticker/price?symbol={s}"
_BN_KLINES = "https://api.binance.com/api/v3/klines?symbol={s}&interval=1h&limit={n}"
_OKX_PRICE = "https://www.okx.com/api/v5/market/ticker?instId={s}"
_KRAKEN_PRICE = "https://api.kraken.com/0/public/Ticker?pair={s}"

# coin -> (coinbase ürünü, binance sembolü, okx instId, kraken çifti)
PAIRS = {
    "BTC": ("BTC-USD", "BTCUSDT", "BTC-USDT", "XBTUSDT"),
    "ETH": ("ETH-USD", "ETHUSDT", "ETH-USDT", "ETHUSDT"),
}


def _coinbase_price(product: str) -> float:
    """Coinbase Exchange, olmazsa Coinbase v2 spot."""
    try:
        return float(get_json(_CB_TICKER.format(p=product), ttl=30)["price"])
    except Exception as e:  # noqa: BLE001
        log.debug("coinbase exchange yok (%s) — v2 spot deneniyor", e)
    d = get_json(_CB_SPOT.format(p=product), ttl=30)
    return float(((d or {}).get("data") or {})["amount"])


def _offshore_price(coin: str) -> tuple[float, str]:
    """İlk çalışan offshore fiyat kaynağı: Binance → OKX → Kraken."""
    _cb, bn, okx, kr = PAIRS[coin]
    try:
        return float(get_json(_BN_PRICE.format(s=bn), ttl=30)["price"]), "binance"
    except Exception as e:  # noqa: BLE001
        log.debug("binance fiyatı yok (%s)", e)
    try:
        d = get_json(_OKX_PRICE.format(s=okx), ttl=30)
        return float((d["data"] or [{}])[0]["last"]), "okx"
    except Exception as e:  # noqa: BLE001
        log.debug("okx fiyatı yok (%s)", e)
    d = get_json(_KRAKEN_PRICE.format(s=kr), ttl=30)
    res = (d.get("result") or {})
    first = next(iter(res.values()))
    return float(first["c"][0]), "kraken"


def _spot(coin: str) -> dict:
    cb_p = PAIRS[coin][0]
    cb = _coinbase_price(cb_p)
    off, venue = _offshore_price(coin)
    if off <= 0:
        raise ValueError("offshore fiyat 0")
    return {"coin": coin, "coinbase": round(cb, 2), "offshore": round(off, 2),
            "venue": venue, "premium_usd": round(cb - off, 2),
            "premium_pct": round((cb - off) / off * 100, 4)}


def _history(coin: str, hours: int = 72) -> list[dict]:
    """Saatlik prim serisi (Coinbase + Binance mumları). Binance yoksa boş."""
    cb_p, bn_s, _okx, _kr = PAIRS[coin]
    cb_raw = get_json(_CB_CANDLES.format(p=cb_p), ttl=900)
    # Coinbase: [time, low, high, open, close, volume] — yeniden eskiye
    cb_map = {int(r[0]) // 3600 * 3600: float(r[4]) for r in cb_raw}
    bn_raw = get_json(_BN_KLINES.format(s=bn_s, n=min(hours, 500)), ttl=900)
    out = []
    for r in bn_raw:
        ts = int(r[0]) // 1000
        cb = cb_map.get(ts // 3600 * 3600)
        bn = float(r[4])
        if cb is None or bn <= 0:
            continue
        out.append({"t": ts * 1000, "premium_pct": round((cb - bn) / bn * 100, 4)})
    return out[-hours:]


def premium() -> dict:
    """BTC + ETH Coinbase primi (anlık + 72 saatlik seri + yorum)."""
    def _build() -> dict:
        rows, series = [], {}
        for coin in PAIRS:
            try:
                rows.append(_spot(coin))
            except Exception as e:  # noqa: BLE001
                log.warning("%s primi alınamadı: %s", coin, e)
        for coin in PAIRS:
            try:
                series[coin] = _history(coin)
            except Exception:  # noqa: BLE001
                series[coin] = []
        btc = next((r for r in rows if r["coin"] == "BTC"), None)
        note, bias = "veri yok", 0.0
        if btc:
            p = btc["premium_pct"]
            if p >= 0.05:
                note, bias = "ABD tarafında güçlü alım (kurumsal talep)", 1.0
            elif p >= 0.01:
                note, bias = "hafif pozitif prim", 0.4
            elif p <= -0.05:
                note, bias = "ABD tarafında satış baskısı", -1.0
            elif p <= -0.01:
                note, bias = "hafif negatif prim", -0.4
            else:
                note, bias = "prim nötr", 0.0
        return {"ok": bool(rows), "rows": rows, "series": series,
                "note": note, "bias": bias}
    return cached("premium", 60, _build)
