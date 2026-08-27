"""Nansen adaptörü (opsiyonel, NANSEN_API_KEY) — smart-money zincir akışları.

Anahtar yoksa `enabled()` False; çağıran taraf orderflow vekiline düşer.
Nansen API sürümleri değişebildiği için yanıt şeması savunmacı okunur ve
herhangi bir hata `ok=False` ile sessizce raporlanır (panel yine dolar).
"""
from __future__ import annotations

import logging

from engine.marketdata.http import get_json
from engine.marketdata.intel import keys

log = logging.getLogger("intel.nansen")

BASE = "https://api.nansen.ai/api/beta"


def enabled() -> bool:
    return bool(keys.nansen())


def smart_money_flows(chain: str = "ethereum", hours: int = 24) -> dict:
    if not enabled():
        return keys.disabled("nansen", "NANSEN_API_KEY")
    key = keys.nansen()
    try:
        d = get_json(f"{BASE}/smart-money/netflow?chain={chain}&timeframe={hours}h",
                     ttl=600, headers={"apiKey": key, "Accept": "application/json"})
    except Exception as e:  # noqa: BLE001
        log.warning("nansen akışı alınamadı: %s", e)
        return {"enabled": True, "ok": False, "reason": str(e)[:140], "rows": []}
    items = d if isinstance(d, list) else (d.get("data") or d.get("result") or [])
    rows = []
    for r in items if isinstance(items, list) else []:
        sym = (r.get("symbol") or r.get("tokenSymbol") or "").upper()
        net = r.get("netflowUSD", r.get("netflow_usd", r.get("netFlow")))
        if not sym or net is None:
            continue
        try:
            net = float(net)
        except (TypeError, ValueError):
            continue
        rows.append({"symbol": sym, "net_usd": round(net, 0),
                     "score": max(-1.0, min(1.0, net / 5_000_000)),
                     "label": "birikim" if net > 0 else "dağıtım"})
    rows.sort(key=lambda r: -abs(r["net_usd"]))
    total = sum(r["net_usd"] for r in rows)
    gross = sum(abs(r["net_usd"]) for r in rows) or 1.0
    return {"enabled": True, "ok": bool(rows), "source": "nansen", "chain": chain,
            "rows": rows[:15], "score": round(total / gross, 3),
            "accumulation": [r for r in rows if r["net_usd"] > 0][:5],
            "distribution": [r for r in rows if r["net_usd"] < 0][:5]}
