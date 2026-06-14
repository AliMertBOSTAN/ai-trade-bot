"""Canlı gas (ağ ücreti) maliyet tahmincisi — USD.

Her işlem ve her arbitraj fırsatı için ağ gas ücretini USD cinsinden tahmin
eder ve böylece gas HER ZAMAN hesaba katılır (sessizce sıfır sayılmaz).

Öncelik sırası:
  1) Canlı: w3.eth.gas_price (TTL cache) × gas_units × native_token_usd
     - native_token_usd, çağırandan (oracle fiyatları) gelebilir; yoksa fallback.
  2) Canlı veri yoksa (paper mod / RPC tanımsız): zincir başına statik USD,
     gas_units oranına göre ölçeklenir.

Tipik gas birimi: V2 swap ~120-150k, V3 swap ~150-180k. Arbitraj = al + sat
(iki bacak). Konservatif sabitler kullanılır.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("dex.gas")

# Tahmini gas birimleri (gas units)
GAS_UNITS_SWAP = 150_000      # tek swap (V2/V3 ortalaması, üst sınıra yakın)
GAS_UNITS_ARB_LEG = 150_000   # arbitrajda her bacak (al / sat)

# Canlı gas fiyatı alınamazsa zincir başına varsayılan (gwei)
_DEFAULT_GWEI: dict[int, float] = {
    1: 20.0, 42161: 0.10, 8453: 0.05, 10: 0.05, 56: 3.0, 137: 50.0,
}
# Native token (ETH/BNB/MATIC) USD — canlı fiyat verilmezse kaba fallback
_NATIVE_USD_FALLBACK: dict[int, float] = {
    1: 3000.0, 42161: 3000.0, 8453: 3000.0, 10: 3000.0, 56: 600.0, 137: 0.7,
}
# En son çare: zincir başına tek-bacak gas maliyeti (USD) — ne canlı ne native
# fiyat varsa kullanılır (paper/offline). GAS_UNITS_SWAP referans alınır.
_STATIC_USD: dict[int, float] = {
    1: 18.0, 42161: 0.25, 8453: 0.10, 10: 0.15, 56: 0.30, 137: 0.02,
}

# Bir işlemin gas'i, notional'ın bu oranını aşarsa işlem ekonomik değildir
MAX_GAS_FRACTION = 0.5

_GWEI_TTL = 15.0  # saniye
_gwei_cache: dict[int, tuple[float, float]] = {}


def _live_gwei(chain_id: int) -> float | None:
    """Canlı gas fiyatı (gwei); TTL cache'li. RPC yok/hata -> None."""
    now = time.time()
    hit = _gwei_cache.get(chain_id)
    if hit and now - hit[0] < _GWEI_TTL:
        return hit[1]
    try:
        from engine.web3x.provider import get_web3  # lazy: web3 sadece canlıda
        w3 = get_web3(chain_id)
        if w3 is None:
            return None
        gwei = w3.eth.gas_price / 1e9
        _gwei_cache[chain_id] = (now, gwei)
        return gwei
    except Exception as e:  # pragma: no cover - ağ hatası
        log.debug("gas fiyatı alınamadı (chain %s): %s", chain_id, e)
        return None


def gas_price_gwei(chain_id: int) -> float:
    """Canlı gas fiyatı (gwei); yoksa zincir varsayılanı."""
    live = _live_gwei(chain_id)
    return live if live is not None else _DEFAULT_GWEI.get(chain_id, 20.0)


def gas_cost_usd(chain_id: int, gas_units: int = GAS_UNITS_SWAP,
                 native_usd: float | None = None) -> float:
    """Bir işlemin tahmini gas maliyeti (USD). Daima > 0 döner."""
    gwei = _live_gwei(chain_id)
    nusd = native_usd if (native_usd and native_usd > 0) else _NATIVE_USD_FALLBACK.get(chain_id)
    if gwei is not None and nusd:
        cost_native = (gwei * 1e9) * gas_units / 1e18  # gwei->wei->native birim
        return cost_native * nusd
    # canlı yoksa: statik USD'yi gas_units ile ölçekle
    base = _STATIC_USD.get(chain_id, 1.0)
    return base * (gas_units / GAS_UNITS_SWAP)


def native_usd_from_quotes(quotes, chain_id: int, wrapped_symbol: str) -> float | None:
    """Oracle fiyat listesinden native token'ın USD fiyatını çıkar (varsa).

    quotes: PriceQuote listesi; wrapped_symbol örn. 'WETH'/'WBNB'/'WMATIC'.
    """
    for q in quotes:
        if q.chain_id == chain_id and q.base == wrapped_symbol and q.price > 0:
            return q.price
    return None
