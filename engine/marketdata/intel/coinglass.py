"""CoinGlass v4 adaptörü — ETF akışı, borsa rezervi, likidasyon, UTXO bantları.

Anahtar yoksa her fonksiyon `{"enabled": False, ...}` döner; çağıran taraf
ücretsiz yedeğe düşer veya paneli "veri yok" gösterir. Ücretli planlarda bazı
uçlar kapalı olabilir — HTTP hatası da aynı şekilde fail-safe yakalanır.

Doküman: https://docs.coinglass.com  (başlık: CG-API-KEY)
"""
from __future__ import annotations

import logging

from engine.marketdata.http import get_json
from engine.marketdata.intel import keys

log = logging.getLogger("intel.coinglass")

BASE = "https://open-api-v4.coinglass.com/api"


def enabled() -> bool:
    return bool(keys.coinglass())


def _get(path: str, ttl: float = 300.0):
    key = keys.coinglass()
    if not key:
        raise RuntimeError("COINGLASS_API_KEY yok")
    d = get_json(f"{BASE}{path}", ttl=ttl,
                 headers={"CG-API-KEY": key, "Accept": "application/json"})
    if isinstance(d, dict):
        code = str(d.get("code", "0"))
        if code not in ("0", "200", "success"):
            raise RuntimeError(f"coinglass hata {code}: {str(d.get('msg'))[:80]}")
        return d.get("data")
    return d


def _safe(path: str, ttl: float, label: str):
    """Anahtar/HTTP hatasını yakalayıp (veri, hata) döner."""
    if not enabled():
        return None, "anahtar yok"
    try:
        return _get(path, ttl), None
    except Exception as e:  # noqa: BLE001
        log.warning("coinglass %s alınamadı: %s", label, e)
        return None, str(e)[:140]


def etf_flow_history(asset: str = "bitcoin") -> dict:
    data, err = _safe(f"/etf/{asset}/flow-history", 900, "etf-flow")
    if data is None:
        return {"enabled": enabled(), "ok": False, "reason": err, "rows": []}
    rows = []
    for r in data if isinstance(data, list) else []:
        ts = r.get("timestamp") or r.get("date")
        flow = r.get("flow_usd", r.get("changeUsd", r.get("flow")))
        if ts is None or flow is None:
            continue
        rows.append({"t": int(ts), "flow_usd": float(flow),
                     "price": float(r.get("price_usd") or r.get("price") or 0) or None})
    return {"enabled": True, "ok": bool(rows), "asset": asset, "rows": rows[-90:]}


def exchange_balance(symbol: str = "BTC") -> dict:
    data, err = _safe(f"/exchange/balance/list?symbol={symbol}", 900, "exchange-balance")
    if data is None:
        return {"enabled": enabled(), "ok": False, "reason": err, "rows": []}
    rows = []
    for r in data if isinstance(data, list) else []:
        rows.append({
            "exchange": r.get("exchange_name") or r.get("exchangeName") or "?",
            "balance": float(r.get("total_balance") or r.get("totalBalance") or 0),
            "change_1d": float(r.get("balance_change_1d") or r.get("balanceChange1d") or 0),
            "change_7d": float(r.get("balance_change_7d") or r.get("balanceChange7d") or 0),
        })
    rows.sort(key=lambda x: -x["balance"])
    return {"enabled": True, "ok": bool(rows), "symbol": symbol, "rows": rows[:15]}


def liquidation_history(symbol: str = "BTC", interval: str = "1h") -> dict:
    data, err = _safe(
        f"/futures/liquidation/aggregated-history?symbol={symbol}&interval={interval}",
        300, "liquidation")
    if data is None:
        return {"enabled": enabled(), "ok": False, "reason": err, "rows": []}
    rows = []
    for r in data if isinstance(data, list) else []:
        rows.append({"t": int(r.get("time") or r.get("timestamp") or 0),
                     "long_usd": float(r.get("aggregated_long_liquidation_usd")
                                       or r.get("longLiquidationUsd") or 0),
                     "short_usd": float(r.get("aggregated_short_liquidation_usd")
                                        or r.get("shortLiquidationUsd") or 0)})
    return {"enabled": True, "ok": bool(rows), "symbol": symbol, "rows": rows[-72:]}


def bitcoin_realized_bands() -> dict:
    """UTXO yaş bantlarına göre gerçekleşmiş fiyat (varsa)."""
    data, err = _safe("/index/bitcoin-short-term-holder-realized-price", 3600, "utxo-rp")
    if data is None:
        return {"enabled": enabled(), "ok": False, "reason": err, "rows": []}
    return {"enabled": True, "ok": True, "raw": data}
