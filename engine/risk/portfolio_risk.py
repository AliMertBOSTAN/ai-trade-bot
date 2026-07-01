"""Portföy-seviyesi risk: korelasyon, maruziyet tavanları, drawdown de-risking,
oynaklık hedefleme.

Pozisyon-bazlı risk_manager'ı tamamlar: tekil işlem onaylanabilir ama portföy
genelinde yoğunlaşma/korelasyon/zarar durumuna göre boyut KÜÇÜLTÜLÜR.
"""
from __future__ import annotations

import math


def correlation(a: list[float], b: list[float]) -> float:
    """İki getiri serisi arasında Pearson korelasyonu (-1..+1)."""
    n = min(len(a), len(b))
    if n < 2:
        return 0.0
    a, b = a[:n], b[:n]
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    if va <= 0 or vb <= 0:
        return 0.0
    return cov / math.sqrt(va * vb)


def exposure_by(positions: list[dict], key: str) -> dict[str, float]:
    """Pozisyonları bir anahtara göre toplam USD maruziyetine indirger.

    positions: [{"base":..., "chain_id":..., "notional_usd":...}, ...]
    key: "base" | "chain_id"
    """
    out: dict[str, float] = {}
    for p in positions:
        k = str(p.get(key))
        out[k] = out.get(k, 0.0) + float(p.get("notional_usd", 0.0))
    return out


def drawdown_derisk_factor(current_dd_pct: float,
                           soft_dd_pct: float = 10.0,
                           hard_dd_pct: float = 25.0) -> float:
    """Drawdown arttıkça pozisyon boyutunu küçülten çarpan (1.0 → 0.0).

    soft altında tam boyut; soft→hard arası doğrusal azalır; hard üstünde 0 (dur).
    """
    if current_dd_pct <= soft_dd_pct:
        return 1.0
    if current_dd_pct >= hard_dd_pct:
        return 0.0
    span = hard_dd_pct - soft_dd_pct
    return max(0.0, 1.0 - (current_dd_pct - soft_dd_pct) / span)


def vol_target_scale(realized_vol: float, target_vol: float,
                     max_scale: float = 1.5) -> float:
    """Oynaklık hedefleme: gerçekleşen oynaklık hedeften düşükse boyut artar,
    yüksekse azalır. (scale = target/realized, max_scale ile sınırlı.)
    """
    if realized_vol <= 0:
        return 1.0
    return min(max_scale, target_vol / realized_vol)


def correlation_penalty(new_returns: list[float],
                        existing: list[list[float]],
                        threshold: float = 0.7) -> float:
    """Yeni pozisyon mevcutlarla yüksek korelasyonluysa boyut çarpanını kısar.

    En yüksek korelasyon threshold'u aşıyorsa, aşım oranında 1.0→0.3 arası kısar.
    """
    if not existing:
        return 1.0
    max_corr = max(abs(correlation(new_returns, e)) for e in existing)
    if max_corr <= threshold:
        return 1.0
    over = (max_corr - threshold) / (1.0 - threshold)  # 0..1
    return max(0.3, 1.0 - 0.7 * over)
