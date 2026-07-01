"""Çapraz-zincir arbitraj gerçekçiliği: köprü maliyeti/süresi + envanter.

Atomik OLMAYAN çapraz-zincir arbitrajda kâr; köprü ücreti, köprü gecikmesi
sırasındaki fiyat riski ve iki tarafta da sermaye bulundurma (envanter) gereği
nedeniyle "kâğıt spread"den çok daha düşüktür. Bu modül net kârı gerçekçi hesaplar.
"""
from __future__ import annotations

from dataclasses import dataclass

from engine.dex import gas

# Zincir başına tipik köprü çıkış maliyeti (USD, sabit yaklaşım) ve süre (saniye).
# Gerçek köprü kotasyonu varsa onunla değiştirilebilir.
_BRIDGE_FIXED_USD = 1.0
_BRIDGE_FEE_PCT = 0.0005  # %0.05
_BRIDGE_TIME_S = {
    1: 900, 42161: 120, 8453: 120, 10: 120, 56: 180, 137: 300,
}


def bridge_cost_usd(notional_usd: float) -> float:
    """Köprü toplam ücreti (sabit + oransal)."""
    return _BRIDGE_FIXED_USD + _BRIDGE_FEE_PCT * notional_usd


def bridge_time_seconds(chain_from: int, chain_to: int) -> int:
    """Köprü tahmini süresi (en yavaş ucu baz al)."""
    return max(_BRIDGE_TIME_S.get(chain_from, 600), _BRIDGE_TIME_S.get(chain_to, 600))


@dataclass
class CrossChainResult:
    profitable: bool
    gross_spread_usd: float
    net_profit_usd: float
    total_cost_usd: float
    bridge_seconds: int
    reason: str


def evaluate(notional_usd: float, buy_price: float, sell_price: float,
             buy_chain: int, sell_chain: int,
             min_net_usd: float = 5.0,
             have_inventory_both_sides: bool = False) -> CrossChainResult:
    """Çapraz-zincir arbitraj fırsatını TÜM maliyetlerle değerlendirir.

    have_inventory_both_sides=True ise köprü gecikmesi olmadan iki tarafta da
    envanter var demektir (atomik-benzeri); köprü SÜRESİ riski düşer ama yine de
    köprü ücreti envanteri yenilemek için eninde sonunda gerekir.
    """
    units = notional_usd / buy_price if buy_price > 0 else 0.0
    gross = (sell_price - buy_price) * units

    gas_buy = gas.gas_cost_usd(buy_chain, gas.GAS_UNITS_SWAP)
    gas_sell = gas.gas_cost_usd(sell_chain, gas.GAS_UNITS_SWAP)
    bridge = 0.0 if have_inventory_both_sides else bridge_cost_usd(notional_usd)
    total_cost = gas_buy + gas_sell + bridge

    net = gross - total_cost
    secs = 0 if have_inventory_both_sides else bridge_time_seconds(buy_chain, sell_chain)

    if net < min_net_usd:
        return CrossChainResult(False, gross, net, total_cost, secs,
                                f"net {net:.2f}$ < eşik {min_net_usd:.2f}$ "
                                f"(maliyet {total_cost:.2f}$ dahil)")
    return CrossChainResult(True, gross, net, total_cost, secs,
                            f"net ~{net:.2f}$ (köprü {secs}s)")
