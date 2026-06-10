"""Teknik göstergeler (saf Python, bağımlılık yok).

RSI, EMA, MACD, momentum. Hibrit sinyalin "kural tabanlı" ön-filtre katmanı.
"""
from __future__ import annotations

from engine.models import TechnicalSnapshot


def ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    k = 2 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


def ema_series(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(values: list[float], period: int = 14) -> float:
    if len(values) < period + 1:
        return 50.0
    gains, losses = 0.0, 0.0
    for i in range(-period, 0):
        diff = values[i] - values[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(values: list[float], fast: int = 12, slow: int = 26,
         signal: int = 9) -> tuple[float, float]:
    if len(values) < slow:
        return 0.0, 0.0
    fast_s = ema_series(values, fast)
    slow_s = ema_series(values, slow)
    macd_line = [f - s for f, s in zip(fast_s, slow_s)]
    signal_line = ema(macd_line[-signal * 3:] or macd_line, signal)
    return macd_line[-1], signal_line


def momentum(values: list[float], period: int = 10) -> float:
    if len(values) <= period:
        return 0.0
    return (values[-1] - values[-period - 1]) / values[-period - 1] * 100


def compute_snapshot(closes: list[float]) -> TechnicalSnapshot:
    macd_v, macd_sig = macd(closes)
    return TechnicalSnapshot(
        rsi=rsi(closes),
        ema_fast=ema(closes[-50:] or closes, 12),
        ema_slow=ema(closes[-50:] or closes, 26),
        macd=macd_v,
        macd_signal=macd_sig,
        momentum=momentum(closes),
        price=closes[-1] if closes else 0.0,
    )
