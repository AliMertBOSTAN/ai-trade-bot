"""Momentum (ROC) stratejisi.

Mantık: fiyat değişim hızı (10-bar momentum %) güçlü ve Awesome Oscillator +
DI yönü onaylıyorsa momentum yönünde işlem. Trend stratejisinden farkı:
EMA dizilimi beklemez — hızlanmayı erken yakalar, ivme kaybında çıkar.
"""
from __future__ import annotations

from engine.strategy.base import BaseStrategy, StrategyContext, StrategySignal


class MomentumStrategy(BaseStrategy):
    name = "momentum"

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        t = ctx.tech
        roc_min = self.p("roc_min", 1.5)      # min %10-bar değişim
        adx_min = self.p("adx_min", 18.0)

        if t.adx < adx_min:
            return self._sig("HOLD", 0.5, f"ivme için zayıf piyasa (ADX {t.adx:.0f})",
                             atr=t.atr)

        up = t.momentum > roc_min and t.awesome > 0 and t.plus_di > t.minus_di
        down = t.momentum < -roc_min and t.awesome < 0 and t.minus_di > t.plus_di

        # güven: ivmenin gücüyle ölçekle (%1.5 taban, %6+ tavan)
        strength = min(1.0, abs(t.momentum) / 6.0)
        if up:
            return self._sig("BUY", 0.55 + 0.35 * strength,
                             f"ivme↑ (mom %{t.momentum:.1f}, AO+)", atr=t.atr)
        if down:
            return self._sig("SELL", 0.55 + 0.35 * strength,
                             f"ivme↓ (mom %{t.momentum:.1f}, AO-)", atr=t.atr)
        return self._sig("HOLD", 0.5, "ivme onayı yok", atr=t.atr)
