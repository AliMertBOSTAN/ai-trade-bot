"""Solana meme coin / fırsat tarayıcı — DexScreener public API (key gerekmez).

Solana EVM olmadığından zincir-okuma altyapısına (engine.dex / chains.py) girmez;
bu modül yalnızca Keşfet ekranı için DexScreener üzerinden Solana token verisi
sağlar:

  - "boosted/trending" tokenlar (anlık fırsatlar / yeni çıkanlar)
  - + birkaç köklü meme (WIF/BONK) her zaman listede dursun diye
  - her token için EN LİKİT havuzun fiyat / 24s% / hacim / likidite / market cap

Fail-safe: kaynak düşerse [] döner. Sonuç TTL cache'lenir.
"""
from __future__ import annotations

import logging
import time

from engine.marketdata.http import get_json

log = logging.getLogger("marketdata.solana")

DS = "https://api.dexscreener.com"
_BOOSTS = f"{DS}/token-boosts/latest/v1"

# Köklü Solana memeleri (adresler DexScreener'dan doğrulandı) — her zaman göster.
ANCHORS = {
    "WIF": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
    "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
}

_MIN_LIQ_USD = 15_000.0   # bu likiditenin altındaki gürültüyü ele
_TTL = 30.0               # saniye
_cache: tuple[float, list[dict]] | None = None


def _boosted_addresses(limit: int = 28) -> list[str]:
    """DexScreener'da öne çıkarılan (trending) Solana token adresleri."""
    try:
        data = get_json(_BOOSTS, ttl=60)
    except Exception as e:  # pragma: no cover
        log.debug("boosts alınamadı: %s", e)
        return []
    out: list[str] = []
    seen: set[str] = set()
    for b in data or []:
        if b.get("chainId") != "solana":
            continue
        a = b.get("tokenAddress")
        if a and a not in seen:
            seen.add(a)
            out.append(a)
        if len(out) >= limit:
            break
    return out


def _best_pair_per_token(addresses: list[str]) -> dict[str, dict]:
    """tokens/{addr,...} (30'arlık parçalar) -> {token_address: en_likit_pair}."""
    result: dict[str, dict] = {}
    for i in range(0, len(addresses), 30):
        chunk = addresses[i:i + 30]
        try:
            d = get_json(f"{DS}/latest/dex/tokens/{','.join(chunk)}", ttl=20)
        except Exception as e:  # pragma: no cover
            log.debug("tokens alınamadı: %s", e)
            continue
        for p in (d.get("pairs") or []):
            if p.get("chainId") != "solana":
                continue
            addr = ((p.get("baseToken") or {}).get("address") or "")
            if not addr:
                continue
            liq = float((p.get("liquidity") or {}).get("usd") or 0)
            cur = result.get(addr)
            if cur is None or liq > cur["_liq"]:
                result[addr] = {"_liq": liq, "pair": p}
    return {a: v["pair"] for a, v in result.items()}


def _instrument(p: dict) -> dict:
    bt = p.get("baseToken") or {}
    return {
        "market": "solana",
        "symbol": bt.get("symbol", "?"),
        "quote": (p.get("quoteToken") or {}).get("symbol", "SOL"),
        "venue": p.get("dexId", "solana"),
        "chain_id": None,
        "price": float(p.get("priceUsd") or 0),
        "change_pct_24h": float((p.get("priceChange") or {}).get("h24") or 0),
        "liquidity_usd": float((p.get("liquidity") or {}).get("usd") or 0),
        "volume_usd": float((p.get("volume") or {}).get("h24") or 0),
        "kind": "spot",
        "market_cap_usd": float(p.get("marketCap") or p.get("fdv") or 0),
        "url": p.get("url"),
    }


def solana_instruments() -> list[dict]:
    """Solana meme/fırsat enstrümanları (TTL cache'li, hacme göre sıralı)."""
    global _cache
    now = time.time()
    if _cache and now - _cache[0] < _TTL:
        return _cache[1]
    addrs = list(dict.fromkeys(list(ANCHORS.values()) + _boosted_addresses()))
    if not addrs:
        return _cache[1] if _cache else []
    pairs = _best_pair_per_token(addrs)
    out = [_instrument(p) for p in pairs.values()]
    out = [i for i in out if i["price"] > 0 and i["liquidity_usd"] >= _MIN_LIQ_USD]
    out.sort(key=lambda i: i["volume_usd"], reverse=True)
    _cache = (now, out)
    return out
