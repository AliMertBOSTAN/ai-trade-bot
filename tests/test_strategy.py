"""Coklu-strateji catisi: registry + stratejiler + manager."""
import math

from engine.indicators.technical import compute_snapshot
from engine.strategy import registry
from engine.strategy.base import StrategyContext
from engine.strategy.manager import StrategyManager
import engine.strategy.strategies  # noqa: F401  (kayitlari yukler)


def _ctx(closes, cash=1000.0, news=0.0):
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    vols = [1000.0] * len(closes)
    tech = compute_snapshot(closes, highs, lows, vols)
    return StrategyContext(base="ETH", quote="USDC", chain_id=1, closes=closes,
                           highs=highs, lows=lows, volumes=vols, tech=tech,
                           price=closes[-1], cash_allocated=cash, news_score=news)


def test_registry_has_builtin_strategies():
    names = registry.available()
    for n in ("trend", "mean_reversion", "breakout", "hybrid"):
        assert n in names


def test_each_strategy_returns_valid_signal():
    closes = [100 + 5 * math.sin(i / 4) + i * 0.3 for i in range(80)]
    ctx = _ctx(closes)
    for name in ("trend", "mean_reversion", "breakout", "hybrid"):
        s = registry.create(name).evaluate(ctx)
        assert s.action in ("BUY", "SELL", "HOLD")
        assert 0.0 <= s.confidence <= 1.0
        assert s.strategy == name


def test_trend_holds_in_choppy_low_adx():
    # Duz/yatay seri -> dusuk ADX -> trend stratejisi HOLD
    closes = [100 + (1 if i % 2 else -1) for i in range(80)]
    s = registry.create("trend").evaluate(_ctx(closes))
    assert s.action == "HOLD"


def test_manager_weights_normalize_and_allocate():
    m = StrategyManager.from_config([
        {"name": "trend", "weight": 3.0},
        {"name": "mean_reversion", "weight": 1.0},
    ])
    w = m.normalized_weights()
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert abs(w["trend"] - 0.75) < 1e-9
    assert abs(m.capital_for("trend", 1000.0) - 750.0) < 1e-6


def test_manager_runs_all_enabled_and_tags():
    m = StrategyManager.from_config([
        {"name": "trend", "weight": 1.0},
        {"name": "mean_reversion", "weight": 1.0},
        {"name": "breakout", "weight": 1.0, "enabled": False},
    ])
    closes = [100 + i * 0.5 for i in range(80)]

    def factory(name, cash):
        return _ctx(closes, cash=cash)

    sigs = m.evaluate(factory, total_equity=3000.0)
    names = {s.strategy for s in sigs}
    assert names == {"trend", "mean_reversion"}  # breakout devre disi
    assert "breakout" not in m.active_names()
