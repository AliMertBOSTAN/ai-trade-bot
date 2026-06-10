"""Paper (simülasyon) broker.

Gerçek zincire dokunmaz. Emirleri anlık fiyatla, gerçekçi bir slippage ve
fee modeliyle doldurur. Aynı arayüzü live broker ile paylaşır.
"""
from __future__ import annotations

from engine.config.settings import RiskConfig
from engine.models import TradeOrder
from engine.trading.portfolio import Portfolio

# DEX swap fee yaklaşığı (v2 %0.3 / v3 %0.05-1). Sabit konservatif değer.
TAKER_FEE_PCT = 0.003


class PaperBroker:
    mode = "paper"

    def __init__(self, portfolio: Portfolio, risk: RiskConfig):
        self.portfolio = portfolio
        self.risk = risk

    def execute(self, order: TradeOrder) -> TradeOrder:
        slippage = self.risk.slippage_bps / 10_000.0
        # alışta fiyat yukarı, satışta aşağı kayar (olumsuz senaryo)
        if order.side == "BUY":
            fill = order.price * (1 + slippage)
        else:
            fill = order.price * (1 - slippage)

        notional = order.amount * fill
        order.filled_price = fill
        order.fee_usd = notional * TAKER_FEE_PCT
        order.status = "filled"
        order.tx_hash = "PAPER"
        self.portfolio.apply_fill(order)
        return order
