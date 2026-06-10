"""Portföy: nakit, pozisyonlar, PnL ve mark-to-market.

Hem paper hem live modda muhasebe için kullanılır (live'da on-chain bakiye
ile periyodik mutabakat yapılması önerilir).
"""
from __future__ import annotations

from engine.models import Position, TradeOrder


class Portfolio:
    def __init__(self, starting_cash_usd: float):
        self.cash_usd = starting_cash_usd
        self.positions: dict[str, Position] = {}
        self.realized_pnl_usd = 0.0

    def apply_fill(self, order: TradeOrder) -> float:
        """Dolan emri portföye uygular. Gerçekleşen PnL (SELL'de) döner."""
        key = f"{order.chain_id}:{order.base}"
        price = order.filled_price or order.price
        realized = 0.0

        if order.side == "BUY":
            cost = order.amount * price + order.fee_usd
            self.cash_usd -= cost
            pos = self.positions.get(key)
            if pos is None:
                self.positions[key] = Position(
                    chain_id=order.chain_id, base=order.base, quote=order.quote,
                    amount=order.amount, avg_entry=price, last_price=price)
            else:
                total = pos.amount + order.amount
                pos.avg_entry = (pos.avg_entry * pos.amount + price * order.amount) / total
                pos.amount = total
                pos.last_price = price
        else:  # SELL
            pos = self.positions.get(key)
            if pos is None or pos.amount <= 0:
                return 0.0
            sell_amt = min(order.amount, pos.amount)
            proceeds = sell_amt * price - order.fee_usd
            realized = (price - pos.avg_entry) * sell_amt - order.fee_usd
            self.cash_usd += proceeds
            self.realized_pnl_usd += realized
            pos.realized_pnl_usd += realized
            pos.amount -= sell_amt
            pos.last_price = price
            if pos.amount <= 1e-12:
                del self.positions[key]

        return realized

    def mark(self, prices: dict[str, float]) -> None:
        """prices: 'chainId:base' -> price. Unrealized PnL günceller."""
        for key, pos in self.positions.items():
            px = prices.get(key, pos.last_price)
            pos.last_price = px
            pos.unrealized_pnl_usd = (px - pos.avg_entry) * pos.amount

    def equity_usd(self) -> float:
        pos_val = sum(p.amount * p.last_price for p in self.positions.values())
        return self.cash_usd + pos_val

    def snapshot(self) -> dict:
        unreal = sum(p.unrealized_pnl_usd for p in self.positions.values())
        return {
            "cash_usd": self.cash_usd,
            "equity_usd": self.equity_usd(),
            "positions": [p.to_dict() for p in self.positions.values()],
            "realized_pnl_usd": self.realized_pnl_usd,
            "unrealized_pnl_usd": unreal,
        }
