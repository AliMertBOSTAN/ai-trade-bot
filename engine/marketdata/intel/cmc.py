"""CoinMarketCap adaptörü (opsiyonel, CMC_API_KEY).

Anahtar yoksa `enabled()` False döner ve çağıran taraf CoinGecko'ya düşer.
Kullanılan uçlar Basic (ücretsiz) planda da mevcuttur.
"""
from __future__ import annotations

import logging

from engine.marketdata.http import get_json
from engine.marketdata.intel import keys

log = logging.getLogger("intel.cmc")

BASE = "https://pro-api.coinmarketcap.com/v1"


def enabled() -> bool:
    return bool(keys.cmc())


def _get(path: str, ttl: float = 600.0):
    key = keys.cmc()
    if not key:
        raise RuntimeError("CMC_API_KEY yok")
    d = get_json(f"{BASE}{path}", ttl=ttl,
                 headers={"X-CMC_PRO_API_KEY": key, "Accept": "application/json"})
    status = (d or {}).get("status") or {}
    if status.get("error_code"):
        raise RuntimeError(f"cmc hata {status['error_code']}: "
                           f"{str(status.get('error_message'))[:80]}")
    return (d or {}).get("data")


def global_metrics() -> dict:
    if not enabled():
        return keys.disabled("coinmarketcap", "CMC_API_KEY")
    try:
        d = _get("/global-metrics/quotes/latest") or {}
    except Exception as e:  # noqa: BLE001
        log.warning("cmc global alınamadı: %s", e)
        return {"enabled": True, "ok": False, "reason": str(e)[:140]}
    q = ((d.get("quote") or {}).get("USD")) or {}
    return {"enabled": True, "ok": True, "source": "coinmarketcap",
            "btc_dominance": d.get("btc_dominance"),
            "eth_dominance": d.get("eth_dominance"),
            "stable_dominance": d.get("stablecoin_market_cap") and round(
                (d["stablecoin_market_cap"] / q["total_market_cap"] * 100), 2)
            if q.get("total_market_cap") else None,
            "total_market_cap_usd": q.get("total_market_cap"),
            "total_volume_usd": q.get("total_volume_24h"),
            "defi_market_cap": d.get("defi_market_cap"),
            "altcoin_market_cap": d.get("altcoin_market_cap"),
            "mcap_change_24h": q.get("total_market_cap_yesterday_percentage_change")}
