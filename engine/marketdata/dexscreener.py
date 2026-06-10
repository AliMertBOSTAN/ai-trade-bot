"""DEX açık verisi — DexScreener public API (key gerekmez).

Uniswap v2/v3, PancakeSwap, QuickSwap dahil yüzlerce DEX'in havuz
verisini (fiyat, likidite, 24s hacim, işlem sayısı) döner. RPC'siz
çalıştığı için zincir okuma altyapısından (engine.dex) bağımsız bir
ikinci/yedek fiyat kaynağıdır.

Bilinen tokenlar için adres-tabanlı /tokens endpoint'i kullanılır
(isim aramasından çok daha güvenilir); bilinmeyenler için /search'e düşer.
"""
from __future__ import annotations

import logging

from engine.marketdata.http import get_json

log = logging.getLogger("marketdata.dexscreener")

BASE = "https://api.dexscreener.com/latest/dex"

# Bizim chain_id'ler -> DexScreener zincir adları
CHAIN_NAMES = {
    1: "ethereum", 42161: "arbitrum", 8453: "base",
    10: "optimism", 56: "bsc", 137: "polygon",
}
SUPPORTED_CHAINS = set(CHAIN_NAMES.values())

# Kanonik token adresleri (adres-tabanlı sorgu için)
TOKEN_ADDRESSES = {
    "WETH":  "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",  # ethereum
    "ETH":   "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    "WBTC":  "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",  # ethereum
    "BTC":   "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
    "LINK":  "0x514910771AF9Ca656af840dff83E8264EcF986CA",  # ethereum
    "UNI":   "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",  # ethereum
    "ARB":   "0x912CE59144191C1204E64559FE8253a0e49E6548",  # arbitrum
    "OP":    "0x4200000000000000000000000000000000000042",  # optimism
    "WBNB":  "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",  # bsc
    "BNB":   "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
    "WMATIC": "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",  # polygon
    "MATIC": "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
}

_STABLES = {"USDC", "USDT", "DAI", "FDUSD", "USDC.E", "USDBC"}


def _pair(p: dict) -> dict:
    """DexScreener pair objesini sadeleştir."""
    base_t = p.get("baseToken") or {}
    quote_t = p.get("quoteToken") or {}
    return {
        "source": "dexscreener",
        "chain": p.get("chainId"),
        "dex": p.get("dexId"),
        "base_symbol": base_t.get("symbol", ""),
        "base_address": (base_t.get("address") or "").lower(),
        "quote_symbol": quote_t.get("symbol", ""),
        "pair": f"{base_t.get('symbol', '')}/{quote_t.get('symbol', '')}",
        "pair_address": p.get("pairAddress"),
        "price_usd": float(p.get("priceUsd") or 0),
        "price_native": float(p.get("priceNative") or 0),
        "liquidity_usd": float((p.get("liquidity") or {}).get("usd") or 0),
        "volume_24h_usd": float((p.get("volume") or {}).get("h24") or 0),
        "txns_24h": sum((p.get("txns") or {}).get("h24", {}).values() or [0]),
        "change_pct_24h": float((p.get("priceChange") or {}).get("h24") or 0),
        "url": p.get("url"),
    }


def _filter_sort(pairs: list[dict], min_liquidity_usd: float) -> list[dict]:
    out = [p for p in pairs
           if p["liquidity_usd"] >= min_liquidity_usd
           and p["chain"] in SUPPORTED_CHAINS
           and p["price_usd"] > 0]
    out.sort(key=lambda p: p["liquidity_usd"], reverse=True)
    return out


def token_pairs(address: str, min_liquidity_usd: float = 50_000) -> list[dict]:
    """Token adresine göre tüm havuzlar (desteklenen zincirlerde)."""
    d = get_json(f"{BASE}/tokens/{address}", ttl=15)
    pairs = [_pair(p) for p in (d.get("pairs") or [])]
    # token base tarafında olmalı (fiyat yönü doğru olsun)
    pairs = [p for p in pairs if p["base_address"] == address.lower()]
    return _filter_sort(pairs, min_liquidity_usd)


def search_pairs(query: str, min_liquidity_usd: float = 50_000,
                 limit: int = 10) -> list[dict]:
    """Serbest metin havuz araması (bilinmeyen tokenlar için yedek yol)."""
    d = get_json(f"{BASE}/search?q={query.replace(' ', '%20')}", ttl=15)
    pairs = [_pair(p) for p in (d.get("pairs") or [])]
    return _filter_sort(pairs, min_liquidity_usd)[:limit]


def best_dex_price(base: str, quote: str = "USDC",
                   prefer_dex: str | None = "uniswap") -> dict | None:
    """En likit havuzun fiyatı (stabil kotasyonlu, tam sembol eşleşmeli).

    Bilinen tokenlarda adres-tabanlı sorgu; aksi halde arama. prefer_dex
    verilirse önce o DEX denenir (varsayılan: uniswap).
    """
    addr = TOKEN_ADDRESSES.get(base.upper())
    if addr:
        pairs = token_pairs(addr)
    else:
        pairs = [p for p in search_pairs(f"{base} {quote}", limit=25)
                 if p["base_symbol"].upper() == base.upper()]

    # USD karşılaştırması için stabil kotasyonlu havuzları tercih et
    stable = [p for p in pairs if p["quote_symbol"].upper() in _STABLES]
    pool = stable or pairs
    if not pool:
        return None
    if prefer_dex:
        preferred = [p for p in pool if prefer_dex in (p["dex"] or "")]
        if preferred:
            return preferred[0]
    return pool[0]
