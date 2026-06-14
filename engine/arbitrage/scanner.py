"""Arbitraj tarayıcı.

Aynı base token'ın farklı zincir/DEX fiyatlarını karşılaştırır.
En ucuz alış ile en pahalı satış arasındaki spread'i bulur, gas + slippage
maliyetlerini düşerek NET kâr tahmini üretir. Sadece eşik üstü fırsatlar döner.
"""
from __future__ import annotations

from collections import defaultdict

from engine.config.chains import CHAINS
from engine.config.settings import RiskConfig
from engine.dex import gas
from engine.models import ArbitrageOpportunity, PriceQuote


def _native_usd_map(quotes: list[PriceQuote]) -> dict[int, float]:
    """Oracle fiyatlarından zincir başına native token USD fiyatı (gas için)."""
    out: dict[int, float] = {}
    for cid, ch in CHAINS.items():
        nu = gas.native_usd_from_quotes(quotes, cid, ch.wrapped_native.symbol)
        if nu:
            out[cid] = nu
    return out


def scan_arbitrage(quotes: list[PriceQuote], risk: RiskConfig,
                   notional_usd: float = 1000.0) -> list[ArbitrageOpportunity]:
    by_base: dict[str, list[PriceQuote]] = defaultdict(list)
    for q in quotes:
        by_base[q.base].append(q)

    native_usd = _native_usd_map(quotes)
    opps: list[ArbitrageOpportunity] = []
    slippage = risk.slippage_bps / 10_000.0

    for base, qs in by_base.items():
        if len(qs) < 2:
            continue
        buy = min(qs, key=lambda x: x.price)   # en ucuz = al
        sell = max(qs, key=lambda x: x.price)  # en pahalı = sat
        if buy.price <= 0 or sell.price <= buy.price:
            continue

        # likidite, notional'ı kaldıramıyorsa notional'ı kısıtla
        usable = min(notional_usd, buy.liquidity_usd * 0.02, sell.liquidity_usd * 0.02)
        if usable < 50:
            continue

        spread_pct = (sell.price - buy.price) / buy.price

        gross = usable * spread_pct
        slippage_cost = usable * slippage * 2     # alış + satış
        # canlı gas: al bacağı + sat bacağı (native fiyat oracle'dan, yoksa fallback)
        gas_cost = (
            gas.gas_cost_usd(buy.chain_id, gas.GAS_UNITS_ARB_LEG, native_usd.get(buy.chain_id))
            + gas.gas_cost_usd(sell.chain_id, gas.GAS_UNITS_ARB_LEG, native_usd.get(sell.chain_id))
        )
        # zincirler arası ise köprü maliyeti yaklaşığı
        bridge_cost = 0.0 if buy.chain_id == sell.chain_id else usable * 0.0010
        net = gross - slippage_cost - gas_cost - bridge_cost

        if net < risk.min_arb_net_profit_usd:
            continue

        opps.append(ArbitrageOpportunity(
            base=base, quote=buy.quote,
            buy_chain=buy.chain_id, buy_dex=buy.dex, buy_price=buy.price,
            sell_chain=sell.chain_id, sell_dex=sell.dex, sell_price=sell.price,
            spread_pct=spread_pct * 100,
            est_net_profit_usd=net, notional_usd=usable,
        ))

    opps.sort(key=lambda o: o.est_net_profit_usd, reverse=True)
    return opps
