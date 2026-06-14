"""CoinGecko açık OHLC (API key gerekmez) — Binance'te olmayan tokenlar için yedek.

Binance yalnızca listeli major/coin'leri kapsar; DEX tokenları (ör. DEGEN)
için CoinGecko'nun /coins/{id}/ohlc ucu gerçek OHLC mum verir. Hacim
dönmediğinden hacim göstergeleri (OBV/VWAP/MFI) close-only güvenli moda düşer.

Not: CoinMarketCap'in OHLCV ucu ücretli API key ister; CoinGecko aynı geniş
token kapsamını ücretsiz/anahtarsız sağladığı için yedek kaynak olarak seçildi.
"""
from __future__ import annotations

import logging

from engine.marketdata.http import get_json

log = logging.getLogger("marketdata.coingecko")

BASE = "https://api.coingecko.com/api/v3"

# Sembol -> CoinGecko id (bot token evreni + yaygınlar). Bilinmeyenler
# /coins/list üzerinden sembolle çözülür (gün boyu cache'li).
_IDS = {
    "BTC": "bitcoin", "ETH": "ethereum", "BNB": "binancecoin",
    "MATIC": "matic-network", "ARB": "arbitrum", "OP": "optimism",
    "LINK": "chainlink", "UNI": "uniswap", "GMX": "gmx",
    "CAKE": "pancakeswap-token", "DEGEN": "degen-base",
    "USDC": "usd-coin", "USDT": "tether",
}

# interval -> gün penceresi (CG mum granülerliğini days'e göre otomatik seçer:
# 1g->30dk, 2-30g->4s, 31g+->günlük civarı).
_DAYS = {"15m": 1, "1h": 7, "4h": 30, "1d": 180}


def resolve_id(symbol: str) -> str | None:
    """Sembolü CoinGecko coin id'sine çevirir (curated map -> /coins/list)."""
    s = symbol.upper()
    if s in _IDS:
        return _IDS[s]
    try:
        lst = get_json(f"{BASE}/coins/list", ttl=86_400)  # 1 gün cache
    except Exception as e:
        log.warning("coins/list alınamadı: %s", e)
        return None
    sl = symbol.lower()
    matches = [c["id"] for c in lst if (c.get("symbol") or "").lower() == sl]
    return matches[0] if matches else None


def ohlc(symbol: str, interval: str = "1h", limit: int = 200) -> list[dict]:
    """Token için OHLC mumları (hacim yok -> 0.0). Çözülemezse boş liste."""
    cid = resolve_id(symbol)
    if not cid:
        return []
    days = _DAYS.get(interval, 7)
    try:
        raw = get_json(
            f"{BASE}/coins/{cid}/ohlc?vs_currency=usd&days={days}", ttl=60)
    except Exception as e:
        log.warning("%s ohlc alınamadı: %s", cid, e)
        return []
    candles = [{
        "t": int(r[0]),
        "open": float(r[1]), "high": float(r[2]),
        "low": float(r[3]), "close": float(r[4]),
        "volume": 0.0,
    } for r in raw]
    return candles[-limit:]
