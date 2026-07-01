"""technical.compute_snapshot — gösterge anlık görüntüsü sağlamlık testleri."""
import math

from engine.indicators.technical import compute_snapshot
from engine.models import TechnicalSnapshot


def _series(n=80):
    closes = [100 + 10 * math.sin(i / 5) + i * 0.2 for i in range(n)]
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    volumes = [1000 + i for i in range(n)]
    return closes, highs, lows, volumes


def test_snapshot_type_and_price():
    closes, highs, lows, volumes = _series()
    snap = compute_snapshot(closes, highs, lows, volumes)
    assert isinstance(snap, TechnicalSnapshot)
    assert snap.price == closes[-1]


def test_rsi_within_bounds():
    closes, highs, lows, volumes = _series()
    snap = compute_snapshot(closes, highs, lows, volumes)
    assert 0.0 <= snap.rsi <= 100.0
    assert 0.0 <= snap.stoch_rsi <= 100.0
    assert 0.0 <= snap.mfi <= 100.0


def test_closes_only_fallback_does_not_crash():
    closes, *_ = _series()
    snap = compute_snapshot(closes)  # highs/lows/volumes yok
    assert isinstance(snap, TechnicalSnapshot)
    assert math.isfinite(snap.rsi)


def test_to_dict_is_json_safe():
    closes, highs, lows, volumes = _series()
    d = compute_snapshot(closes, highs, lows, volumes).to_dict()
    assert "rsi" in d and "supertrend_dir" in d
    assert all(isinstance(v, (int, float)) for v in d.values())
