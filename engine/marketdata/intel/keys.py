"""Intel sağlayıcıları için opsiyonel API anahtarları — tek okuma noktası.

Anahtar YOKSA ilgili sağlayıcı sessizce devre dışı kalır ve panel
`{"enabled": false, "reason": "..."}` döner. Hiçbir anahtar zorunlu değildir;
anahtarsız kaynaklar (Binance, Hyperliquid, DefiLlama, CoinGecko, Stooq,
alternative.me, blockchain.info) her zaman çalışır.

.env örneği:
    COINGLASS_API_KEY=...      # ETF akışı, borsa rezervi, likidasyon, UTXO bantları
    CMC_API_KEY=...            # global metrikler + dominans + sektör
    NANSEN_API_KEY=...         # smart-money akışları
    HL_WATCH_WALLETS=0xabc...,0xdef...   # takip edilecek Hyperliquid cüzdanları
"""
from __future__ import annotations

import os


def coinglass() -> str:
    return (os.getenv("COINGLASS_API_KEY") or "").strip()


def cmc() -> str:
    return (os.getenv("CMC_API_KEY") or os.getenv("COINMARKETCAP_API_KEY") or "").strip()


def nansen() -> str:
    return (os.getenv("NANSEN_API_KEY") or "").strip()


def etherscan() -> str:
    return (os.getenv("ETHERSCAN_API_KEY") or "").strip()


def hl_wallets() -> list[str]:
    raw = os.getenv("HL_WATCH_WALLETS", "")
    return [w.strip() for w in raw.split(",") if w.strip().startswith("0x")]


def status() -> dict:
    """UI'ın "hangi panel neden kapalı" göstermesi için anahtar durumu."""
    return {
        "coinglass": bool(coinglass()),
        "coinmarketcap": bool(cmc()),
        "nansen": bool(nansen()),
        "etherscan": bool(etherscan()),
        "hl_wallets": len(hl_wallets()),
    }


def disabled(provider: str, env_name: str) -> dict:
    """Anahtarsız sağlayıcı için standart 'kapalı' yanıtı."""
    return {"enabled": False, "provider": provider,
            "reason": f"{env_name} tanımlı değil — .env'e ekleyince bu panel dolar"}
