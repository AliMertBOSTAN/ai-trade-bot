"""Binance açık (public) piyasa verisi — API key gerekmez.

Kullanılan endpoint'ler:
  /api/v3/ticker/24hr  -> 24s fiyat/hacim istatistikleri
  /api/v3/klines       -> OHLCV mumlar
  /api/v3/depth        -> emir defteri (bid/ask derinliği)
  /api/v3/trades       -> son gerçekleşen işlemler
"""
from __future__ import annotations

import logging

from engine.marketdata.http import get_json

log = logging.getLogger("marketdata.binance")

BASE = "https://api.binance.com/api/v3"


def ticker_24h(symbol: str) -> dict:
    """24 saatlik özet: son fiyat, değişim %, hacim, high/low."""
    d = get_json(f"{BASE}/ticker/24hr?symbol={symbol.upper()}", ttl=5)
    return {
        "source": "binance",
        "symbol": d["symbol"],
        "price": float(d["lastPrice"]),
        "change_pct_24h": float(d["priceChangePercent"]),
        "high_24h": float(d["highPrice"]),
        "low_24h": float(d["lowPrice"]),
        "volume_base_24h": float(d["volume"]),
        "volume_quote_24h": float(d["quoteVolume"]),
        "trades_24h": int(d["count"]),
    }


def klines(symbol: str, interval: str = "1h", limit: int = 100) -> list[dict]:
    """OHLCV mumları (indikatör/karşılaştırma beslemesi)."""
    raw = get_json(
        f"{BASE}/klines?symbol={symbol.upper()}&interval={interval}"
        f"&limit={min(limit, 1000)}", ttl=30)
    return [{
        "t": int(k[0]),
        "open": float(k[1]), "high": float(k[2]),
        "low": float(k[3]), "close": float(k[4]),
        "volume": float(k[5]),
    } for k in raw]


def order_book(symbol: str, limit: int = 20) -> dict:
    """Emir defteri özeti: en iyi bid/ask, spread, derinlik dengesizliği."""
    d = get_json(f"{BASE}/depth?symbol={symbol.upper()}&limit={limit}", ttl=3)
    bids = [(float(p), float(q)) for p, q in d["bids"]]
    asks = [(float(p), float(q)) for p, q in d["asks"]]
    best_bid = bids[0][0] if bids else 0.0
    best_ask = asks[0][0] if asks else 0.0
    bid_vol = sum(q for _, q in bids)
    ask_vol = sum(q for _, q in asks)
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread_bps": ((best_ask - best_bid) / best_ask * 10_000) if best_ask else 0.0,
        "bid_volume": bid_vol,
        "ask_volume": ask_vol,
        # >0 alış baskısı, <0 satış baskısı
        "imbalance": ((bid_vol - ask_vol) / (bid_vol + ask_vol))
                     if (bid_vol + ask_vol) else 0.0,
    }


def recent_trades(symbol: str, limit: int = 50) -> list[dict]:
    """Son gerçekleşen işlemler (taker yönü dahil)."""
    raw = get_json(f"{BASE}/trades?symbol={symbol.upper()}&limit={min(limit, 1000)}",
                   ttl=3)
    return [{
        "t": int(t["time"]),
        "price": float(t["price"]),
        "qty": float(t["qty"]),
        "side": "SELL" if t["isBuyerMaker"] else "BUY",  # taker yönü
    } for t in raw]
