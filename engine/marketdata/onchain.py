"""On-chain borsa netflow — OPSİYONEL (Etherscan API anahtarı gerekir).

ETHERSCAN_API_KEY ayarlıysa, bilinen borsa cüzdanlarının ETH bakiye/transfer
yönünü kabaca okuyup "borsaya giriş (satış baskısı)" vs "borsadan çıkış
(biriktirme)" sinyali üretir. Anahtar yoksa sessizce nötr döner — çekirdek
akış anahtarsız çalışmaya devam eder (fail-safe).

Not: Tam doğru netflow için ücretli/indeksli servis gerekir; bu modül hafif bir
yaklaşım sunar ve mevcutsa sinyali zenginleştirir, yoksa hiçbir şeyi bozmaz.
"""
from __future__ import annotations

import logging
import os

from engine.marketdata.http import get_json

log = logging.getLogger("marketdata.onchain")

ETHERSCAN = "https://api.etherscan.io/api"

# Bilinen büyük borsa sıcak cüzdanları (ETH). Genişletilebilir.
EXCHANGE_WALLETS = {
    "Binance 7": "0xbe0eb53f46cd790cd13851d5eff43d12404d33e8",
    "Binance 8": "0xf977814e90da44bfa03b6295a0616a897441acec",
    "Kraken 4": "0xfa52274dd61e1643d2205169732f29114bc240b3",
    "Coinbase 1": "0x71660c4005ba85c37ccec55d0c4493e66fe775d3",
}


def enabled() -> bool:
    return bool(os.environ.get("ETHERSCAN_API_KEY"))


def _balance(addr: str, key: str) -> float | None:
    try:
        d = get_json(
            f"{ETHERSCAN}?module=account&action=balance&address={addr}"
            f"&tag=latest&apikey={key}", ttl=120)
        if str(d.get("status")) == "1":
            return int(d["result"]) / 1e18
    except Exception as e:  # noqa: BLE001
        log.warning("etherscan balance hata %s: %s", addr, e)
    return None


def exchange_eth_balances() -> dict:
    """Bilinen borsa cüzdanlarının toplam ETH bakiyesi (anahtar varsa)."""
    key = os.environ.get("ETHERSCAN_API_KEY")
    if not key:
        return {"enabled": False, "total_eth": 0.0, "wallets": {}}
    wallets: dict[str, float] = {}
    for name, addr in EXCHANGE_WALLETS.items():
        bal = _balance(addr, key)
        if bal is not None:
            wallets[name] = round(bal, 2)
    return {"enabled": True, "total_eth": round(sum(wallets.values()), 2),
            "wallets": wallets}


def netflow_signal(symbol: str = "ETH") -> dict:
    """On-chain borsa rezerv sinyali. Anahtar yoksa nötr/devre dışı.

    Yüksek borsa rezervi → potansiyel satış baskısı (bearish); düşen rezerv →
    biriktirme (bullish). Tek atışlık bakiye anlık seviyedir; trend için
    çağrı geçmişi tutmak gerekir (kapsam dışı, ileride DB ile).
    """
    if symbol.upper() not in ("ETH", "WETH"):
        return {"enabled": False, "score": 0.0, "note": "yalnızca ETH desteklenir"}
    if not enabled():
        return {"enabled": False, "score": 0.0,
                "note": "ETHERSCAN_API_KEY yok (on-chain devre dışı)"}
    bals = exchange_eth_balances()
    return {"enabled": True, "score": 0.0,  # trend için geçmiş gerekir
            "total_exchange_eth": bals["total_eth"],
            "wallets": bals["wallets"],
            "note": "anlık borsa rezervi (trend için geçmiş gerekir)"}
