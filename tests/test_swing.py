"""patterns.swing_trend — Dow yapisi (HH+HL / LH+LL) testleri."""
import math
from engine.indicators import patterns as pat


def _series(drift, n=80):
    closes = [100 + drift * i + 8 * math.sin(i / 3.0) for i in range(n)]
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    return highs, lows


def test_uptrend_hh_hl():
    h, l = _series(+1.5)   # yukari drift + salinim -> yukselen tepe+dip
    assert pat.swing_trend(h, l) == 1


def test_downtrend_lh_ll():
    h, l = _series(-1.5)   # asagi drift -> dusen tepe+dip
    assert pat.swing_trend(h, l) == -1


def test_ternary_and_short_input():
    assert pat.swing_trend([1, 2, 3], [0, 1, 2]) == 0   # yetersiz pivot
    h, l = _series(+1.5)
    assert pat.swing_trend(h, l) in (-1, 0, 1)
