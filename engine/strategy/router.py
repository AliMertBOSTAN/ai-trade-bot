"""Rejim yönlendirici — piyasa rejimine göre AKTİF stratejileri seçer.

Trend piyasasında trend/breakout, yatay (range) piyasada mean_reversion öne
çıkar; hybrid her rejimde çalışır. Böylece choppy piyasada trend-takip whipsaw'u
azalır, trendde mean-reversion'un ters girişleri elenir.

`select_active` rejime UYAN etkin stratejileri ve normalize edilmiş ağırlıklarını
döndürür. Hiçbiri uymazsa hybrid'e (varsa) düşer — fail-safe.
"""
from __future__ import annotations

from engine.models import TechnicalSnapshot
from engine.strategy.regime import detect_regime, strategy_fits_regime


def select_active(manager, tech: TechnicalSnapshot,
                  adx_trend: float = 25.0) -> tuple[str, dict[str, float]]:
    """Mevcut rejim + uygun stratejilerin normalize ağırlıkları.

    Döner: (regime, {strateji_adı: ağırlık}). Ağırlıklar toplamı 1 (boşsa {}).
    """
    regime = detect_regime(tech, adx_trend)
    fitting = [
        (a.strategy.name, a.weight)
        for a in manager.allocations
        if a.enabled and strategy_fits_regime(a.strategy.name, regime)
    ]
    # Hiçbiri uymadıysa: hybrid'e düş (her rejimde geçerli)
    if not fitting:
        fitting = [(a.strategy.name, a.weight) for a in manager.allocations
                   if a.enabled and a.strategy.name == "hybrid"]
    total = sum(w for _, w in fitting) or 1.0
    return regime, {name: w / total for name, w in fitting}
