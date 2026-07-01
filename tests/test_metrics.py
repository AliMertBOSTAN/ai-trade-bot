"""analytics.metrics — risk-ayarli metrik testleri."""
import math

from engine.analytics import metrics as m


def test_max_drawdown_simple():
    eq = [100, 120, 90, 110]  # tepe 120 -> dip 90 = %25
    assert abs(m.max_drawdown(eq) - 0.25) < 1e-9


def test_sharpe_zero_for_flat():
    assert m.sharpe([0.0, 0.0, 0.0]) == 0.0


def test_sharpe_positive_for_steady_gains():
    rets = [0.01] * 50
    # sabit getiride std=0 -> 0 (tanim geregi); kucuk gurultu ekleyince pozitif
    rets = [0.01 + (0.001 if i % 2 else -0.001) for i in range(50)]
    assert m.sharpe(rets) > 0


def test_trade_stats():
    pnls = [10, -5, 20, -10, 5]
    s = m.trade_stats(pnls)
    assert s["trades"] == 5
    assert abs(s["win_rate"] - 0.6) < 1e-9
    assert abs(s["profit_factor"] - (35 / 15)) < 1e-6
    assert abs(s["expectancy"] - 4.0) < 1e-9


def test_summarize_keys():
    eq = [100, 101, 103, 102, 105]
    out = m.summarize(eq, trade_pnls=[5, -2, 3])
    for k in ("sharpe", "sortino", "max_drawdown_pct", "calmar",
              "win_rate", "profit_factor", "expectancy_usd", "total_return_pct"):
        assert k in out


def test_sortino_only_penalizes_downside():
    rets = [0.02, 0.02, -0.01, 0.02, -0.01]
    assert m.sortino(rets) > m.sharpe(rets) or m.sortino(rets) > 0
