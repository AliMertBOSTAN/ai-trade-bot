"""Türev/likidasyon sinyali + on-chain (anahtarsız yollar) testleri."""
import os

from engine.marketdata import derivatives as dv
from engine.marketdata import onchain


def test_perp_symbol_normalize():
    assert dv._perp("ETH") == "ETHUSDT"
    assert dv._perp("BTCUSDT") == "BTCUSDT"
    assert dv._perp("ethusdc") == "ETHUSDT"


def test_squeeze_crowded_longs_bearish():
    # asiri pozitif funding -> kalabalik long -> long-squeeze (asagi, skor<0)
    sq = dv._squeeze_direction(funding=0.0015, oi_change_pct=2.0, ls_ratio=2.5)
    assert sq["score"] < 0
    assert "aşağı" in sq["direction"]


def test_squeeze_crowded_shorts_bullish():
    # asiri negatif funding + asiri short -> short-squeeze (yukari, skor>0)
    sq = dv._squeeze_direction(funding=-0.0015, oi_change_pct=1.0, ls_ratio=0.5)
    assert sq["score"] > 0
    assert "yukarı" in sq["direction"]


def test_squeeze_neutral():
    sq = dv._squeeze_direction(funding=0.00005, oi_change_pct=0.5, ls_ratio=1.0)
    assert sq["score"] == 0.0
    assert sq["direction"] == "nötr"


def test_squeeze_cascade_flag():
    sq = dv._squeeze_direction(funding=0.0, oi_change_pct=-8.0, ls_ratio=1.0)
    assert sq["cascade"] is True


def test_onchain_disabled_without_key(monkeypatch):
    monkeypatch.delenv("ETHERSCAN_API_KEY", raising=False)
    assert onchain.enabled() is False
    r = onchain.netflow_signal("ETH")
    assert r["enabled"] is False and r["score"] == 0.0


def test_onchain_non_eth_symbol():
    r = onchain.netflow_signal("BTC")
    assert r["enabled"] is False
