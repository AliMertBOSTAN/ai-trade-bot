"""Hibrit strateji — mevcut çok-göstergeli kural motorunu sarmalar.

signals.engine._rule_decision tüm göstergeleri (trend+salınım+momentum+pattern)
ağırlıklı birleştirir. Bu strateji onu çoklu-strateji çatısına taşır; böylece
diğer stratejilerle aynı anda, kendi sermaye dilimiyle çalışabilir.
"""
from __future__ import annotations

from engine.signals.engine import _rule_decision
from engine.strategy.base import BaseStrategy, StrategyContext, StrategySignal


class HybridStrategy(BaseStrategy):
    name = "hybrid"

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        action, conf = _rule_decision(ctx.tech)
        # haber sentiment'iyle hafif modülasyon (aksiyona hizalı)
        if action == "BUY":
            conf = min(1.0, conf + 0.1 * max(0.0, ctx.news_score))
        elif action == "SELL":
            conf = min(1.0, conf + 0.1 * max(0.0, -ctx.news_score))
        return self._sig(action, conf, "çok-göstergeli kural", atr=ctx.tech.atr)
