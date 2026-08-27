"""/analyst/* — AI analist uçları (elle çalıştırma + otonom tarama).

`/analyst/{symbol}` mevcut app.py ucudur ve korunur; buradaki router onun
üstüne derinlik seçimi, sembol evreni ve otonom tarama kontrolünü ekler.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from engine.marketdata import analyst as analyst_mod
from engine.marketdata.ai_analyst import ai_analyst, watchlist

log = logging.getLogger("api.analyst")

router = APIRouter(prefix="/analyst", tags=["analyst"])


class RunIn(BaseModel):
    symbol: str
    depth: str | None = None      # kisa | normal | derin | cok_derin | "1800"


@router.get("/depths")
def depths() -> dict:
    """Seçilebilir analiz derinlikleri ve token bütçeleri."""
    return {
        "default": analyst_mod.DEFAULT_DEPTH,
        "options": [
            {"id": "kisa", "label": "Kısa", "tokens": analyst_mod.DEPTHS["kisa"],
             "note": "tek paragraf görüş — en ucuz"},
            {"id": "normal", "label": "Normal", "tokens": analyst_mod.DEPTHS["normal"],
             "note": "seviyeler + senaryolar (varsayılan)"},
            {"id": "derin", "label": "Derin", "tokens": analyst_mod.DEPTHS["derin"],
             "note": "tam gerekçe + işlem planı"},
            {"id": "cok_derin", "label": "Çok derin",
             "tokens": analyst_mod.DEPTHS["cok_derin"],
             "note": "en ayrıntılı — en pahalı"},
        ],
    }


@router.get("/universe")
def universe(limit: int = 250) -> dict:
    """Analiz edilebilecek semboller — Hyperliquid + Binance + izleme listesi.

    Arayüzdeki sabit 8 sembollük liste yerine bunu kullanır; arama kutusundan
    yüzlerce token seçilebilir.
    """
    rows: list[dict] = []
    seen: set[str] = set()

    def add(sym: str, source: str, extra: dict | None = None) -> None:
        s = sym.upper()
        if not s or s in seen:
            return
        seen.add(s)
        rows.append({"symbol": s, "source": source, **(extra or {})})

    for s in watchlist():
        add(s, "watchlist")
    try:
        from engine.trading.hl_broker import universe as hl_universe
        for u in sorted(hl_universe().values(), key=lambda r: -r["day_volume_usd"]):
            add(u["symbol"], "hyperliquid",
                {"mark": u["mark"], "max_leverage": u["max_leverage"],
                 "volume_usd": u["day_volume_usd"], "perp": True})
    except Exception as e:  # noqa: BLE001
        log.warning("hl evreni alınamadı: %s", e)
    try:
        from engine.marketdata import binance as bn
        for t in bn.top_symbols(limit=150) if hasattr(bn, "top_symbols") else []:
            add(str(t).replace("USDT", ""), "binance")
    except Exception:  # noqa: BLE001
        pass
    return {"ok": bool(rows), "count": len(rows), "rows": rows[:limit]}


@router.post("/run")
def run(r: RunIn) -> dict:
    """Tek sembolü seçilen derinlikte analiz et (elle tetikleme)."""
    return analyst_mod.analyze(r.symbol, depth=r.depth)


@router.get("/auto/status")
def auto_status() -> dict:
    return ai_analyst.status()


@router.get("/auto/reports")
def auto_reports(limit: int = 30) -> dict:
    """Otonom analistin son kararları (en yeni önce)."""
    ai_analyst._load()
    return {"reports": ai_analyst.log[-limit:][::-1],
            "by_symbol": ai_analyst.reports,
            "status": ai_analyst.status()}


@router.get("/decision/{symbol}")
def decision(symbol: str, refresh: bool = False, depth: str | None = None) -> dict:
    """Bir pair için AI kararı: POZİSYON AL / BEKLE / GİRME + gerekçe.

    Otopilot kapalı olsa bile karar üretilir; `executed=false` olur ve `reason`
    neden işleme dönmediğini söyler. `refresh=1` önce yeni analiz çalıştırır
    (LLM tokenı harcar).
    """
    if refresh:
        summary = ai_analyst.analyze_one(symbol, "elle-tetik")
        if not summary.get("ok", True):
            return {"state": "BLOCKED", "label": "GİRME", "verdict": "avoid",
                    "symbol": symbol.upper(), "executed": False,
                    "reason": summary.get("error") or "analiz başarısız"}
    return ai_analyst.last_decision(symbol)


@router.post("/decision/{symbol}/dry-run")
def decision_dry_run(symbol: str) -> dict:
    """Son analizi risk kapısından TEKRAR geçir ama emir GÖNDERME.

    Tavanları .env'de değiştirdikten sonra "şimdi geçer miydi" diye bakmak için.
    """
    ai_analyst._load()
    rep = ai_analyst.reports.get(symbol.upper())
    if not rep:
        return {"state": "NO_SCAN", "label": "BEKLE", "verdict": "wait",
                "symbol": symbol.upper(), "executed": False,
                "reason": "Bu pair için henüz analiz yok."}
    return ai_analyst.decide(rep, execute=False)


@router.post("/auto/scan")
def auto_scan(symbol: str | None = None) -> dict:
    """Taramayı hemen tetikle. symbol verilmezse tüm izleme listesi sıraya girer."""
    targets = [symbol.upper()] if symbol else watchlist()
    for s in targets:
        ai_analyst.request(s, "elle-tetik")
    if not (ai_analyst._thread and ai_analyst._thread.is_alive()):
        # Döngü kapalıysa senkron çalıştır ki UI boş dönmesin.
        out = [ai_analyst.analyze_one(s, "elle-tetik") for s in targets[:3]]
        return {"ok": True, "ran_inline": True, "reports": out}
    return {"ok": True, "queued": targets}
