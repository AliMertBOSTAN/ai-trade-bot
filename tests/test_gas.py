"""dex/gas — gas maliyet tahmincisi testleri (statik fallback, ağ yok)."""
from engine.dex import gas


def test_gas_cost_positive_and_finite():
    cost = gas.gas_cost_usd(1, gas.GAS_UNITS_SWAP)
    assert cost > 0
    assert cost < 10_000  # makul üst sınır (saçma değer değil)


def test_more_units_costs_more():
    low = gas.gas_cost_usd(1, gas.GAS_UNITS_SWAP)
    high = gas.gas_cost_usd(1, gas.GAS_UNITS_SWAP * 3)
    assert high > low


def test_l2_cheaper_than_mainnet():
    # Arbitrum (42161) tipik olarak Ethereum (1) mainnet'ten ucuz olmalı
    eth = gas.gas_cost_usd(1, gas.GAS_UNITS_SWAP)
    arb = gas.gas_cost_usd(42161, gas.GAS_UNITS_SWAP)
    assert arb <= eth


def test_max_gas_fraction_sane():
    assert 0 < gas.MAX_GAS_FRACTION <= 1
