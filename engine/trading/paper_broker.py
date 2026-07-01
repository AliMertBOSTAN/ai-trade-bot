"""Paper (simülasyon) broker.

Gerçek zincire dokunmaz. Emirleri anlık fiyatla, gerçekçi bir slippage ve fee
modeliyle doldurur. Aynı arayüzü live broker ile paylaşır.
"""
from __future__ import annotations

from engine.config.settings import RiskConfig
from engine.dex import gas
from engine.models import TradeOrder
from engine.trading.portfolio import Portfolio

TAKER_FEE_PCT = 0.003


class PaperBroker:
    mode = "paper"

    def __init__(self, portfolio: Portfolio, risk: RiskConfig):
        self.portfolio = portfolio
        self.risk = risk
        # Paper modda simule nonce: zincir basina sirali sayac (gercek zincir yok).
        self._nonce: dict[int, int] = {}

    def execute(self, order: TradeOrder) -> TradeOrder:
        slippage = self.risk.slippage_bps / 10_000.0
        if order.side == "BUY":
            fill = order.price * (1 + slippage)
        else:
            fill = order.price * (1 - slippage)

        notional = order.amount * fill
        order.filled_price = fill
        swap_fee = notional * TAKER_FEE_PCT
        gas_fee = gas.gas_cost_usd(order.chain_id, gas.GAS_UNITS_SWAP)
        order.fee_usd = swap_fee + gas_fee
        if not order.reason:
            order.reason = f"swap~{swap_fee:.2f}$ + gas~{gas_fee:.2f}$"
        order.status = "filled"
        order.tx_hash = "PAPER"
        n = self._nonce.get(order.chain_id, 0)
        order.nonce = n
        self._nonce[order.chain_id] = n + 1
        self.portfolio.apply_fill(order)
        return order
