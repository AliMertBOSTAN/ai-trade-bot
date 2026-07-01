"""#4-#10 finansal modul testleri: regime, exits, execution, edge, cross-chain, portfolio."""
import math

from engine.models import TechnicalSnapshot


def _tech(**kw):
    base = dict(rsi=50, ema_fast=1.0, ema_slow=1.0, macd=0, macd_signal=0,
                momentum=0, price=100.0)
    base.update(kw)
    return TechnicalSnapshot(**base)


# ---- #4 regime ----
def test_regime_detection():
    from engine.strategy.regime import detect_regime
    assert detect_regime(_tech(adx=30, ema_fast=2, ema_slow=1)) == "trend_up"
    assert detect_regime(_tech(adx=30, ema_fast=1, ema_slow=2)) == "trend_down"
    assert detect_regime(_tech(adx=10)) == "range"


def test_cooldown():
    from engine.strategy.regime import Cooldown
    cd = Cooldown(seconds=100)
    assert cd.ready("ETH", now=0)
    cd.mark("ETH", now=0)
    assert not cd.ready("ETH", now=50)
    assert cd.ready("ETH", now=100)


def test_mtf_confirm():
    from engine.strategy.regime import mtf_confirm
    up = _tech(ema_fast=2, ema_slow=1, supertrend_dir=1)
    assert mtf_confirm("BUY", up)
    assert not mtf_confirm("SELL", up)
    assert mtf_confirm("HOLD", up)


# ---- #5 exits ----
def test_exit_stop_and_trailing():
    from engine.trading.exits import ExitConfig, ExitManager, ExitState
    em = ExitManager(ExitConfig(atr_stop_mult=2, trail_mult=2, take_profit_atr=3,
                                breakeven_atr=1))
    st = ExitState(entry=100, atr=2)
    # fiyat dususe gecince stop
    d = em.update(st, 95)  # stop = 100-4 = 96 -> 95 <= 96 EXIT
    assert d.action == "EXIT"


def test_exit_partial_tp():
    from engine.trading.exits import ExitConfig, ExitManager, ExitState
    em = ExitManager(ExitConfig(take_profit_atr=3, partial_tp_fraction=0.5))
    st = ExitState(entry=100, atr=2)
    d = em.update(st, 107)  # 100 + 3*2 = 106 -> 107 PARTIAL
    assert d.action == "PARTIAL" and abs(d.fraction - 0.5) < 1e-9


# ---- #6 execution ----
def test_best_route_picks_cheapest():
    from engine.dex.execution import Quote, best_route
    qs = [Quote("a", 1, 100.0, fee_pct=0.003, liquidity_usd=1_000_000),
          Quote("b", 42161, 100.0, fee_pct=0.003, liquidity_usd=1_000_000)]
    q, cost = best_route(qs, 1000)
    assert q.dex in ("a", "b") and cost > 0


def test_depth_slippage_monotonic():
    from engine.dex.execution import depth_slippage_bps
    assert depth_slippage_bps(10000, 1_000_000) < depth_slippage_bps(100000, 1_000_000)


def test_twap_slices():
    from engine.dex.execution import twap_slices
    s = twap_slices(1000, 4)
    assert len(s) == 4 and abs(sum(s) - 1000) < 1e-6
    assert twap_slices(10, 4, min_slice_usd=25) == [10]  # cok kucuk bolme


# ---- #7 edge gate ----
def test_edge_gate_rejects_uneconomic():
    from engine.trading.edge_gate import evaluate_edge
    r = evaluate_edge(expected_move_pct=0.1, notional_usd=1000, total_cost_usd=5)
    # brut = 1$ < maliyet 5$ -> red
    assert not r.ok


def test_edge_gate_accepts_good():
    from engine.trading.edge_gate import evaluate_edge
    r = evaluate_edge(expected_move_pct=2.0, notional_usd=1000, total_cost_usd=5)
    assert r.ok and r.net_edge_usd > 0


def test_promotion_criteria():
    from engine.trading.edge_gate import evaluate_promotion
    bad = evaluate_promotion({"trades": 5, "sharpe": 0.2})
    assert not bad.ready and bad.reasons
    good = evaluate_promotion({"trades": 50, "sharpe": 1.5, "win_rate": 0.55,
                               "profit_factor": 1.5, "expectancy_usd": 3.0,
                               "max_drawdown_pct": 10.0})
    assert good.ready


# ---- #8 funding arb ----
def test_funding_arb_strategy():
    from engine.strategy.base import StrategyContext
    from engine.strategy.registry import create
    import engine.strategy.strategies  # noqa
    closes = [100.0] * 60
    ctx = StrategyContext(base="ETH", quote="USDC", chain_id=1, closes=closes,
                          highs=closes, lows=closes, volumes=[1.0] * 60,
                          tech=_tech(), price=100.0, funding_pct=0.05)
    s = create("funding_arb").evaluate(ctx)
    assert s.action == "BUY"  # guclu pozitif funding -> spot long
    ctx.funding_pct = None
    assert create("funding_arb").evaluate(ctx).action == "HOLD"


# ---- #9 cross-chain ----
def test_cross_chain_costs_kill_thin_spread():
    from engine.arbitrage.cross_chain import evaluate
    # %0.1 spread, 1000$ -> brut ~1$; kopru+gas bunu yer -> red
    r = evaluate(1000, buy_price=100, sell_price=100.1, buy_chain=1, sell_chain=42161)
    assert not r.profitable
    assert r.total_cost_usd > 0


def test_cross_chain_big_spread_profits():
    from engine.arbitrage.cross_chain import evaluate
    r = evaluate(1000, buy_price=100, sell_price=105, buy_chain=42161, sell_chain=8453)
    assert r.profitable and r.net_profit_usd > 0


# ---- #10 portfolio risk ----
def test_correlation():
    from engine.risk.portfolio_risk import correlation
    a = [1, 2, 3, 4]
    assert abs(correlation(a, a) - 1.0) < 1e-9
    assert abs(correlation(a, [4, 3, 2, 1]) + 1.0) < 1e-9


def test_drawdown_derisk():
    from engine.risk.portfolio_risk import drawdown_derisk_factor
    assert drawdown_derisk_factor(5) == 1.0
    assert drawdown_derisk_factor(25) == 0.0
    assert 0 < drawdown_derisk_factor(17.5) < 1


def test_vol_target():
    from engine.risk.portfolio_risk import vol_target_scale
    assert vol_target_scale(0.10, 0.20, max_scale=1.5) == 1.5  # dusuk vol -> buyut (sinirli)
    assert vol_target_scale(0.40, 0.20) == 0.5                 # yuksek vol -> kucult
