"""Türev piyasası & likidasyon sinyalleri — anahtarsız (Binance Futures public).

Spot balina baskısını (whales.py) tamamlar. Üç keyless sinyal birleştirilir:
  1) FUNDING RATE (/fapi premiumIndex): aşırı pozitif → kalabalık LONG (long-squeeze
     riski, fiyat düşebilir); aşırı negatif → kalabalık SHORT (short-squeeze, yukarı).
  2) OPEN INTEREST değişimi (openInterestHist): OI artışı pozisyon birikimi; ani
     OI düşüşü + fiyat hareketi = likidasyon kaskadı işareti.
  3) LONG/SHORT hesap oranı (globalLongShortAccountRatio): aşırı uçlar contrarian.

Likidasyon "squeeze yönü" türetilir: +1 short-squeeze (yukarı baskı potansiyeli),
-1 long-squeeze (aşağı baskı), 0 nötr. Hata durumunda nötr/boş döner (fail-safe).
"""
from __future__ import annotations

import logging

from engine.marketdata.http import get_json

log = logging.getLogger("marketdata.derivatives")

FBASE = "https://fapi.binance.com"

# Funding eşikleri (8 saatlik oran). ~0.01% nötr; |0.05%| üstü aşırı.
FUNDING_HOT = 0.0005   # %0.05
FUNDING_EXTREME = 0.001  # %0.10


def _perp(symbol: str) -> str:
    s = symbol.upper()
    if s.endswith("USDT"):
        return s
    if s.endswith(("USDC", "BUSD", "USD")):
        return s[: -len("USDC")] + "USDT" if s.endswith("USDC") else s
    return f"{s}USDT"


def funding_rate(symbol: str) -> dict:
    """Anlık funding + mark fiyat."""
    sym = _perp(symbol)
    try:
        d = get_json(f"{FBASE}/fapi/v1/premiumIndex?symbol={sym}", ttl=30)
        if isinstance(d, list):
            d = d[0] if d else {}
        rate = float(d.get("lastFundingRate", 0.0))
        return {"funding": rate, "mark": float(d.get("markPrice", 0.0) or 0.0),
                "ok": True}
    except Exception as e:  # noqa: BLE001
        log.warning("funding_rate %s hata: %s", symbol, e)
        return {"funding": 0.0, "mark": 0.0, "ok": False}


def open_interest_change(symbol: str, period: str = "5m",
                         limit: int = 12) -> dict:
    """Son N periyotta açık pozisyon (OI) yüzde değişimi."""
    sym = _perp(symbol)
    try:
        rows = get_json(
            f"{FBASE}/futures/data/openInterestHist"
            f"?symbol={sym}&period={period}&limit={min(limit, 30)}", ttl=30)
        if not rows or len(rows) < 2:
            return {"oi_change_pct": 0.0, "oi_now": 0.0, "ok": False}
        first = float(rows[0]["sumOpenInterest"])
        last = float(rows[-1]["sumOpenInterest"])
        chg = ((last - first) / first * 100.0) if first > 0 else 0.0
        return {"oi_change_pct": round(chg, 2), "oi_now": round(last, 2),
                "ok": True}
    except Exception as e:  # noqa: BLE001
        log.warning("open_interest_change %s hata: %s", symbol, e)
        return {"oi_change_pct": 0.0, "oi_now": 0.0, "ok": False}


def long_short_ratio(symbol: str, period: str = "5m") -> dict:
    """Global hesap long/short oranı (aşırı uçlar contrarian sinyal)."""
    sym = _perp(symbol)
    try:
        rows = get_json(
            f"{FBASE}/futures/data/globalLongShortAccountRatio"
            f"?symbol={sym}&period={period}&limit=1", ttl=30)
        if not rows:
            return {"ls_ratio": 1.0, "ok": False}
        r = rows[-1]
        return {"ls_ratio": round(float(r["longShortRatio"]), 3),
                "long_pct": round(float(r["longAccount"]) * 100, 1),
                "short_pct": round(float(r["shortAccount"]) * 100, 1),
                "ok": True}
    except Exception as e:  # noqa: BLE001
        log.warning("long_short_ratio %s hata: %s", symbol, e)
        return {"ls_ratio": 1.0, "ok": False}


def _squeeze_direction(funding: float, oi_change_pct: float,
                       ls_ratio: float) -> dict:
    """Funding + OI + L/S oranından likidasyon/squeeze yönü türet.

    +1: short-squeeze (yukarı baskı potansiyeli) ; -1: long-squeeze (aşağı) ; 0 nötr.
    """
    score = 0.0
    notes = []
    # Funding: pozitif=longlar öder (kalabalık long → long-squeeze riski = -)
    if funding >= FUNDING_EXTREME:
        score -= 0.5
        notes.append("aşırı + funding: kalabalık long (long-squeeze riski)")
    elif funding >= FUNDING_HOT:
        score -= 0.25
        notes.append("yüksek + funding")
    elif funding <= -FUNDING_EXTREME:
        score += 0.5
        notes.append("aşırı - funding: kalabalık short (short-squeeze potansiyeli)")
    elif funding <= -FUNDING_HOT:
        score += 0.25
        notes.append("düşük - funding")
    # L/S oranı: çok yüksek long → contrarian aşağı; çok düşük → yukarı
    if ls_ratio >= 2.0:
        score -= 0.25
        notes.append("L/S çok yüksek (aşırı long)")
    elif ls_ratio <= 0.6:
        score += 0.25
        notes.append("L/S çok düşük (aşırı short)")
    # OI ani düşüş = likidasyon kaskadı (mevcut yönü hızlandırır, belirsizlik)
    cascade = oi_change_pct <= -5.0
    if cascade:
        notes.append("OI ani düşüş: likidasyon kaskadı")
    score = max(-1.0, min(1.0, score))
    direction = ("short-squeeze (yukarı)" if score > 0.2 else
                 "long-squeeze (aşağı)" if score < -0.2 else "nötr")
    return {"score": round(score, 3), "direction": direction,
            "cascade": cascade, "notes": notes}


def summary(symbol: str) -> dict:
    """Birleşik türev/likidasyon özeti (anahtarsız, fail-safe)."""
    fr = funding_rate(symbol)
    oi = open_interest_change(symbol)
    ls = long_short_ratio(symbol)
    sq = _squeeze_direction(fr["funding"], oi["oi_change_pct"], ls["ls_ratio"])
    return {
        "symbol": symbol.upper(),
        "funding": fr["funding"],
        "funding_pct": round(fr["funding"] * 100, 4),
        "oi_change_pct": oi["oi_change_pct"],
        "ls_ratio": ls["ls_ratio"],
        "long_pct": ls.get("long_pct"),
        "short_pct": ls.get("short_pct"),
        "squeeze": sq,
        "ok": fr["ok"] or oi["ok"] or ls["ok"],
    }
