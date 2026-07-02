"""Sıkışma patlaması (TTM Squeeze) stratejisi.

Mantık: Bollinger, Keltner kanalının İÇİNE girince piyasa "sıkışmıştır"
(düşük oynaklık birikimi). Sıkışma AÇILDIĞINDA momentum yönünde patlama
beklenir. Sıkışma sürerken asla işlem açmaz — sabırlı bir strateji.
"""
from __future__ import annotations

from engine.strategy.base import BaseStrategy, StrategyContext, StrategySignal


class SqueezeStrategy(BaseStrategy):
    name = "squeeze"

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        t = ctx.tech
        mom_min = self.p("mom_min", 0.0)

        if t.squeeze_on > 0:
            return self._sig("HOLD", 0.6, "sıkışma sürüyor — patlama bekleniyor",
                             atr=t.atr)
        if t.squeeze_momentum == 0:
            return self._sig("HOLD", 0.4, "sıkışma/momentum sinyali yok", atr=t.atr)

        # sıkışma kapalı + momentum yönü belli → onay katmanları
        direction_up = t.squeeze_momentum > mom_min
        macd_ok = (t.macd > t.macd_signal) if direction_up else (t.macd < t.macd_signal)
        st_ok = (t.supertrend_dir >= 0) if direction_up else (t.supertrend_dir < 0)
        conf = 0.55 + (0.12 if macd_ok else 0.0) + (0.12 if st_ok else 0.0)
        # FVG yönü hizalıysa küçük bonus
        if (t.fvg_bias > 0) == direction_up and t.fvg_bias != 0:
            conf += 0.06

        if direction_up:
            return self._sig("BUY", conf, "sıkışma açıldı → momentum yukarı",
                             atr=t.atr)
        return self._sig("SELL", conf, "sıkışma açıldı → momentum aşağı", atr=t.atr)
