"""Geri çekilme (pullback / swing) stratejisi.

Mantık: yapısal YÜKSELİŞ trendinde (EMA dizilimi + Dow swing yapısı) kısa
vadeli aşırı satım dipleri ALIM fırsatıdır ("trende katıl, zirveden kovalama").
Aşırı ısınmada veya trend yapısı bozulunca pozisyonu kapatır. Long-only doğaldır.
"""
from __future__ import annotations

from engine.strategy.base import BaseStrategy, StrategyContext, StrategySignal


class PullbackStrategy(BaseStrategy):
    name = "pullback"

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        t = ctx.tech
        rsi_dip = self.p("rsi_dip", 45.0)     # dip kabul eşiği
        rsi_exit = self.p("rsi_exit", 72.0)   # kâr alma eşiği
        adx_min = self.p("adx_min", 18.0)

        uptrend = (t.ema_fast > t.ema_slow and t.swing_trend >= 0
                   and t.adx >= adx_min)
        broken = t.ema_fast < t.ema_slow and t.swing_trend < 0

        if broken:
            return self._sig("SELL", 0.62, "trend yapısı bozuldu (LH+LL)", atr=t.atr)
        if not uptrend:
            return self._sig("HOLD", 0.5, "yükseliş yapısı yok", atr=t.atr)

        # trend sağlam → dipte mi?
        dip = t.rsi <= rsi_dip and t.bb_pct_b <= 45.0
        overheated = t.rsi >= rsi_exit or t.bb_pct_b >= 92.0
        if dip:
            depth = min(1.0, (rsi_dip - t.rsi) / rsi_dip + 0.3)
            return self._sig("BUY", 0.55 + 0.30 * depth,
                             f"trend içi dip (RSI {t.rsi:.0f}, %B {t.bb_pct_b:.0f})",
                             atr=t.atr)
        if overheated:
            return self._sig("SELL", 0.58,
                             f"aşırı ısınma — kâr al (RSI {t.rsi:.0f})", atr=t.atr)
        return self._sig("HOLD", 0.5, "trend sağlam, dip bekleniyor", atr=t.atr)
