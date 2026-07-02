"""Yeni stratejiler (momentum, pullback, squeeze, sentiment) birim testleri."""
from __future__ import annotations

from engine.models import TechnicalSnapshot
from engine.strategy import registry
from engine.strategy.base import StrategyContext
import engine.strategy.strategies  # noqa: F401  (kayıtları yükle)


def _tech(**kw) -> TechnicalSnapshot:
    base = dict(rsi=50.0, ema_fast=100.0, ema_slow=100.0, macd=0.0,
                macd_signal=0.0, momentum=0.0, price=100.0, atr=1.0)
    base.update(kw)
    return TechnicalSnapshot(**base)


def _ctx(tech: TechnicalSnapshot, news: float = 0.0) -> StrategyContext:
    closes = [100.0] * 40
    return StrategyContext(base="WETH", quote="USDC", chain_id=1, closes=closes,
                           highs=closes, lows=closes, volumes=[0.0] * 40,
                           tech=tech, price=tech.price, cash_allocated=100.0,
                           news_score=news)


def test_new_strategies_registered():
    for name in ("momentum", "pullback", "squeeze", "sentiment"):
        assert registry.is_registered(name), name


def test_momentum_buy_and_hold():
    s = registry.create("momentum")
    strong = _tech(momentum=4.0, awesome=1.0, plus_di=30, minus_di=10, adx=30)
    assert s.evaluate(_ctx(strong)).action == "BUY"
    weak = _tech(momentum=0.2, awesome=1.0, plus_di=30, minus_di=10, adx=30)
    assert s.evaluate(_ctx(weak)).action == "HOLD"
    quiet = _tech(momentum=5.0, awesome=1.0, plus_di=30, minus_di=10, adx=10)
    assert s.evaluate(_ctx(quiet)).action == "HOLD"  # zayıf ADX kapısı


def test_pullback_buys_dip_in_uptrend():
    s = registry.create("pullback")
    dip = _tech(ema_fast=105, ema_slow=100, swing_trend=1, adx=25,
                rsi=38, bb_pct_b=30)
    assert s.evaluate(_ctx(dip)).action == "BUY"
    hot = _tech(ema_fast=105, ema_slow=100, swing_trend=1, adx=25,
                rsi=80, bb_pct_b=95)
    assert s.evaluate(_ctx(hot)).action == "SELL"     # kâr al
    broken = _tech(ema_fast=95, ema_slow=100, swing_trend=-1, adx=25, rsi=38)
    assert s.evaluate(_ctx(broken)).action == "SELL"  # yapı bozuldu
    no_dip = _tech(ema_fast=105, ema_slow=100, swing_trend=1, adx=25,
                   rsi=55, bb_pct_b=60)
    assert s.evaluate(_ctx(no_dip)).action == "HOLD"


def test_squeeze_waits_then_fires():
    s = registry.create("squeeze")
    squeezed = _tech(squeeze_on=1.0, squeeze_momentum=2.0)
    assert s.evaluate(_ctx(squeezed)).action == "HOLD"  # sıkışma sürüyor
    fired_up = _tech(squeeze_on=0.0, squeeze_momentum=2.0, macd=1.0,
                     macd_signal=0.0, supertrend_dir=1)
    r = s.evaluate(_ctx(fired_up))
    assert r.action == "BUY" and r.confidence > 0.7
    fired_dn = _tech(squeeze_on=0.0, squeeze_momentum=-2.0, macd=-1.0,
                     macd_signal=0.0, supertrend_dir=-1)
    assert s.evaluate(_ctx(fired_dn)).action == "SELL"


def test_sentiment_needs_news_and_confirmation():
    s = registry.create("sentiment")
    t_up = _tech(ema_fast=105, ema_slow=100)
    assert s.evaluate(_ctx(t_up, news=0.0)).action == "HOLD"       # haber yok
    assert s.evaluate(_ctx(t_up, news=0.6)).action == "BUY"        # haber + onay
    t_dn = _tech(ema_fast=95, ema_slow=100)
    assert s.evaluate(_ctx(t_dn, news=0.6)).action == "HOLD"       # onay yok
    assert s.evaluate(_ctx(t_dn, news=-0.6)).action == "SELL"      # negatif haber


def test_regime_fits_new_strategies():
    from engine.strategy.regime import strategy_fits_regime
    assert strategy_fits_regime("momentum", "trend_up")
    assert not strategy_fits_regime("momentum", "range")
    assert strategy_fits_regime("pullback", "trend_up")
    assert not strategy_fits_regime("pullback", "trend_down")
    assert strategy_fits_regime("squeeze", "range")
    assert strategy_fits_regime("sentiment", "trend_down")


def test_presets_include_new_strategies(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("PAPER_SEED_USD", "0")
    import importlib
    import engine.config.settings as st
    importlib.reload(st)
    import engine.storage.db as db
    importlib.reload(db)
    import engine.bot.orchestrator as orch
    importlib.reload(orch)
    b = orch.TradingBot()
    b.apply_preset("aggressive")
    enabled = {a.strategy.name for a in b.strategies.allocations if a.enabled}
    assert {"momentum", "squeeze", "sentiment"} <= enabled
    b.apply_preset("safe")
    enabled = {a.strategy.name for a in b.strategies.allocations if a.enabled}
    assert "pullback" in enabled and "momentum" not in enabled
