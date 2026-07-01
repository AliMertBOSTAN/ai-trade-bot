"""Pozisyon boyutlandırma — sabit nominal yerine risk-tabanlı.

Yöntemler:
  • risk_based_size: sermayenin %X'ini riske at, stop mesafesine göre boyutla.
  • atr_based_size: stop'u ATR'ye bağla (oynaklık-uyarlı).
  • fractional_kelly: kazanma oranı + ödül/risk'ten kesirli Kelly.
  • apply_caps: varlık/zincir/toplam maruziyet tavanları.
Tüm fonksiyonlar saf ve test edilebilir; USD nominal döndürür.
"""
from __future__ import annotations


def risk_based_size(equity_usd: float, risk_pct: float, entry: float,
                    stop_price: float) -> float:
    """Sermayenin risk_pct'i kadar zararı stop'a kadar göze alan nominal (USD).

    risk_amount = equity * risk_pct ; birim risk = |entry - stop| / entry
    nominal = risk_amount / birim_risk
    """
    if entry <= 0 or risk_pct <= 0 or equity_usd <= 0:
        return 0.0
    unit_risk = abs(entry - stop_price) / entry
    if unit_risk <= 0:
        return 0.0
    risk_amount = equity_usd * risk_pct
    return risk_amount / unit_risk


def atr_based_size(equity_usd: float, risk_pct: float, entry: float,
                   atr: float, atr_mult: float = 2.0) -> float:
    """Stop'u ATR'ye bağlayarak risk-tabanlı boyut (oynaklık-uyarlı).

    stop mesafesi = atr_mult * ATR ; düşük oynaklıkta büyük, yüksekte küçük pozisyon.
    """
    if entry <= 0 or atr <= 0:
        return 0.0
    stop_price = entry - atr_mult * atr
    return risk_based_size(equity_usd, risk_pct, entry, stop_price)


def fractional_kelly(win_rate: float, win_loss_ratio: float,
                     fraction: float = 0.5) -> float:
    """Kesirli Kelly oranı (sermayenin yüzdesi olarak, 0..1'e kırpılı).

    Kelly f* = W - (1-W)/R  (W: kazanma olasılığı, R: ortalama kazanç/kayıp).
    Tam Kelly çok agresif → fraction (örn. 0.5 = yarım Kelly) ile ölçekle.
    """
    if win_loss_ratio <= 0:
        return 0.0
    k = win_rate - (1.0 - win_rate) / win_loss_ratio
    k = max(0.0, k) * fraction
    return min(1.0, k)


def apply_caps(size_usd: float, *, equity_usd: float,
               existing_asset_usd: float = 0.0,
               existing_chain_usd: float = 0.0,
               existing_total_usd: float = 0.0,
               max_per_asset_pct: float = 0.25,
               max_per_chain_pct: float = 0.50,
               max_total_pct: float = 0.95,
               max_abs_usd: float | None = None) -> float:
    """İstenen nominali maruziyet tavanlarına göre kırpar (negatif olmaz).

    Tüm yüzdeler equity'ye göredir. Mevcut maruziyetler düşülür.
    """
    if size_usd <= 0 or equity_usd <= 0:
        return 0.0
    caps = [
        max_per_asset_pct * equity_usd - existing_asset_usd,
        max_per_chain_pct * equity_usd - existing_chain_usd,
        max_total_pct * equity_usd - existing_total_usd,
    ]
    if max_abs_usd is not None:
        caps.append(max_abs_usd)
    allowed = min([size_usd] + caps)
    return max(0.0, allowed)
