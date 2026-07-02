"""Haber duyarlılığı (sentiment) stratejisi.

Mantık: belirgin pozitif/negatif haber akışı + teknik onay birlikteyse işlem.
Haber TEK BAŞINA yetmez (manipülasyon/gürültü); EMA yönü onaylamalı.
news_score orkestratörden gelir (-1..+1); haber yoksa daima HOLD.
"""
from __future__ import annotations

from engine.strategy.base import BaseStrategy, StrategyContext, StrategySignal


class SentimentStrategy(BaseStrategy):
    name = "sentiment"

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        t = ctx.tech
        s = float(ctx.news_score or 0.0)
        thr = self.p("score_min", 0.25)       # min |duyarlılık|

        if abs(s) < thr:
            return self._sig("HOLD", 0.5, f"haber nötr ({s:+.2f})", atr=t.atr)

        tech_up = t.ema_fast > t.ema_slow
        conf = 0.50 + 0.35 * min(1.0, abs(s))
        if s > 0 and tech_up:
            return self._sig("BUY", conf,
                             f"pozitif haber ({s:+.2f}) + teknik onay", atr=t.atr)
        if s < 0:
            # negatif haberde teknik onay beklemeden korun (pozisyon kapatma)
            return self._sig("SELL", conf,
                             f"negatif haber ({s:+.2f}) — riskten kaçın", atr=t.atr)
        return self._sig("HOLD", 0.5,
                         f"haber pozitif ama teknik onay yok ({s:+.2f})", atr=t.atr)
