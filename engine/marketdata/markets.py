"""Tüm piyasaları/enstrümanları tek çatıda toplayan kayıt + birleştirici.

Şu an: Kripto DEX (on-chain, orchestrator fiyatları) + Kripto CEX (Binance).
İLERİDE: BIST, ABD borsaları gibi piyasalar buraya `MARKETS` kaydına bir giriş
ve bir fetcher (örn. `bist_instruments()`) eklenerek devreye alınır
(asset_class="equity"). UI, MARKETS listesini filtre olarak otomatik gösterir;
status="coming_soon" olanlar "yakında" rozetiyle pasif görünür.

Bu modül /markets endpoint'inin veri kaynağıdır: kullanıcı tek ekrandan botun
gördüğü TÜM fiyatları arayıp inceleyebilir.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from engine.marketdata import binance
from engine.marketdata import hyperliquid
from engine.marketdata import solana as solana_md

log = logging.getLogger("marketdata.markets")

# Piyasa kaydı — UI bunu filtre çipi olarak gösterir.
#   status: "live" (veri akıyor) | "coming_soon" (planlandı, henüz veri yok)
MARKETS: list[dict] = [
    {"id": "dex", "label": "Kripto · DEX", "asset_class": "crypto", "status": "live"},
    {"id": "binance", "label": "Kripto · Binance (CEX)", "asset_class": "crypto",
     "status": "live"},
    {"id": "hyperliquid", "label": "Hyperliquid · Perp (kaldıraçlı)",
     "asset_class": "crypto-perp", "status": "live"},
    {"id": "solana", "label": "Solana · Meme / DEX",
     "asset_class": "crypto", "status": "live"},
    {"id": "bist", "label": "BIST · Borsa İstanbul", "asset_class": "equity",
     "status": "coming_soon"},
    {"id": "us", "label": "ABD Borsaları (NYSE/NASDAQ)", "asset_class": "equity",
     "status": "coming_soon"},
]

# CEX'te listelenecek başlıca semboller (genişletilebilir).
CEX_SYMBOLS = [
    "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "MATIC", "ARB", "OP",
    "LINK", "UNI", "AVAX", "DOT", "LTC", "ATOM", "NEAR", "APT", "FIL", "INJ",
    "TRX", "SUI", "PEPE", "TIA", "SEI",
]


def dex_instruments(quotes: list[dict]) -> list[dict]:
    """Orchestrator'ın hazır DEX fiyatlarını (PriceQuote.to_dict) enstrümana çevirir.

    Yeni ağ çağrısı yapmaz; bellekteki son fiyatları kullanır (hızlı).
    """
    out: list[dict] = []
    for q in quotes:
        out.append({
            "market": "dex",
            "symbol": q.get("base", "?"),
            "quote": q.get("quote", "USD"),
            "venue": q.get("dex", ""),
            "chain_id": q.get("chain_id"),
            "price": q.get("price", 0.0),
            "change_pct_24h": None,
            "liquidity_usd": q.get("liquidity_usd", 0.0),
            "volume_usd": None,
        })
    return out


def _cex_one(sym: str) -> dict | None:
    try:
        t = binance.ticker_24h(f"{sym}USDT")
        return {
            "market": "binance",
            "symbol": sym,
            "quote": "USDT",
            "venue": "Binance",
            "chain_id": None,
            "price": t["price"],
            "change_pct_24h": t["change_pct_24h"],
            "liquidity_usd": None,
            "volume_usd": t["volume_quote_24h"],
        }
    except Exception as e:  # pragma: no cover - ağ hatası
        log.debug("cex %s alınamadı: %s", sym, e)
        return None


def cex_instruments(symbols: list[str] | None = None) -> list[dict]:
    """Binance 24s ticker'larından enstrüman listesi (paralel, TTL cache'li)."""
    syms = symbols or CEX_SYMBOLS
    out: list[dict] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for r in pool.map(_cex_one, syms):
            if r:
                out.append(r)
    return out


def hyperliquid_instruments() -> list[dict]:
    """Hyperliquid perp'lerini (kaldıraçlı) enstrümana çevirir."""
    out: list[dict] = []
    for p in hyperliquid.perp_contexts():
        out.append({
            "market": "hyperliquid",
            "symbol": p["symbol"],
            "quote": "USD",
            "venue": "Hyperliquid",
            "chain_id": None,
            "price": p["price"],
            "change_pct_24h": p["change_pct_24h"],
            "liquidity_usd": None,
            "volume_usd": p["volume_usd"],
            # perp'e özgü alanlar
            "kind": "perp",
            "max_leverage": p["max_leverage"],
            "funding_pct": p["funding_pct"],
            "open_interest_usd": p["open_interest_usd"],
        })
    return out


def all_markets(dex_quotes: list[dict]) -> dict:
    """/markets yanıtı: piyasa kaydı + tüm enstrümanlar.

    DEX bellekten (hızlı); CEX (Binance) ve Hyperliquid (perp) canlı çekilir.
    Her kaynak fail-safe: biri düşerse diğerleriyle devam eder.
    """
    instruments = dex_instruments(dex_quotes)
    try:
        instruments += cex_instruments()
    except Exception as e:  # pragma: no cover
        log.warning("CEX enstrümanları alınamadı: %s", e)
    try:
        instruments += hyperliquid_instruments()
    except Exception as e:  # pragma: no cover
        log.warning("Hyperliquid enstrümanları alınamadı: %s", e)
    try:
        instruments += solana_md.solana_instruments()
    except Exception as e:  # pragma: no cover
        log.warning("Solana enstrümanları alınamadı: %s", e)
    return {"markets": MARKETS, "instruments": instruments}
