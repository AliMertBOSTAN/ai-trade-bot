"""Teknik göstergelerden ML özellik vektörü + etiketli veri seti üretimi."""
from __future__ import annotations

from engine.indicators.technical import compute_snapshot
from engine.models import TechnicalSnapshot

# Özellik adları (sıra önemli; model bu sırayla eğitilir/çalışır)
FEATURE_NAMES = [
    "rsi", "adx", "bb_pct_b", "macd_up", "supertrend_dir", "psar_dir",
    "ma_cross_dir", "smc_trend", "swing_trend", "momentum", "ema_up",
    "stoch_rsi", "williams_r", "mfi",
]


def feature_vector(t: TechnicalSnapshot) -> list[float]:
    """TechnicalSnapshot -> normalize edilmiş özellik vektörü."""
    return [
        t.rsi / 100.0,
        t.adx / 50.0,
        t.bb_pct_b / 100.0,
        1.0 if t.macd > t.macd_signal else 0.0,
        t.supertrend_dir,
        t.psar_dir,
        t.ma_cross_dir,
        t.smc_trend,
        t.swing_trend,
        max(-3.0, min(3.0, t.momentum)) / 3.0,
        1.0 if t.ema_fast > t.ema_slow else 0.0,
        t.stoch_rsi / 100.0,
        t.williams_r / 100.0,
        t.mfi / 100.0,
    ]


def make_dataset(candles: list[dict], horizon: int = 4,
                 warmup: int = 40) -> tuple[list[list[float]], list[int]]:
    """Mumlardan (özellik, etiket) seti. Etiket: horizon bar sonra fiyat YÜKSELDİ mi?"""
    closes = [c["close"] for c in candles]
    highs = [c.get("high", c["close"]) for c in candles]
    lows = [c.get("low", c["close"]) for c in candles]
    vols = [c.get("volume", 0.0) for c in candles]
    X: list[list[float]] = []
    y: list[int] = []
    for i in range(warmup, len(closes) - horizon):
        t = compute_snapshot(closes[:i + 1], highs[:i + 1], lows[:i + 1], vols[:i + 1])
        X.append(feature_vector(t))
        y.append(1 if closes[i + horizon] > closes[i] else 0)
    return X, y
