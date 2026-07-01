"""ML sinyal katmani testleri (saf-Python lojistik regresyon)."""
import random

from engine.ml.logistic import LogisticRegression
from engine.ml.model import (MLSignal, blend_confidence, train_from_candles,
                             walk_forward_models)
from engine.ml.features import feature_vector, make_dataset, FEATURE_NAMES
from engine.indicators.technical import compute_snapshot


def test_logistic_learns_separable():
    X = [[i / 10.0, 0.0] for i in range(20)]
    y = [1 if i >= 10 else 0 for i in range(20)]
    m = LogisticRegression(epochs=500).fit(X, y)
    assert m.predict_proba([1.8, 0.0]) > 0.7
    assert m.predict_proba([0.1, 0.0]) < 0.3


def test_logistic_save_load_roundtrip(tmp_path):
    X = [[i / 10.0] for i in range(20)]
    y = [1 if i >= 10 else 0 for i in range(20)]
    m = LogisticRegression(epochs=300).fit(X, y)
    p = str(tmp_path / "m.json")
    m.save(p)
    m2 = LogisticRegression.load(p)
    assert abs(m.predict_proba([1.5]) - m2.predict_proba([1.5])) < 1e-9


def _noisy_candles(n=500, drift=0.1, noise=1.5, seed=1):
    """Karisik-etiketli (hem yukselis hem dusus) gercekci seri."""
    rng = random.Random(seed)
    price = 100.0
    out = []
    for i in range(n):
        price = max(1.0, price + drift + rng.uniform(-noise, noise))
        out.append({"t": i, "open": price, "high": price * 1.004,
                    "low": price * 0.996, "close": price, "volume": 1000.0})
    return out


def test_dataset_shapes_and_mixed_labels():
    candles = _noisy_candles(300)
    X, y = make_dataset(candles, horizon=4, warmup=40)
    assert len(X) == len(y) > 0
    assert all(len(row) == len(FEATURE_NAMES) for row in X)
    assert set(y) == {0, 1}  # her iki sinif da var


def test_train_learns_better_than_chance():
    candles = _noisy_candles(500, drift=0.15, noise=1.2, seed=2)
    ml = train_from_candles(candles, horizon=4)
    X, y = make_dataset(candles, horizon=4, warmup=40)
    correct = sum(1 for x, yy in zip(X, y)
                  if (ml.model.predict_proba(x) >= 0.5) == bool(yy))
    acc = correct / len(X)
    assert acc > 0.5  # rasgeleden iyi (egitim icinde)
    # predict_up gecerli olasilik dondurur
    tech = compute_snapshot([c["close"] for c in candles],
                            [c["high"] for c in candles],
                            [c["low"] for c in candles],
                            [c["volume"] for c in candles])
    p = ml.predict_up(tech)
    assert 0.0 <= p <= 1.0


def test_blend_confidence_directions():
    assert blend_confidence(0.6, 0.9, "BUY") > 0.6
    assert blend_confidence(0.6, 0.1, "BUY") < 0.6
    assert blend_confidence(0.6, 0.1, "SELL") > 0.6
    assert blend_confidence(0.6, 0.9, "HOLD") == 0.6
    assert 0.0 <= blend_confidence(0.0, 0.0, "BUY") <= 1.0


def test_walk_forward_runs():
    candles = _noisy_candles(600, drift=0.1, noise=1.5, seed=3)
    res = walk_forward_models(candles, folds=3, horizon=4)
    assert len(res) >= 1
    assert all(0.0 <= r["accuracy"] <= 1.0 for r in res)


def test_feature_importance_sorted():
    candles = _noisy_candles(400, drift=0.1, noise=1.4, seed=4)
    ml = train_from_candles(candles)
    imp = ml.feature_importance()
    assert len(imp) == len(FEATURE_NAMES)
    vals = [abs(w) for _, w in imp]
    assert vals == sorted(vals, reverse=True)
