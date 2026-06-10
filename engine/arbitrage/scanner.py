"""Arbitraj tarayıcı.

Aynı base token'ın farklı zincir/DEX fiyatlarını karşılaştırır.
En ucuz alış ile en pahalı satış arasındaki spread'i bulur, gas + slippage
maliyetlerini düşerek NET kâr tahmini üretir. Sadece eşik üstü fırsatlar döner.
"""
from __future__ import annotations

from collections import defaultdict

from engine.config.settings import RiskConfig
from engine.models import ArbitrageOpportunity, PriceQuote

# Zincir başına tek-bacak gas maliyeti tahmini (USD). Gerçekte canlı gas
# oracle'dan çekilir; burada konservatif sabitler kullanıyoruz.
GAS_COST_USD = {1: 18.0, 42161: 0.25, 8453: 0.10, 10: 0.15, 56: 0.30, 137: 0.02}


def _gas(chain_id: int) -> float:
    return GAS_COST_USD.get(chain_id, 1.0)


def scan_arbitrage(quotes: list[PriceQuote], risk: RiskConfig,
                   notional_usd: float = 1000.0) -> list[ArbitrageOpportunity]:
    by_base: dict[str, list[PriceQuote]] = defaultdict(list)
    for q in quotes:
        by_base[q.base].append(q)

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
        gas_cost = _gas(buy.chain_id) + _gas(sell.chain_id)
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
