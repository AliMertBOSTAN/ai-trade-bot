"""Funding arbitrajı stratejisi (perp funding-farkında, delta-nötr eğilimli).

Mantık: Hyperliquid gibi perp piyasalarda funding oranı pozitifken LONG'lar
SHORT'lara ödeme yapar. Bu durumda delta-nötr kurulum (spot LONG + perp SHORT)
funding'i toplar; yön riski taşımaz. Bu strateji SPOT bacağını üretir (BUY),
perp SHORT bacağı ayrı venue'da (CexBroker/Hyperliquid keeper) açılır.

Funding güçlü NEGATİF ise tersi (spot azalt / nötr) → HOLD/SELL.
ctx.funding_pct (%/saat) gereklidir; yoksa HOLD.
"""
from __future__ import annotations

from engine.strategy.base import BaseStrategy, StrategyContext, StrategySignal


class FundingArbStrategy(BaseStrategy):
    name = "funding_arb"

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        f = ctx.funding_pct
        if f is None:
            return self._sig("HOLD", 0.4, "funding verisi yok")

        # Eşikler: saatlik funding %. 0.01%/saat ≈ %0.24/gün ≈ ~%87/yıl (yıllık APR)
        enter = self.p("funding_enter_pct", 0.01)   # bu üstünde fırsat
        strong = self.p("funding_strong_pct", 0.05)

        if f >= enter:
            # pozitif funding → spot LONG (perp SHORT ile delta-nötr), funding topla
            conf = 0.55 + min(0.45, (f - enter) / max(strong - enter, 1e-6) * 0.45)
            apr = f * 24 * 365
            return self._sig("BUY", conf,
                             f"funding+ {f:.4f}%/sa (~{apr:.0f}% APR) → spot long + perp short")
        if f <= -enter:
            # negatif funding → bu kurulum funding ÖDETİR; spot bacağı açma
            return self._sig("SELL", 0.5,
                             f"funding- {f:.4f}%/sa → kurulumu boz / spot azalt")
        return self._sig("HOLD", 0.5, f"funding nötr ({f:.4f}%/sa)")
