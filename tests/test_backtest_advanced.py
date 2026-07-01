"""backtester (zengin metrik) + walk_forward testleri."""
import math

from engine.backtest.backtester import run_backtest
from engine.backtest.walk_forward import walk_forward
from engine.config.settings import RiskConfig


def _candles(n=200):
    out = []
    for i in range(n):
        c = 100 + 20 * math.sin(i / 12) + i * 0.15
        out.append({"t": i * 3600_000, "open": c, "high": c + 1,
                    "low": c - 1, "close": c, "volume": 1000.0})
    return out


def test_backtest_returns_rich_metrics():
    res = run_backtest(_candles(), "ETH", "USDC", 10000,
                       RiskConfig(min_confidence=0.3), interval="1h")
    for k in ("sharpe", "sortino", "calmar", "profit_factor",
              "expectancy_usd", "max_drawdown_pct", "num_closed_trades"):
        assert k in res
    assert res["max_drawdown_pct"] >= 0


def test_walk_forward_runs_and_reports():
    # 360 mum, 2 kat -> seg=180, %60 train=108, test=72 (>=40 gecerli)
    wf = walk_forward(_candles(360), "ETH", "USDC", 10000,
                      RiskConfig(min_confidence=0.3),
                      min_conf_grid=[0.3, 0.5, 0.7], n_folds=2, interval="1h")
    assert "folds" in wf and "robust" in wf and "total_folds" in wf
    assert wf["total_folds"] >= 1
