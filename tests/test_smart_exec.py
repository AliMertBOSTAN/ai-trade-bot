"""Akıllı yürütme + portföy-riski karar yolu testleri."""
from dataclasses import dataclass

from engine.trading import smart_exec
from engine.risk import portfolio_risk as pr
from engine.dex import execution as ex


@dataclass
class FakeQuote:
    chain_id: int
    dex: str
    price: float
    liquidity_usd: float


def test_best_route_prefers_deeper_pool():
    # ayni fiyat, daha derin havuz daha dusuk slippage -> secilmeli
    cands = [FakeQuote(1, "shallow", 100.0, 50_000),
             FakeQuote(1, "deep", 100.0, 5_000_000)]
    plan = smart_exec.plan_execution(cands, 20_000, "BUY", 10_000, 10_000)
    assert plan is not None
    assert plan.dex == "deep"


def test_drawdown_scales_size_down():
    cands = [FakeQuote(1, "d", 100.0, 1_000_000)]
    # tepe 10000, simdi 8000 -> %20 drawdown (soft=10 hard=25 arasi) -> kucultme
    plan = smart_exec.plan_execution(cands, 1000, "BUY", 8000, 10000)
    assert plan.derisk_factor < 1.0
    assert plan.size_usd < 1000


def test_no_drawdown_full_size():
    cands = [FakeQuote(1, "d", 100.0, 1_000_000)]
    plan = smart_exec.plan_execution(cands, 1000, "BUY", 10000, 10000)
    assert plan.derisk_factor == 1.0
    assert plan.size_usd == 1000


def test_twap_slicing_large_order():
    cands = [FakeQuote(1, "d", 100.0, 100_000_000)]
    plan = smart_exec.plan_execution(cands, 20_000, "BUY", 100_000, 100_000,
                                     twap_threshold_usd=5000, twap_slices=4)
    assert len(plan.slices) > 1
    assert abs(sum(plan.slices) - plan.size_usd) < 1e-6


def test_empty_candidates_returns_none():
    assert smart_exec.plan_execution([], 1000, "BUY", 10000, 10000) is None


def test_hard_drawdown_zero_factor():
    cands = [FakeQuote(1, "d", 100.0, 1_000_000)]
    # %30 drawdown > hard(25) -> factor 0
    plan = smart_exec.plan_execution(cands, 1000, "BUY", 7000, 10000)
    assert plan.derisk_factor == 0.0
    assert plan.size_usd == 0.0


def test_portfolio_risk_units():
    assert pr.drawdown_derisk_factor(5) == 1.0
    assert pr.drawdown_derisk_factor(30) == 0.0
    assert 0 < pr.drawdown_derisk_factor(17) < 1
    assert pr.correlation([1, 2, 3], [1, 2, 3]) > 0.99
    assert pr.exposure_by([{"base": "ETH", "notional_usd": 100},
                           {"base": "ETH", "notional_usd": 50}], "base")["ETH"] == 150
