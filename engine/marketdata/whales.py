"""Balina (whale) hareketleri takibi — anahtarsız, Binance public veriyle.

İki bağımsız sinyal birleştirilir:
  1) İŞLEM BANDI (aggTrades): belirli USD eşiğinin üstündeki BÜYÜK işlemler →
     balina ALIM vs SATIM baskısı (-1..+1). Agresif tarafa göre sınıflanır.
  2) EMİR DEFTERİ DUVARLARI (depth): en büyük bid/ask kümeleri → balina
     destek/direnç seviyeleri.

Not: on-chain transfer takibi (Whale Alert / Etherscan netflow) gelecekte
eklenebilir; API anahtarı gerektirdiği için şimdilik kapsam dışı. Bu modül
tamamen anahtarsız çalışır ve hata durumunda boş/nötr döner (fail-safe).
"""
from __future__ import annotations

import logging

from engine.marketdata.http import get_json

log = logging.getLogger("marketdata.whales")

BASE = "https://api.binance.com/api/v3"

# Varsayılan "balina" eşiği (USD). Sembol/fiyat bağımsız kaba bir alt sınır.
DEFAULT_MIN_USD = 25_000.0


def _to_spot(symbol: str) -> str:
    s = symbol.upper()
    return s if s.endswith(("USDT", "USDC", "BUSD", "USD")) else f"{s}USDT"


def large_trades(symbol: str, min_usd: float = DEFAULT_MIN_USD,
                 limit: int = 1000) -> list[dict]:
    """Son işlemlerden USD eşiğini aşan BÜYÜK olanları döndürür.

    aggTrades.m: 'alıcı maker mı?'. True ise agresif taraf SATICI (market sell),
    False ise agresif taraf ALICI (market buy).
    """
    spot = _to_spot(symbol)
    raw = get_json(f"{BASE}/aggTrades?symbol={spot}&limit={min(limit, 1000)}", ttl=4)
    out: list[dict] = []
    for t in raw:
        price = float(t["p"])
        qty = float(t["q"])
        usd = price * qty
        if usd >= min_usd:
            out.append({
                "price": price,
                "qty": qty,
                "usd": round(usd, 2),
                "side": "sell" if t.get("m") else "buy",
                "time": int(t["T"]),
            })
    return out


def _pressure_from_trades(trades: list[dict]) -> dict:
    """Büyük işlem listesinden balina baskısı (saf, test edilebilir)."""
    buy = sum(t["usd"] for t in trades if t["side"] == "buy")
    sell = sum(t["usd"] for t in trades if t["side"] == "sell")
    tot = buy + sell
    score = ((buy - sell) / tot) if tot > 0 else 0.0
    return {
        "score": round(score, 3),                 # -1 (satış) .. +1 (alım)
        "buy_usd": round(buy, 2),
        "sell_usd": round(sell, 2),
        "buy_count": sum(1 for t in trades if t["side"] == "buy"),
        "sell_count": sum(1 for t in trades if t["side"] == "sell"),
        "big_count": len(trades),
    }


def whale_pressure(symbol: str, min_usd: float = DEFAULT_MIN_USD) -> dict:
    """Balina alım/satım baskısı (-1..+1) + sayımlar."""
    try:
        trades = large_trades(symbol, min_usd)
    except Exception as e:  # noqa: BLE001
        log.warning("whale_pressure %s hata: %s", symbol, e)
        trades = []
    res = _pressure_from_trades(trades)
    res["min_usd"] = min_usd
    return res


def order_book_walls(symbol: str, limit: int = 500, top: int = 5,
                     min_usd: float = DEFAULT_MIN_USD) -> dict:
    """Emir defterindeki en büyük bid/ask duvarlarını döndürür (destek/direnç)."""
    spot = _to_spot(symbol)
    try:
        d = get_json(f"{BASE}/depth?symbol={spot}&limit={limit}", ttl=4)
    except Exception as e:  # noqa: BLE001
        log.warning("order_book_walls %s hata: %s", symbol, e)
        return {"bids": [], "asks": []}

    def walls(levels: list) -> list[dict]:
        rows = []
        for p, q in levels:
            price = float(p)
            qty = float(q)
            usd = price * qty
            if usd >= min_usd:
                rows.append({"price": price, "qty": round(qty, 4), "usd": round(usd, 2)})
        rows.sort(key=lambda x: x["usd"], reverse=True)
        return rows[:top]

    return {"bids": walls(d.get("bids", [])), "asks": walls(d.get("asks", []))}


def summary(symbol: str, min_usd: float = DEFAULT_MIN_USD) -> dict:
    """Birleşik balina özeti: baskı + etiket + duvarlar + son büyük işlemler."""
    pressure = whale_pressure(symbol, min_usd)
    walls = order_book_walls(symbol, min_usd=min_usd)
    try:
        recent = sorted(large_trades(symbol, min_usd), key=lambda t: t["time"],
                        reverse=True)[:8]
    except Exception:
        recent = []

    s = pressure["score"]
    label = ("balina alımı" if s > 0.15 else
             "balina satışı" if s < -0.15 else "dengeli")
    return {
        "symbol": symbol.upper(),
        "label": label,
        "pressure": pressure,
        "walls": walls,
        "recent": recent,
    }
