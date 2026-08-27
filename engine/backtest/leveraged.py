"""Kaldıraçlı backtest — kaldıracın stratejiye NE YAPTIĞINI ölçer.

Mevcut `run_backtest` sonucunun equity eğrisi alınır ve her bar getirisi
kaldıraçla çarpılır. Modelleme varsayımları AÇIKÇA şudur:

  • Sabit kaldıraç (her bar yeniden dengelenir) — perp'te tipik davranış.
  • **Likidasyon mutlak bariyerdir**: equity ≤ bakım teminatı seviyesine
    inerse pozisyon kapanır ve sermaye SIFIRLANIR. Geri dönüş yoktur.
  • Funding maliyeti her bar düşülür (perp'te long pozisyon genelde öder).
  • Kaldıraç, alım-satım ücretlerini de büyütür (nosyonel L kat).

Bu kasıtlı olarak İYİMSER bir modeldir (slippage derinliği, likidasyon cezası
ve funding dalgalanması dahil değil) — yani gerçek sonuç buradan DAHA KÖTÜdür.
Buna rağmen yüksek kaldıraçta sonuç negatife dönüyorsa, bu bir kanıttır.

Neden getiriler çarpılıyor da pozisyon büyüklüğü değil?
  Sabit kaldıraçlı bir pozisyonun bar getirisi tanım gereği L × dayanak getirisi
  kadardır. Aradaki tek fark, kaldıracın YOL BAĞIMLILIĞI (volatility drag) —
  bu da bileşik çarpımda zaten doğru şekilde ortaya çıkar:
      E[(1+L·r)] > 1  olsa bile  ∏(1+L·r) < 1  olabilir.
"""
from __future__ import annotations

import logging
import math

log = logging.getLogger("backtest.leveraged")

# Bakım teminatı: equity bu orana düşünce likidasyon (borsalarda ~%0,5).
DEFAULT_MAINTENANCE = 0.005
# Perp funding: bar başına maliyet (8 saatte ~%0,01 → 4h barda ~%0,005).
DEFAULT_FUNDING_PER_BAR = 0.00005
# Kaldıraçlı işlemin ek alım-satım maliyeti (nosyonel başına, tek yön).
DEFAULT_TAKER_FEE = 0.00045


def equity_returns(equity_curve: list) -> list[float]:
    """Equity eğrisinden bar-başı getiri listesi (dict veya float kabul eder)."""
    eq = [(e["equity"] if isinstance(e, dict) else float(e)) for e in equity_curve]
    return [(eq[i] / eq[i - 1] - 1.0)
            for i in range(1, len(eq)) if eq[i - 1] > 0]


def apply_leverage(returns: list[float], leverage: float,
                   maintenance: float = DEFAULT_MAINTENANCE,
                   funding_per_bar: float = DEFAULT_FUNDING_PER_BAR,
                   taker_fee: float = DEFAULT_TAKER_FEE,
                   n_trades: int = 0) -> dict:
    """Getiri serisine sabit kaldıraç uygular. Likidasyon olursa erken biter.

    Maliyet modeli (kasıtlı olarak muhafazakâr ama HAKSIZ değil):
      • **funding**: yalnızca POZİSYONDA olunan barlarda (r ≠ 0) ve nosyonel
        kaldıraçla orantılı. Boşta duran barlar funding ödemez.
      • **komisyon**: bar başına DEĞİL, gerçek işlem sayısına göre
        (giriş + çıkış = 2 bacak) ve nosyonel kaldıraçla orantılı.
      • **likidasyon**: equity bakım teminatı altına inerse sermaye SIFIR.

    Döner: {leverage, total_return_pct, max_drawdown_pct, liquidated,
            liquidation_bar, final_multiple, bars, funding_cost_pct,
            fee_cost_pct, in_position_bars}
    """
    lev = max(1.0, float(leverage))
    eq = 1.0
    peak = 1.0
    dd = 0.0
    liq_bar = -1
    funding_total = 0.0
    in_pos = 0
    for i, r in enumerate(returns):
        # funding yalnızca pozisyondayken işler
        cost = (funding_per_bar * lev) if r != 0.0 else 0.0
        if r != 0.0:
            in_pos += 1
        funding_total += cost
        eq *= (1.0 + lev * r - cost)
        if eq <= maintenance:          # LİKİDASYON — mutlak bariyer
            eq = 0.0
            liq_bar = i
            break
        peak = max(peak, eq)
        dd = max(dd, (peak - eq) / peak)

    # komisyon: gerçek işlem sayısı × 2 bacak × nosyonel kaldıraç
    fee_total = 2.0 * max(0, int(n_trades)) * taker_fee * lev
    if liq_bar < 0 and fee_total > 0:
        eq *= max(0.0, 1.0 - fee_total)
        if eq <= maintenance:
            eq, liq_bar = 0.0, len(returns) - 1

    return {
        "leverage": round(lev, 3),
        "total_return_pct": round((eq - 1.0) * 100.0, 4),
        "max_drawdown_pct": round(dd * 100.0, 3),
        "liquidated": liq_bar >= 0,
        "liquidation_bar": (liq_bar if liq_bar >= 0 else None),
        "final_multiple": round(eq, 6),
        "bars": len(returns),
        "in_position_bars": in_pos,
        "funding_cost_pct": round(funding_total * 100.0, 3),
        "fee_cost_pct": round(fee_total * 100.0, 3),
    }


def leverage_sweep(equity_curve: list,
                   levels: tuple[float, ...] = (1, 2, 3, 5, 10, 20, 50),
                   n_trades: int = 0, **kw) -> dict:
    """Aynı stratejiyi farklı kaldıraçlarda ölçer + en iyi kaldıracı bulur.

    "En iyi" = likide olmayan ve toplam getirisi en yüksek kaldıraç. Bu değer
    GEÇMİŞE bakar; canlıda kullanılacak kaldıraç `risk.leverage.decide_leverage`
    (Kelly + ölçülen istatistik) tarafından belirlenir.
    """
    rets = equity_returns(equity_curve)
    rows = [apply_leverage(rets, L, n_trades=n_trades, **kw) for L in levels]
    alive = [r for r in rows if not r["liquidated"]]
    best = max(alive, key=lambda r: r["total_return_pct"]) if alive else None
    first_liq = next((r["leverage"] for r in rows if r["liquidated"]), None)
    return {
        "bars": len(rets),
        "rows": rows,
        "best_leverage": (best["leverage"] if best else 1.0),
        "best_return_pct": (best["total_return_pct"] if best else None),
        "first_liquidating_leverage": first_liq,
        "note": ("Kaldıraç kenarı ÇARPAR; kenar yoksa çarpım da yoktur. "
                 "Likidasyon mutlak bariyerdir — bir kez değince geri dönüş yok."),
    }


def growth_probability_bound(start_usd: float, target_usd: float) -> float:
    """Adil piyasada `start` → `target` olasılığının üst sınırı (1/kat)."""
    if start_usd <= 0 or target_usd <= start_usd:
        return 1.0
    return start_usd / target_usd


def bars_needed(multiple: float, per_bar_return: float) -> float | None:
    """Verilen bar-başı getiriyle `multiple` katına kaç barda ulaşılır."""
    if multiple <= 1 or per_bar_return <= 0:
        return None
    return math.log(multiple) / math.log(1.0 + per_bar_return)
