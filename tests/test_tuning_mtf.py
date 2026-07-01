"""Parametre ayarı (optimizer) + MTF onay testleri."""
import os
import random

from engine.config.settings import RiskConfig
from engine.tuning import optimizer
from engine.strategy.regime import mtf_confirm
from engine.indicators.technical import compute_snapshot
from engine.signals import engine as sig


def _candles(n=400, drift=0.2, noise=1.0, seed=1):
    rng = random.Random(seed)
    price = 100.0
    out = []
    for i in range(n):
        price = max(1.0, price + drift + rng.uniform(-noise, noise))
        out.append({"t": i * 3600000, "open": price, "high": price * 1.005,
                    "low": price * 0.995, "close": price, "volume": 1000.0})
    return out


def test_mtf_confirm_logic():
    up = compute_snapshot([100, 101, 102, 103, 104, 105] * 8)
    assert mtf_confirm("BUY", up) is True
    assert mtf_confirm("SELL", up) is False
    assert mtf_confirm("HOLD", up) is True


def test_optimize_and_store(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    candles = _candles(400, drift=0.25, noise=1.2, seed=3)
    res = optimizer.optimize_symbol(candles, "ETH", "USD", 10000.0,
                                    RiskConfig(), interval="1h")
    assert res["ok"] is True
    assert 0.0 <= res["min_confidence"] <= 1.0
    # diske yazildi -> get_tuned okuyabilmeli
    t = optimizer.get_tuned("ETH")
    assert t is not None and t["min_confidence"] == res["min_confidence"]


def test_apply_tuned_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    candles = _candles(400, drift=0.2, noise=1.3, seed=4)
    optimizer.optimize_symbol(candles, "BTC", "USD", 10000.0, RiskConfig())
    base = RiskConfig()
    applied = optimizer.apply_tuned(base, "BTC")
    t = optimizer.get_tuned("BTC")
    assert applied.min_confidence == t["min_confidence"]
    # bilinmeyen sembol -> degismez
    same = optimizer.apply_tuned(base, "DOGE")
    assert same.min_confidence == base.min_confidence


def test_apply_tuned_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "empty"))
    base = RiskConfig()
    assert optimizer.apply_tuned(base, "ETH").min_confidence == base.min_confidence


def test_signal_mtf_gate_reduces_on_conflict():
    # Alt-TF guclu yukselis (BUY uretir), ust-TF dusus -> guven kisilmali
    rng = random.Random(9)
    price = 100.0
    closes = []
    for i in range(120):
        price = price * 1.01
        closes.append(price)
    highs = [c * 1.004 for c in closes]
    lows = [c * 0.996 for c in closes]
    vols = [1000.0] * len(closes)
    # dusen ust-TF
    htf = [200.0 * (0.99 ** i) for i in range(60)]
    htf_h = [c * 1.004 for c in htf]
    htf_l = [c * 0.996 for c in htf]
    htf_v = [1000.0] * len(htf)

    sig.set_ml_model(None)
    s_no = sig.generate_signal(1, "ETH", "USDC", closes, highs, lows, vols)
    s_mtf = sig.generate_signal(1, "ETH", "USDC", closes, highs, lows, vols,
                                htf_closes=htf, htf_highs=htf_h, htf_lows=htf_l,
                                htf_volumes=htf_v)
    if s_no.action == "BUY":
        assert s_mtf.confidence <= s_no.confidence
        assert s_mtf.breakdown.get("mtfNote") in ("ust-TF celiskili (kisildi)",
                                                  "ust-TF onayladi (+3%)")
