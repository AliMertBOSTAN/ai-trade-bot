"""Ortalamaya dönüş (mean-reversion) stratejisi.

Mantık: aşırı satımda (RSI düşük + Bollinger alt banda yakın) AL, aşırı alımda SAT.
YATAY piyasada iyi çalışır; güçlü trendde ters girmemek için ADX yüksekse kısar.
"""
from __future__ import annotations

from engine.strategy.base import BaseStrategy, StrategyContext, StrategySignal


class MeanReversionStrategy(BaseStrategy):
    name = "mean_reversion"

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        t = ctx.tech
        rsi_lo = self.p("rsi_oversold", 30.0)
        rsi_hi = self.p("rsi_overbought", 70.0)
        adx_max = self.p("adx_max", 30.0)

        # Güçlü trendde ortalamaya dönüş tehlikelidir → güveni kıs
        trend_penalty = max(0.0, min(1.0, (t.adx - adx_max) / 20.0))
        damp = 1.0 - trend_penalty

        oversold = t.rsi < rsi_lo and t.bb_pct_b < 20.0
        overbought = t.rsi > rsi_hi and t.bb_pct_b > 80.0

        if oversold:
            base = 0.5 + 0.5 * (rsi_lo - t.rsi) / rsi_lo
            return self._sig("BUY", base * damp,
                             f"aşırı satım (RSI {t.rsi:.0f}, %B {t.bb_pct_b:.0f})", atr=t.atr)
        if overbought:
            base = 0.5 + 0.5 * (t.rsi - rsi_hi) / max(100.0 - rsi_hi, 1.0)
            return self._sig("SELL", base * damp,
                             f"aşırı alım (RSI {t.rsi:.0f}, %B {t.bb_pct_b:.0f})", atr=t.atr)
        return self._sig("HOLD", 0.5, "nötr bölge", atr=t.atr)
