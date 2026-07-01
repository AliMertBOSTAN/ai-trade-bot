"""Piyasa rejimi tespiti + cooldown + çoklu zaman dilimi (MTF) onayı.

Amaç: dalgalı (choppy) piyasada aşırı işlemi azaltmak ve sinyal kalitesini
artırmak. Rejim "trend" veya "range" olarak sınıflanır; cooldown aynı sembolde
arka arkaya işlemleri sınırlar; MTF onayı üst zaman dilimiyle çelişen girişleri eler.
"""
from __future__ import annotations

import time

from engine.models import TechnicalSnapshot

Regime = str  # "trend_up" | "trend_down" | "range"


def detect_regime(tech: TechnicalSnapshot, adx_trend: float = 25.0) -> Regime:
    """ADX + EMA dizilimiyle rejim sınıflar.

    ADX >= adx_trend → trend (EMA yönüne göre up/down); aksi halde range.
    """
    if tech.adx >= adx_trend:
        return "trend_up" if tech.ema_fast >= tech.ema_slow else "trend_down"
    return "range"


def is_trending(tech: TechnicalSnapshot, adx_trend: float = 25.0) -> bool:
    return detect_regime(tech, adx_trend) != "range"


def strategy_fits_regime(strategy_name: str, regime: Regime) -> bool:
    """Bir stratejinin mevcut rejime uygun olup olmadığı (yumuşak filtre).

    - trend/breakout: trend rejimlerinde
    - mean_reversion: range rejiminde
    - hybrid: her rejimde (zaten ADX'i içsel kullanır)
    """
    if strategy_name in ("trend", "breakout"):
        return regime in ("trend_up", "trend_down")
    if strategy_name == "mean_reversion":
        return regime == "range"
    return True


class Cooldown:
    """Sembol başına işlem sonrası bekleme süresi (saniye).

    Aynı sembolde çok sık işlem açmayı engeller → işlem maliyeti + gürültü azalır.
    """

    def __init__(self, seconds: float = 900.0):
        self.seconds = seconds
        self._last: dict[str, float] = {}

    def ready(self, symbol: str, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        last = self._last.get(symbol)
        return last is None or (now - last) >= self.seconds

    def mark(self, symbol: str, now: float | None = None) -> None:
        self._last[symbol] = now if now is not None else time.time()

    def remaining(self, symbol: str, now: float | None = None) -> float:
        now = now if now is not None else time.time()
        last = self._last.get(symbol)
        if last is None:
            return 0.0
        return max(0.0, self.seconds - (now - last))


def mtf_confirm(action: str, higher_tf: TechnicalSnapshot) -> bool:
    """Üst zaman dilimi alt-TF aksiyonunu onaylıyor mu?

    BUY için üst-TF yükseliş eğiliminde (EMA fast>=slow ya da supertrend yukarı),
    SELL için düşüş eğiliminde olmalı. HOLD daima onaylı.
    """
    if action == "HOLD":
        return True
    up = higher_tf.ema_fast >= higher_tf.ema_slow or higher_tf.supertrend_dir >= 0
    if action == "BUY":
        return up
    if action == "SELL":
        return not up
    return True
