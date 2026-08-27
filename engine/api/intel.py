"""/intel/* — Piyasa İstihbaratı uçları (Electron "Piyasa İstihbaratı" sekmesi).

Tüm uçlar TTL cache'li ve fail-safe'tir: upstream düşse bile en son başarılı
veri `stale` işaretiyle döner, panel boşalmaz. Anahtar isteyen kaynaklar
(CoinGlass/CMC/Nansen) yoksa ilgili panel `enabled=false` + gerekçe döner.

Uçlar:
    GET /intel/overview              tüm paneller (paralel)
    GET /intel/group/{macro|onchain|hl}
    GET /intel/panel/{ad}            tek panel
    GET /intel/sources               kaynak/anahtar durumu + tazelik
    GET /intel/bias                  sinyale beslenen birleşik yapı skoru
    GET /intel/taker/{symbol}        taker alım/satım dengesi
    GET /intel/refresh               tazelemeyi elle tetikle
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from engine.marketdata import intel as intel_mod
from engine.marketdata.intel import bias as bias_mod
from engine.marketdata.intel import flows as flows_mod
from engine.marketdata.intel.refresher import refresher

log = logging.getLogger("api.intel")

router = APIRouter(prefix="/intel", tags=["intel"])

_GROUPS = ("macro", "onchain", "hl")


@router.get("/overview")
def overview() -> dict:
    """Tüm paneller tek yanıtta (UI ilk yüklemesi)."""
    return {"panels": intel_mod.snapshot(),
            "sources": intel_mod.sources(),
            "bias": bias_mod.market_bias(),
            "refresher": refresher.status()}


@router.get("/group/{group}")
def group(group: str) -> dict:
    if group not in _GROUPS:
        raise HTTPException(404, f"bilinmeyen grup: {group} ({'|'.join(_GROUPS)})")
    return {"group": group, "panels": intel_mod.snapshot(group=group)}


@router.get("/panel/{name}")
def panel(name: str) -> dict:
    try:
        return {"name": name, "data": intel_mod.panel(name)}
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/sources")
def sources() -> dict:
    return intel_mod.sources()


@router.get("/bias")
def bias(symbol: str | None = None) -> dict:
    """Sinyal motoruna giren yapısal bias — UI'da "neden" olarak gösterilir."""
    return bias_mod.combined(symbol)


@router.get("/taker/{symbol}")
def taker(symbol: str, period: str = "1h") -> dict:
    try:
        return flows_mod.taker_flow(symbol, period=period)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "symbol": symbol.upper(), "error": str(e)[:160]}


@router.get("/refresh")
def refresh() -> dict:
    """Panelleri hemen tazele (UI'daki yenile düğmesi)."""
    panels = intel_mod.snapshot()
    ok = sum(1 for v in panels.values() if isinstance(v, dict) and v.get("ok"))
    return {"ok": True, "refreshed": len(panels), "healthy": ok,
            "refresher": refresher.status()}
