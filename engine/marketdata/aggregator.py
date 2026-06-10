"""CEX/DEX veri birleştirici.

Aynı varlık için Binance (CEX) ve Uniswap/diğer DEX'lerden (DexScreener)
fiyat çekip karşılaştırır; spread'i, hacim/likidite bağlamını ve emir
defteri baskısını tek bir anlık görüntüde toplar. LLM analistinin ve
/marketdata endpoint'inin ana veri kaynağıdır.
"""
from __future__ import annotations

import logging

from engine.marketdata import binance, dexscreener
from engine.models import now_ms

log = logging.getLogger("marketdata.aggregator")

# UI sembolü -> (Binance sembolü, DEX base, DEX quote)
SYMBOL_MAP = {
    "ETH":   ("ETHUSDT", "WETH", "USDC"),
    "WETH":  ("ETHUSDT", "WETH", "USDC"),
    "BTC":   ("BTCUSDT", "WBTC", "USDC"),
    "WBTC":  ("BTCUSDT", "WBTC", "USDC"),
    "BNB":   ("BNBUSDT", "WBNB", "USDT"),
    "MATIC": ("MATICUSDT", "WMATIC", "USDC"),
    "ARB":   ("ARBUSDT", "ARB", "USDC"),
    "OP":    ("OPUSDT", "OP", "USDC"),
    "LINK":  ("LINKUSDT", "LINK", "USDC"),
    "UNI":   ("UNIUSDT", "UNI", "USDC"),
}


def snapshot(symbol: str) -> dict:
    """Tek varlık için CEX+DEX karşılaştırmalı anlık görüntü.

    Kaynaklardan biri düşerse diğeriyle devam eder (fail-safe);
    ikisi de yoksa 'error' alanı dolu döner.
    """
    sym = symbol.upper()
    b_sym, d_base, d_quote = SYMBOL_MAP.get(sym, (f"{sym}USDT", sym, "USDC"))

    out: dict = {"symbol": sym, "ts": now_ms(),
                 "cex": None, "dex": None, "comparison": None, "errors": []}

    try:
        t = binance.ticker_24h(b_sym)
        t["order_book"] = binance.order_book(b_sym)
        out["cex"] = t
    except Exception as e:
        out["errors"].append(f"binance: {e}")

    try:
        out["dex"] = dexscreener.best_dex_price(d_base, d_quote)
    except Exception as e:
        out["errors"].append(f"dexscreener: {e}")

    cex, dex = out["cex"], out["dex"]
    if cex and dex and dex["price_usd"]:
        spread_bps = (dex["price_usd"] - cex["price"]) / cex["price"] * 10_000
        out["comparison"] = {
            "cex_price": cex["price"],
            "dex_price": dex["price_usd"],
            "dex_venue": f"{dex['dex']}@{dex['chain']}",
            # >0: DEX pahalı (CEX'te al-DEX'te sat yönü), <0: tersi
            "spread_bps": round(spread_bps, 2),
            "dex_liquidity_usd": dex["liquidity_usd"],
            "note": ("DEX premium" if spread_bps > 0 else "CEX premium")
                    if abs(spread_bps) > 5 else "fiyatlar uyumlu",
        }
    return out


def multi_snapshot(symbols: list[str]) -> list[dict]:
    return [snapshot(s) for s in symbols]
