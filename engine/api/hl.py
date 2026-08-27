"""/hl/* — Hyperliquid perp işlem masası uçları.

Elle gönderilen emirler de, AI otopilotun emirleri de AYNI risk kapısından
(`engine/risk/hl_risk.check`) geçer. Buradaki uçlar o kapıyı atlamaz.

Güvenlik notları:
  · Canlı emir için hem imzalayıcı (API wallet veya keystore) hem de HL_LIVE=1
    gerekir. İkisinden biri eksikse broker kağıt modda kalır ve bunu `live`
    alanında gerekçesiyle bildirir.
  · Anahtarlar hiçbir yanıtta dönmez; yalnızca "var/yok" bilgisi verilir.
  · Pozisyon KAPATMA hiçbir kapıdan engellenmez (risk azaltmak her zaman serbest).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from engine.risk import hl_risk
from engine.trading.hl_broker import hl, normalize_symbol, universe

log = logging.getLogger("api.hl")

router = APIRouter(prefix="/hl", tags=["hyperliquid"])


class OrderIn(BaseModel):
    symbol: str
    side: str = Field(description="LONG | SHORT")
    notional_usd: float | None = None
    size: float | None = None
    leverage: int = 3
    order_type: str = "market"          # market | limit
    limit_price: float | None = None
    reduce_only: bool = False


class CloseIn(BaseModel):
    symbol: str
    size: float | None = None           # None = tamamı


class LeverageIn(BaseModel):
    symbol: str
    leverage: int
    cross: bool = False


class ResetIn(BaseModel):
    seed_usd: float = 1000.0


@router.get("/state")
def state() -> dict:
    """Hesap durumu: equity, teminat, açık pozisyonlar, likidasyon fiyatları."""
    try:
        st = hl.state()
    except Exception as e:  # noqa: BLE001
        log.warning("hl durum hatası: %s", e)
        return {"ok": False, "error": str(e)[:160], "positions": []}
    st["limits"] = hl_risk.limits()
    return st


@router.get("/universe")
def hl_universe(limit: int = 400) -> dict:
    """İşlem yapılabilir perp listesi (mark, 24s değişim, funding, azami kaldıraç).

    Arayüzdeki piyasa listesi bunu kullanır; bu yüzden varsayılan limit TÜM
    evreni kapsayacak kadar yüksektir (~180 perp). Hata durumunda `ok=false` +
    `error` döner — arayüz bunu sessizce yutmaz, gerekçeyi gösterir.
    """
    try:
        rows = sorted(universe().values(), key=lambda r: -r["day_volume_usd"])
    except Exception as e:  # noqa: BLE001
        log.warning("hl evreni alınamadı: %s", e)
        return {"ok": False, "count": 0, "rows": [],
                "error": f"Hyperliquid piyasa listesi alınamadı: {str(e)[:140]}"}
    if not rows:
        return {"ok": False, "count": 0, "rows": [],
                "error": "Hyperliquid boş evren döndürdü (geçici olabilir)"}
    for r in rows:
        prev = r.get("prev_day_px") or 0
        r["change_pct_24h"] = (round((r["mark"] - prev) / prev * 100, 2)
                               if prev else None)
    return {"ok": True, "count": len(rows), "rows": rows[:limit]}


@router.get("/health")
def health() -> dict:
    """Tek çağrıda tanı: HL API erişilebilir mi, kaç perp var, imzalayıcı hazır mı.

    Arayüz "işlem sekmesi çalışmıyor" durumunda ilk buraya bakar; hangi halkanın
    koptuğu (engine / Hyperliquid / imzalayıcı) buradan anlaşılır.
    """
    out: dict = {"engine": True, "routes": "hl+analyst", "hyperliquid": False,
                 "markets": 0, "error": None}
    try:
        u = universe()
        out["hyperliquid"] = bool(u)
        out["markets"] = len(u)
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:160]
    out["live"] = hl.live_ready()
    out["limits"] = hl_risk.limits()
    return out


@router.get("/limits")
def get_limits() -> dict:
    """Yürürlükteki risk tavanları (elle ve AI için ayrı)."""
    return {"manual": hl_risk.limits(), "ai": hl_risk.limits(for_ai=True)}


@router.post("/preview")
def preview(o: OrderIn) -> dict:
    """Emri GÖNDERMEDEN kapı sonucunu ve likidasyon fiyatını göster."""
    from engine.trading.hl_broker import liquidation_price
    sym = normalize_symbol(o.symbol)
    u = universe().get(sym)
    if not u:
        raise HTTPException(404, f"{sym} Hyperliquid perp evreninde yok")
    mark = u["mark"]
    notional = o.notional_usd if o.notional_usd else (o.size or 0) * mark
    st = hl.state()
    d = hl_risk.check(symbol=sym, side=o.side, notional_usd=notional,
                      leverage=o.leverage, state=st)
    lev = d.leverage or o.leverage
    return {
        "symbol": sym, "mark": mark, "side": o.side.upper(),
        "decision": d.to_dict(),
        "size": round((d.notional_usd or notional) / mark, 6),
        "margin_usd": round((d.notional_usd or notional) / max(1, lev), 2),
        "liq_price": liquidation_price(mark, lev, o.side.upper(), sym),
        "max_leverage": u["max_leverage"],
        "funding_hourly_pct": round(u["funding_hourly"] * 100, 5),
    }


@router.post("/order")
def order(o: OrderIn) -> dict:
    """Elle emir. Risk kapısından geçer; reddedilirse HTTP 200 + gerekçe döner."""
    sym = normalize_symbol(o.symbol)
    u = universe().get(sym)
    if not u:
        raise HTTPException(404, f"{sym} Hyperliquid perp evreninde yok")
    notional = o.notional_usd if o.notional_usd else (o.size or 0) * u["mark"]
    st = hl.state()
    d = hl_risk.check(symbol=sym, side=o.side, notional_usd=notional,
                      leverage=o.leverage, state=st)
    if not d.approved:
        return {"ok": False, "blocked": True, "reason": d.reason,
                "decision": d.to_dict()}
    res = hl.open(sym, o.side, notional_usd=d.notional_usd,
                  leverage=d.leverage, order_type=o.order_type,
                  limit_price=o.limit_price, reduce_only=o.reduce_only,
                  source="manual")
    if res.get("ok"):
        hl_risk.note_order(sym)
    res["decision"] = d.to_dict()
    return res


@router.post("/close")
def close(c: CloseIn) -> dict:
    """Pozisyon kapat. Risk kapısı UYGULANMAZ — riski azaltmak hep serbesttir."""
    return hl.close(c.symbol, c.size, source="manual")


@router.post("/leverage")
def leverage(l: LeverageIn) -> dict:
    return hl.set_leverage(l.symbol, l.leverage, l.cross)


@router.post("/paper/reset")
def paper_reset(r: ResetIn) -> dict:
    """Kağıt defterini sıfırla (canlı hesabı ETKİLEMEZ)."""
    return hl.reset_paper(r.seed_usd)


@router.get("/live/status")
def live_status() -> dict:
    """Canlı emir gönderilebilir mi ve gönderilemiyorsa hangi adım eksik."""
    return hl.live_ready()
