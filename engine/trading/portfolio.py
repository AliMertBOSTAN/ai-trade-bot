"""Portfoy: nakit, pozisyonlar, PnL ve mark-to-market.

Varsayilan LONG-ONLY (spot DEX). allow_short=True ile cift-yonlu (short) destegi
acilir; bu yalnizca backtest/simulasyon ve perp icindir (spot DEX'te short yapilamaz).
Short modda pozisyon amount'u NEGATIF olabilir; equity = nakit + sum(amount*last_price)
formulu her iki yonu de dogru degerler (short acarken alinan nakit, negatif pozisyon
degerini denkler).
"""
from __future__ import annotations

from engine.models import Position, TradeOrder


class Portfolio:
    def __init__(self, starting_cash_usd: float, allow_short: bool = False):
        self.cash_usd = starting_cash_usd
        self.positions: dict[str, Position] = {}
        self.realized_pnl_usd = 0.0
        self.allow_short = allow_short

    def apply_fill(self, order: TradeOrder) -> float:
        """Dolan emri portfoye uygular. Gerceklesen PnL doner."""
        key = f"{order.chain_id}:{order.base}"
        price = order.filled_price or order.price
        if self.allow_short:
            return self._apply_bidirectional(order, key, price)
        return self._apply_long_only(order, key, price)

    # ---- LONG-ONLY (mevcut davranis, DEGISMEDEN) ----
    def _apply_long_only(self, order: TradeOrder, key: str, price: float) -> float:
        realized = 0.0
        if order.side == "BUY":
            cost = order.amount * price + order.fee_usd
            self.cash_usd -= cost
            pos = self.positions.get(key)
            if pos is None:
                self.positions[key] = Position(
                    chain_id=order.chain_id, base=order.base, quote=order.quote,
                    amount=order.amount, avg_entry=price, last_price=price,
                    dex=order.dex, opened_ts=order.timestamp)
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

    # ---- CIFT-YONLU (short destekli) ----
    def _apply_bidirectional(self, order: TradeOrder, key: str, price: float) -> float:
        amt = order.amount
        fee = order.fee_usd
        signed = amt if order.side == "BUY" else -amt   # pozisyon degisimi (long+/short-)
        pos = self.positions.get(key)
        cur = pos.amount if pos else 0.0                # mevcut imzali miktar

        # nakit akisi: BUY oder, SELL alir; ucret her zaman dusulur
        self.cash_usd -= fee
        self.cash_usd += (-amt * price) if order.side == "BUY" else (amt * price)

        realized = 0.0
        if pos is None or cur == 0.0:
            # yeni pozisyon (long veya short)
            self.positions[key] = Position(
                chain_id=order.chain_id, base=order.base, quote=order.quote,
                amount=signed, avg_entry=price, last_price=price,
                dex=order.dex, opened_ts=order.timestamp)
            return 0.0

        same_dir = (cur > 0) == (signed > 0)
        if same_dir:
            # pozisyonu ARTIR (avg_entry guncelle)
            total = cur + signed
            pos.avg_entry = (pos.avg_entry * abs(cur) + price * abs(signed)) / abs(total)
            pos.amount = total
            pos.last_price = price
        else:
            # pozisyonu AZALT / KAPAT / TERS CEVIR
            closed = min(abs(signed), abs(cur))
            if cur > 0:        # long kapatiliyor (SELL)
                realized = (price - pos.avg_entry) * closed
            else:              # short kapatiliyor (BUY)
                realized = (pos.avg_entry - price) * closed
            self.realized_pnl_usd += realized
            pos.realized_pnl_usd += realized
            new_amt = cur + signed
            if abs(new_amt) <= 1e-12:
                del self.positions[key]
            elif (new_amt > 0) != (cur > 0):
                # ters cevirdi: kalan miktar yeni yonde, giris = mevcut fiyat
                pos.amount = new_amt
                pos.avg_entry = price
                pos.last_price = price
            else:
                pos.amount = new_amt
                pos.last_price = price
        return realized

    def mark(self, prices: dict[str, float]) -> None:
        """prices: 'chainId:base' -> price. Unrealized PnL gunceller (long+/short-)."""
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

    def to_persist(self) -> dict:
        return {
            "cash_usd": self.cash_usd,
            "realized_pnl_usd": self.realized_pnl_usd,
            "positions": [
                {
                    "chain_id": p.chain_id, "base": p.base, "quote": p.quote,
                    "amount": p.amount, "avg_entry": p.avg_entry,
                    "realized_pnl_usd": p.realized_pnl_usd, "last_price": p.last_price,
                    "dex": p.dex, "opened_ts": p.opened_ts,
                }
                for p in self.positions.values()
            ],
        }

    def load_persist(self, data: dict) -> None:
        self.cash_usd = float(data.get("cash_usd", self.cash_usd))
        self.realized_pnl_usd = float(data.get("realized_pnl_usd", 0.0))
        self.positions = {}
        for pd in data.get("positions", []):
            pos = Position(
                chain_id=int(pd["chain_id"]), base=str(pd["base"]),
                quote=str(pd.get("quote", "USD")), amount=float(pd["amount"]),
                avg_entry=float(pd["avg_entry"]),
                realized_pnl_usd=float(pd.get("realized_pnl_usd", 0.0)),
                last_price=float(pd.get("last_price", pd["avg_entry"])),
                dex=str(pd.get("dex", "")),
                opened_ts=int(pd.get("opened_ts", 0)),
            )
            self.positions[pos.key] = pos
