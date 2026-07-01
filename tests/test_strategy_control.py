"""Strateji kullanıcı kontrolü + AI mum özeti testleri."""
from engine.strategy.config import default_manager
from engine.signals import llm


def test_set_enabled_and_weight():
    m = default_manager()
    assert m.set_weight("trend", 2.5) is True
    assert m._find("trend").weight == 2.5
    assert m.set_enabled("hybrid", False) is True
    assert m._find("hybrid").enabled is False


def test_enable_adds_registered_strategy():
    m = default_manager()
    # kayıtlı ama belki aktif değil -> set_enabled True onu ekleyip açar
    assert m.set_enabled("funding_arb", True) is True
    assert any(a.strategy.name == "funding_arb" and a.enabled for a in m.allocations)


def test_unknown_strategy_rejected():
    m = default_manager()
    assert m.set_enabled("yok_boyle", True) is False
    assert m.set_weight("yok_boyle", 1.0) is False


def test_describe_has_details():
    m = default_manager()
    d = m.describe()
    assert all("title" in x and "description" in x and "regime" in x for x in d)


def test_to_config_roundtrip():
    from engine.strategy.manager import StrategyManager
    m = default_manager()
    m.set_weight("trend", 3.0)
    m.set_enabled("mean_reversion", False)
    cfg = m.to_config()
    m2 = StrategyManager.from_config(cfg)
    assert m2._find("trend").weight == 3.0
    assert m2._find("mean_reversion").enabled is False


def test_available_info_covers_all():
    m = default_manager()
    info = m.available_info()
    names = {i["name"] for i in info}
    assert {"trend", "mean_reversion", "breakout", "hybrid"} <= names


def test_candle_summary_detects_bullish_engulfing():
    # son mum bir önceki kırmızıyı yutan yeşil
    closes = [100, 98, 102]
    highs = [101, 99, 103]
    lows = [99, 96, 97]
    opens = [100.5, 99, 97]
    out = llm._candle_summary(closes, highs, lows, opens, n=3)
    assert "yutan boğa" in out


def test_candle_summary_doji():
    closes = [100, 100, 100.02]
    highs = [101, 101, 101]
    lows = [99, 99, 99]
    opens = [100, 100, 100.0]
    out = llm._candle_summary(closes, highs, lows, opens, n=3)
    assert "doji" in out


def test_candle_in_prompt():
    from engine.indicators.technical import compute_snapshot
    closes = [100 + i for i in range(60)]
    tech = compute_snapshot(closes)
    p = llm._build_user_prompt("ETH", "USDC", tech, "BUY", [1.0, 0.5],
                               candles={"closes": closes})
    assert "SON MUMLAR" in p
