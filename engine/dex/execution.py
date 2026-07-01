"""Yürütme kalitesi: en iyi yönlendirme, TWAP bölme, derinlik-tabanlı slippage.

Amaç: büyük emirlerin fiyat etkisini azaltmak ve toplam maliyeti (fiyat + ücret
+ gas) en aza indiren DEX'i seçmek.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from engine.dex import gas


@dataclass
class Quote:
    dex: str
    chain_id: int
    price: float
    fee_pct: float = 0.003       # DEX swap ücreti
    liquidity_usd: float = 0.0   # derinlik (slippage tahmini için)


def depth_slippage_bps(notional_usd: float, liquidity_usd: float,
                       impact_coef: float = 0.5) -> float:
    """Havuz derinliğine göre tahmini slippage (bps).

    Basit karekök fiyat-etkisi modeli: impact ~ coef * sqrt(notional/likidite).
    Likidite yoksa konservatif yüksek değer döner.
    """
    if liquidity_usd <= 0:
        return 500.0  # bilinmiyor → %5 konservatif
    ratio = notional_usd / liquidity_usd
    return impact_coef * math.sqrt(max(0.0, ratio)) * 10_000.0


def effective_cost_usd(q: Quote, notional_usd: float, side: str = "BUY") -> float:
    """Bir teklifin toplam etkin maliyeti (USD): slippage + DEX ücreti + gas."""
    slip_bps = depth_slippage_bps(notional_usd, q.liquidity_usd)
    slip_cost = notional_usd * slip_bps / 10_000.0
    fee_cost = notional_usd * q.fee_pct
    gas_cost = gas.gas_cost_usd(q.chain_id, gas.GAS_UNITS_SWAP)
    return slip_cost + fee_cost + gas_cost


def best_route(quotes: list[Quote], notional_usd: float,
               side: str = "BUY") -> tuple[Quote, float]:
    """Toplam etkin maliyeti en düşük teklifi seçer. Döner: (teklif, maliyet_usd)."""
    if not quotes:
        raise ValueError("teklif yok")
    scored = [(q, effective_cost_usd(q, notional_usd, side)) for q in quotes]
    scored.sort(key=lambda x: x[1])
    return scored[0]


def twap_slices(notional_usd: float, n_slices: int,
                min_slice_usd: float = 25.0) -> list[float]:
    """Büyük emri n parçaya böler (fiyat etkisini azaltmak için).

    Çok küçük parçalar gas'i ekonomik kılmaz → min_slice_usd altına bölmez.
    """
    if n_slices <= 1 or notional_usd <= min_slice_usd:
        return [notional_usd]
    max_slices = max(1, int(notional_usd // min_slice_usd))
    k = min(n_slices, max_slices)
    base = notional_usd / k
    return [base] * k


def gas_window_ok(current_gwei: float, max_gwei: float) -> bool:
    """Şu anki gas, tavanın altında mı? (ucuz pencere bekleme kararı için)."""
    return current_gwei <= max_gwei
