"""BTC gerçekleşmiş fiyat (realized price) & MVRV — anahtarsız on-chain.

Kaynak: bitcoin-data.com açık uçları (ücretsiz, anahtarsız):
    /v1/realized-price        tüm piyasanın maliyet tabanı
    /v1/sth-realized-price    kısa vadeli sahiplerin maliyet tabanı
    /v1/mvrv                  piyasa değeri / gerçekleşmiş değer

NinjaTools'taki "UTXO RP" panelinin çekirdeği: spot fiyatın bu maliyet
tabanlarına göre konumu, piyasanın toplam kâr/zarar durumunu gösterir.
MVRV > 3.5 → tarihsel tepe bölgesi; < 1 → maliyet tabanının altı (dip bölgesi).
STH maliyet tabanı boğa piyasalarında dinamik destek, ayıda dirençtir.
"""
from __future__ import annotations

import logging

from engine.marketdata.http import get_json
from engine.marketdata.intel.cache import cached

log = logging.getLogger("intel.utxo")

BD = "https://bitcoin-data.com/v1/{metric}"


def _f(x, d: float | None = None) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def _series(metric: str, field: str) -> dict[str, float]:
    """{'YYYY-MM-DD': değer} — bitcoin-data.com serisi."""
    raw = get_json(BD.format(metric=metric), ttl=3600)
    out: dict[str, float] = {}
    for r in raw if isinstance(raw, list) else []:
        d = r.get("d")
        v = _f(r.get(field))
        if d and v is not None:
            out[d] = v
    return out


def realized_price() -> dict:
    """Gerçekleşmiş fiyat + STH maliyet tabanı + MVRV bölgesi."""
    def _build() -> dict:
        try:
            rp = _series("realized-price", "realizedPrice")
            mvrv = _series("mvrv", "mvrv")
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:140], "series": []}
        try:
            sth = _series("sth-realized-price", "sthRealizedPrice")
        except Exception:  # noqa: BLE001
            sth = {}
        if not rp or not mvrv:
            return {"ok": False, "error": "seri boş", "series": []}

        series = []
        for d in sorted(set(rp) & set(mvrv)):
            r, m = rp[d], mvrv[d]
            if r <= 0 or m <= 0:
                continue
            series.append({"d": d, "realized": round(r, 2), "mvrv": round(m, 3),
                           "price": round(r * m, 2),
                           "sth": round(sth[d], 2) if d in sth else None})
        if not series:
            return {"ok": False, "error": "eşleşen tarih yok", "series": []}

        last = series[-1]
        prem = (last["price"] - last["realized"]) / last["realized"] * 100
        m = last["mvrv"]
        if m >= 3.5:
            zone, bias = "aşırı değerli (tarihsel tepe bölgesi)", -1.0
        elif m >= 2.4:
            zone, bias = "yüksek — kâr realizasyonu riski", -0.5
        elif m >= 1.2:
            zone, bias = "normal bant", 0.0
        elif m >= 1.0:
            zone, bias = "maliyet tabanına yakın — birikim bölgesi", 0.5
        else:
            zone, bias = "maliyet tabanının altı (tarihsel dip bölgesi)", 1.0

        sth_note = None
        if last["sth"]:
            above = last["price"] >= last["sth"]
            sth_note = ("STH maliyet tabanının ÜSTÜNDE (destek)" if above
                        else "STH maliyet tabanının ALTINDA (direnç)")
        return {"ok": True, "date": last["d"], "price": last["price"],
                "realized_price": last["realized"], "sth_realized": last["sth"],
                "mvrv": last["mvrv"], "premium_pct": round(prem, 2),
                "zone": zone, "bias": bias, "sth_note": sth_note,
                "series": series[-365:]}
    return cached("utxo:realized", 3600, _build)
