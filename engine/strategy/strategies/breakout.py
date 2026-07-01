"""Kırılım (breakout) stratejisi.

Mantık: fiyat Donchian üst kanalını kırarsa AL (momentum başlangıcı), alt kanalı
kırarsa SAT. Squeeze (TTM) sonrası kırılımlar daha güvenilir → güveni artırır.
"""
from __future__ import annotations

from engine.strategy.base import BaseStrategy, StrategyContext, StrategySignal


class BreakoutStrategy(BaseStrategy):
    name = "breakout"

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        t = ctx.tech
        price = ctx.price
        up = t.donchian_upper
        lo = t.donchian_lower
        if up <= 0 or lo <= 0 or up <= lo:
            return self._sig("HOLD", 0.4, "kanal yok", atr=t.atr)

        # Kanal genişliğine göre kırılım yakınlığı
        rng = up - lo
        near_top = (price - lo) / rng if rng else 0.5
        squeeze_release = t.squeeze_on <= 0 and t.squeeze_momentum != 0

        if price >= up * 0.999:
            conf = 0.6 + (0.2 if squeeze_release and t.squeeze_momentum > 0 else 0.0)
            return self._sig("BUY", conf, "üst kanal kırılımı", atr=t.atr)
        if price <= lo * 1.001:
            conf = 0.6 + (0.2 if squeeze_release and t.squeeze_momentum < 0 else 0.0)
            return self._sig("SELL", conf, "alt kanal kırılımı", atr=t.atr)
        return self._sig("HOLD", 0.5 - abs(near_top - 0.5),
                         "kanal içi", atr=t.atr)
