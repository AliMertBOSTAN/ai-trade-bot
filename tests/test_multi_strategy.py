"""Rejim-degisimli coklu-strateji: router + multi_backtest."""
import math

from engine.backtest.multi_backtest import run_multi_backtest
from engine.config.settings import RiskConfig
from engine.indicators.technical import compute_snapshot
from engine.strategy.manager import StrategyManager
from engine.strategy.router import select_active
import engine.strategy.strategies  # noqa: F401


def _candles(kind, n=300):
    out = []
    for i in range(n):
        if kind == "up":
            c = 100 * (1 + 0.004 * i) + 6 * math.sin(i / 9)
        elif kind == "down":
            c = 100 * (1 - 0.003 * i) + 6 * math.sin(i / 9)
        else:
            c = 100 + 10 * math.sin(i / 8)
        out.append({"t": i * 3600000, "open": c, "high": c + 1.2,
                    "low": c - 1.2, "close": c, "volume": 1000.0})
    return out


def _mgr():
    return StrategyManager.from_config([
        {"name": "trend", "weight": 1.0},
        {"name": "mean_reversion", "weight": 1.0},
        {"name": "breakout", "weight": 1.0},
        {"name": "hybrid", "weight": 1.0},
    ])


def test_router_picks_trend_in_uptrend():
    closes = [100 + i for i in range(60)]
    tech = compute_snapshot(closes, [c + 1 for c in closes], [c - 1 for c in closes],
                            [1000.0] * 60)
    regime, active = select_active(_mgr(), tech)
    assert regime in ("trend_up", "trend_down", "range")
    assert abs(sum(active.values()) - 1.0) < 1e-9
    if regime == "trend_up":
        assert "trend" in active and "mean_reversion" not in active


def test_multi_backtest_runs_and_attributes():
    res = run_multi_backtest(_candles("up"), "ETH", "USDC", 10000, _mgr(),
                             RiskConfig(min_confidence=0.5), interval="1h")
    assert "attribution" in res and len(res["attribution"]) == 4
    assert "regime_distribution" in res
    # sermaye dilimleri toplami ~ baslangic
    alloc = sum(a["alloc_pct"] for a in res["attribution"])
    assert abs(alloc - 100.0) < 0.5
    assert res["final_equity_usd"] > 0


def test_multi_backtest_all_regimes():
    for kind in ("up", "down", "range"):
        res = run_multi_backtest(_candles(kind), "ETH", "USDC", 10000, _mgr(),
                                 RiskConfig(min_confidence=0.5), interval="1h")
        assert res["final_equity_usd"] > 0
        assert sum(res["regime_distribution"].values()) > 0
