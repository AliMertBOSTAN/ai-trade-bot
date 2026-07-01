"""risk/manager — risk kapilari (paper/live gas davranisi dahil)."""
import dataclasses

from engine.config.settings import RiskConfig, settings
from engine.models import Position, TechnicalSnapshot, TradeSignal
from engine.risk.manager import RiskManager


def _sig(action="BUY", conf=0.9, price=2000.0, chain=1, base="ETH"):
    tech = TechnicalSnapshot(rsi=50, ema_fast=1, ema_slow=1, macd=0,
                             macd_signal=0, momentum=0, price=price)
    return TradeSignal(chain_id=chain, base=base, quote="USDC", action=action,
                       confidence=conf, technical=tech, rationale="t", source="technical")


def test_hold_rejected():
    assert not RiskManager(RiskConfig()).evaluate(_sig(action="HOLD"), {}, 10000).approved


def test_low_confidence_rejected():
    d = RiskManager(RiskConfig(min_confidence=0.75)).evaluate(_sig(conf=0.5), {}, 10000)
    assert not d.approved and "Guven" in d.reason or "Güven" in d.reason


def test_kill_switch_blocks():
    rm = RiskManager(RiskConfig(max_daily_loss_usd=100))
    rm.record_realized(-150)
    assert not rm.evaluate(_sig(), {}, 10000).approved


def test_paper_mode_gas_does_not_block():
    # Paper modda (varsayilan trading_mode='paper') gas, islemi ENGELLEMEZ
    assert settings.trading_mode == "paper"
    d = RiskManager(RiskConfig()).evaluate(_sig(conf=0.9, chain=1), {}, 10000)
    assert d.approved


def test_sell_without_position_rejected():
    assert not RiskManager(RiskConfig()).evaluate(_sig(action="SELL"), {}, 10000).approved


def test_stop_take():
    rm = RiskManager(RiskConfig(stop_loss_pct=0.05, take_profit_pct=0.10))
    pos = Position(chain_id=1, base="ETH", quote="USDC", amount=1, avg_entry=100)
    assert rm.check_stop_take(pos, 94) == "stop-loss"
    assert rm.check_stop_take(pos, 111) == "take-profit"
    assert rm.check_stop_take(pos, 100) is None


def test_min_out():
    assert RiskManager(RiskConfig(slippage_bps=50)).min_out(10_000) == 9_950
