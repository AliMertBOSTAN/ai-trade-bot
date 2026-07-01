"""Trend takip stratejisi.

Mantık: güçlü trendde (ADX yüksek) trend yönünde işlem; EMA dizilimi + Supertrend
+ MACD onayı. Yatay/zayıf trendde (düşük ADX) işlem AÇMAZ → choppy'de durur.
"""
from __future__ import annotations

from engine.strategy.base import BaseStrategy, StrategyContext, StrategySignal


class TrendFollowingStrategy(BaseStrategy):
    name = "trend"

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        t = ctx.tech
        adx_min = self.p("adx_min", 22.0)

        # Trend gücü kapısı: zayıf trendde işlem yok (overtrading önleme)
        if t.adx < adx_min:
            return self._sig("HOLD", 1.0 - t.adx / max(adx_min, 1.0),
                             f"zayıf trend (ADX {t.adx:.0f}<{adx_min:.0f})", atr=t.atr)

        up = (t.ema_fast > t.ema_slow) and (t.supertrend_dir >= 0) and (t.macd > t.macd_signal)
        down = (t.ema_fast < t.ema_slow) and (t.supertrend_dir < 0) and (t.macd < t.macd_signal)

        # güven: ADX'i 0..1'e ölçekle (25 güçlü, 50+ çok güçlü)
        strength = min(1.0, t.adx / 50.0)
        if up:
            return self._sig("BUY", 0.55 + 0.45 * strength,
                             f"trend↑ (ADX {t.adx:.0f})", atr=t.atr)
        if down:
            return self._sig("SELL", 0.55 + 0.45 * strength,
                             f"trend↓ (ADX {t.adx:.0f})", atr=t.atr)
        return self._sig("HOLD", 0.5, "trend belirsiz", atr=t.atr)
