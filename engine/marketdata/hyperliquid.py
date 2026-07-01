"""Hyperliquid perp (kaldıraçlı) DEX fiyat okuyucu — public API, key gerekmez.

POST https://api.hyperliquid.xyz/info  body={"type":"metaAndAssetCtxs"} ->
[meta, assetCtxs]; universe[i] ile assetCtxs[i] hizalıdır. Her perp için
mark fiyat, 24s değişim, 24s notional hacim, funding, open interest ve
maksimum kaldıraç döndürür. Sonuç TTL cache'lenir; hata -> son cache veya [].

Bu, Keşfet ekranındaki "Hyperliquid · Perp (kaldıraçlı)" piyasasının kaynağıdır.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request

log = logging.getLogger("marketdata.hyperliquid")

_URL = "https://api.hyperliquid.xyz/info"
_UA = "ai-trade-bot/0.2 (+public-data)"
_TTL = 15.0  # saniye
_cache: tuple[float, list[dict]] | None = None


def _post(payload: dict, timeout: float = 15.0):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        _URL, data=data, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _f(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def perp_contexts() -> list[dict]:
    """Tüm Hyperliquid perp bağlamları (TTL cache'li). Hata -> son cache / []."""
    global _cache
    now = time.time()
    if _cache and now - _cache[0] < _TTL:
        return _cache[1]
    try:
        meta, ctxs = _post({"type": "metaAndAssetCtxs"})
        universe = meta.get("universe", [])
        out: list[dict] = []
        for u, c in zip(universe, ctxs):
            name = u.get("name", "")
            if not name or u.get("isDelisted"):
                continue
            mark = _f(c.get("markPx") or c.get("midPx"))
            if mark <= 0:
                continue
            prev = _f(c.get("prevDayPx"))
            chg = ((mark - prev) / prev * 100) if prev else None
            oi_coin = _f(c.get("openInterest"))
            out.append({
                "symbol": name,
                "price": mark,
                "change_pct_24h": chg,
                "volume_usd": _f(c.get("dayNtlVlm")),
                "funding_pct": _f(c.get("funding")) * 100,  # saatlik funding (%)
                "open_interest_usd": oi_coin * mark,
                "max_leverage": int(u.get("maxLeverage", 0) or 0),
            })
        _cache = (now, out)
        return out
    except Exception as e:  # pragma: no cover - ağ hatası
        log.warning("Hyperliquid alınamadı: %s", e)
        return _cache[1] if _cache else []
