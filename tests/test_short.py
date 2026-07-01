"""Portfolio short destegi + short-aware backtest."""
import math

from engine.models import TradeOrder
from engine.trading.portfolio import Portfolio


def _order(side, amount, price, fee=0.0):
    o = TradeOrder(mode="paper", chain_id=0, dex="x", base="ETH", quote="USDC",
                   side=side, amount=amount, price=price)
    o.filled_price = price
    o.fee_usd = fee
    return o


def test_long_only_unchanged():
    pf = Portfolio(10000)  # allow_short=False
    pf.apply_fill(_order("BUY", 1, 100))
    assert pf.positions["0:ETH"].amount == 1
    r = pf.apply_fill(_order("SELL", 1, 110))
    assert abs(r - 10) < 1e-6 and not pf.positions


def test_short_open_and_cover_profit():
    pf = Portfolio(10000, allow_short=True)
    pf.apply_fill(_order("SELL", 1, 100))         # short ac
    assert pf.positions["0:ETH"].amount == -1
    assert abs(pf.cash_usd - 10100) < 1e-6        # short acinca nakit alinir
    pf.mark({"0:ETH": 90})
    assert abs(pf.equity_usd() - 10010) < 1e-6    # fiyat dustu -> short kar
    r = pf.apply_fill(_order("BUY", 1, 90))        # cover
    assert abs(r - 10) < 1e-6 and not pf.positions
    assert abs(pf.equity_usd() - 10010) < 1e-6


def test_short_loss_when_price_rises():
    pf = Portfolio(10000, allow_short=True)
    pf.apply_fill(_order("SELL", 1, 100))
    pf.mark({"0:ETH": 110})
    assert abs(pf.equity_usd() - 9990) < 1e-6     # fiyat yukseldi -> short zarar


def test_flip_long_to_short():
    pf = Portfolio(10000, allow_short=True)
    pf.apply_fill(_order("BUY", 1, 100))           # long 1
    pf.apply_fill(_order("SELL", 3, 110))          # 1 kapat + 2 short ac
    p = pf.positions["0:ETH"]
    assert abs(p.amount + 2) < 1e-6                # -2 (short)
    assert abs(p.avg_entry - 110) < 1e-6
