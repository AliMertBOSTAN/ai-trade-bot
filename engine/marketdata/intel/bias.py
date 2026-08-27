"""Piyasa yapısı bias'ı — panel verilerinin TEK bir -1..+1 skoruna indirgenmesi.

Bu modül sinyal motorunun ve risk kapılarının okuduğu yerdir. İki katı kural:

  1. ASLA ağ çağrısı yapmaz. Yalnızca `intel.cache` içindeki, arka planda
     tazelenen snapshot'ları okur. Cache boşsa (test ortamı, ilk açılış, ağ
     yok) sonuç NÖTR'dür ve mevcut davranış hiç değişmez.
  2. Her bileşen bağımsızdır; biri eksikse ağırlıklar kalanlar üzerinden
     yeniden normalize edilir.

Yorum yönü: skor > 0 → yapısal olarak ALIM lehine; skor < 0 → SATIŞ lehine.
Korku/açgözlülük gibi contrarian göstergeler ters çevrilerek katılır.
"""
from __future__ import annotations

import logging

from engine.marketdata.intel.cache import peek

log = logging.getLogger("intel.bias")

# Bileşen ağırlıkları (toplamı 1 olmak zorunda değil; normalize edilir).
WEIGHTS = {
    "risk_on_off": 0.18,
    "crypto_fng": 0.12,
    "premium": 0.14,
    "etf": 0.14,
    "stablecoins": 0.12,
    "hyperliquid": 0.12,
    "smart_money": 0.10,
    "reserves": 0.05,
    "mvrv": 0.03,
}

# Cache anahtarı bayatsa bileşeni yok say (saniye).
MAX_AGE_S = 3600.0


def _fresh(key: str) -> dict | None:
    hit = peek(key)
    if hit is None:
        return None
    value, age = hit
    if age > MAX_AGE_S or not isinstance(value, dict):
        return None
    return value


def _clamp(x: float) -> float:
    return max(-1.0, min(1.0, x))


def _components() -> list[dict]:
    out: list[dict] = []

    def add(name: str, score: float, detail: str) -> None:
        out.append({"name": name, "score": round(_clamp(score), 3),
                    "weight": WEIGHTS.get(name, 0.0), "detail": detail})

    r = _fresh("macro:riskonoff")
    if r and r.get("ok"):
        add("risk_on_off", (r["score"] - 50) / 50.0,
            f"{r.get('mode')} ({r['score']}/100)")

    f = _fresh("macro:fng")
    c = (f or {}).get("crypto") or {}
    if c.get("ok"):
        v = c["value"]
        # Contrarian: aşırı korku alım fırsatı, aşırı açgözlülük risk.
        if v <= 25:
            s = 0.8
        elif v <= 40:
            s = 0.35
        elif v >= 80:
            s = -0.8
        elif v >= 65:
            s = -0.35
        else:
            s = 0.0
        add("crypto_fng", s, f"Kripto F&G {v} ({c.get('label', '')})")

    p = _fresh("premium")
    if p and p.get("ok"):
        add("premium", float(p.get("bias") or 0.0),
            f"Coinbase primi: {p.get('note')}")

    e = _fresh("etf:bitcoin")
    if e and e.get("ok"):
        add("etf", float(e.get("bias") or 0.0),
            f"ETF akışı ({e.get('source')}): {e.get('note', '')}".strip())

    s = _fresh("llama:stables")
    if s and s.get("ok"):
        add("stablecoins", float(s.get("bias") or 0.0),
            f"Stablecoin arzı 30g: {s.get('change_30d_pct')}% — {s.get('note')}")

    h = _fresh("hl:sentiment")
    if h and h.get("ok"):
        add("hyperliquid", float(h.get("score") or 0.0),
            f"HL: {h.get('label')} (funding {h.get('weighted_funding_pct')}%)")

    m = _fresh("flows:smartmoney")
    if m and m.get("ok"):
        add("smart_money", float(m.get("score") or 0.0),
            f"Smart money ({m.get('source')}) skoru {m.get('score')}")

    rv = _fresh("flows:reserves:BTC")
    if rv and rv.get("ok"):
        add("reserves", float(rv.get("bias") or 0.0),
            f"Borsa rezervi: {rv.get('note', '')}".strip())

    u = _fresh("utxo:realized")
    if u and u.get("ok"):
        add("mvrv", float(u.get("bias") or 0.0),
            f"MVRV {u.get('mvrv')} — {u.get('zone')}")

    return out


def market_bias() -> dict:
    """Genel piyasa yapısı bias'ı. Veri yoksa {"ok": False, "score": 0.0}."""
    comps = _components()
    if not comps:
        return {"ok": False, "score": 0.0, "label": "veri yok",
                "components": [], "available": 0}
    wsum = sum(c["weight"] for c in comps) or 1.0
    score = sum(c["score"] * c["weight"] for c in comps) / wsum
    score = round(_clamp(score), 3)
    label = ("güçlü yapısal destek" if score >= 0.4 else
             "yapısal destek" if score >= 0.15 else
             "yapısal baskı" if score <= -0.15 else "nötr")
    if score <= -0.4:
        label = "güçlü yapısal baskı"
    return {"ok": True, "score": score, "label": label,
            "components": comps, "available": len(comps),
            "weight_covered": round(wsum, 3)}


def symbol_bias(symbol: str) -> dict:
    """Sembole özel akış bias'ı (smart-money satırı + HL net pozisyon)."""
    sym = (symbol or "").upper().replace("USDT", "").replace("WETH", "ETH")
    parts: list[dict] = []

    m = _fresh("flows:smartmoney")
    if m and m.get("ok"):
        row = next((r for r in (m.get("rows") or []) if r.get("symbol") == sym), None)
        if row:
            parts.append({"name": "smart_money", "score": float(row.get("score") or 0.0),
                          "detail": f"{sym}: {row.get('label')}"})

    w = _fresh("hl:winners")
    if w and w.get("ok"):
        row = next((r for r in (w.get("rows") or []) if r.get("symbol") == sym), None)
        if row:
            long_pct = float(row.get("long_pct") or 50.0)
            parts.append({"name": "hl_winners",
                          "score": _clamp((long_pct - 50) / 50.0),
                          "detail": f"HL kazananları {sym} için %{long_pct:.0f} LONG"})

    if not parts:
        return {"ok": False, "score": 0.0, "components": []}
    score = round(_clamp(sum(p["score"] for p in parts) / len(parts)), 3)
    return {"ok": True, "score": score, "components": parts}


def combined(symbol: str | None = None) -> dict:
    """Genel + sembole özel bias birleşimi (sinyal motorunun okuduğu şey)."""
    g = market_bias()
    s = symbol_bias(symbol) if symbol else {"ok": False, "score": 0.0, "components": []}
    if not g["ok"] and not s["ok"]:
        return {"ok": False, "score": 0.0, "label": "veri yok",
                "components": [], "symbol_components": []}
    if g["ok"] and s["ok"]:
        score = round(_clamp(0.7 * g["score"] + 0.3 * s["score"]), 3)
    else:
        score = g["score"] if g["ok"] else s["score"]
    return {"ok": True, "score": score,
            "label": g.get("label", "—"),
            "market_score": g["score"], "symbol_score": s["score"],
            "components": g.get("components", []),
            "symbol_components": s.get("components", []),
            "available": g.get("available", 0)}
