"""Strateji-yönlendirmeli işlem akışı + canlı SL/TP testleri.

Kapsam:
- Paper modda DEX fiyatı yokken pseudo-quote ile işlem simülasyonu
- Strateji sermaye dilimi (_maybe_trade cash_usd) boyutlamayı sınırlar
- Stop-loss / take-profit artık CANLI döngüde de tetiklenir (_check_exits)
- Günlük gerçekleşen PnL DELTA olarak kaydedilir (kümülatif çift sayım yok)
"""
from __future__ import annotations

from engine.indicators.technical import compute_snapshot
from engine.models import TradeSignal


def _bot(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("PAPER_SEED_USD", "0")
    monkeypatch.setenv("MIN_CONFIDENCE", "0.5")
    import importlib
    import engine.config.settings as st
    importlib.reload(st)
    # store singleton'ı da taze DATA_DIR ile yeniden kur (test izolasyonu)
    import engine.storage.db as db
    importlib.reload(db)
    import engine.bot.orchestrator as orch
    importlib.reload(orch)
    b = orch.TradingBot()
    # Deterministik başlangıç: store/module leak'lerinden bağımsız temiz portföy.
    b.portfolio.positions.clear()
    b.portfolio.cash_usd = 10_000.0
    b.portfolio.realized_pnl_usd = 0.0
    b.rm.reset_daily()
    b._seed_pending = False
    return b


def _signal(action="BUY", conf=0.9, price=100.0) -> TradeSignal:
    closes = [price * (1 + 0.001 * i) for i in range(40)]
    tech = compute_snapshot(closes)
    tech.price = price
    return TradeSignal(chain_id=1, base="WETH", quote="USDC", action=action,
                       confidence=conf, technical=tech,
                       rationale="test", source="test")


def test_paper_trade_without_dex_quote(tmp_path, monkeypatch):
    """RPC/DEX fiyatı olmadan paper modda pseudo-quote ile işlem açılmalı."""
    b = _bot(tmp_path, monkeypatch)
    filled = b._maybe_trade(_signal(), prices=[], cash_usd=500.0, strategy="trend")
    assert filled is True
    assert "1:WETH" in b.portfolio.positions
    trade = b.get_trades(5)[0]
    assert "strateji: trend" in trade["reason"]


def test_cash_slice_caps_position_size(tmp_path, monkeypatch):
    """Stratejiye tahsis edilen dilim, pozisyon boyutunu sınırlamalı."""
    b = _bot(tmp_path, monkeypatch)
    b._maybe_trade(_signal(price=100.0), prices=[], cash_usd=50.0, strategy="trend")
    pos = b.portfolio.positions.get("1:WETH")
    assert pos is not None
    assert pos.amount * 100.0 <= 50.0 + 1e-6


def test_live_stop_loss_exit(tmp_path, monkeypatch):
    """Fiyat stop-loss altına inince _check_exits pozisyonu kapatmalı."""
    b = _bot(tmp_path, monkeypatch)
    assert b._maybe_trade(_signal(price=100.0), prices=[], cash_usd=500.0)
    assert "1:WETH" in b.portfolio.positions
    # %5 stop → fiyat 90'a düşsün
    b.portfolio.mark({"1:WETH": 90.0})
    b._check_exits({"1:WETH": 90.0}, prices=[])
    assert "1:WETH" not in b.portfolio.positions
    trade = b.get_trades(5)[0]
    assert trade["side"] == "SELL"
    assert "stop-loss" in trade["reason"]


def test_daily_pnl_recorded_as_delta(tmp_path, monkeypatch):
    """İki ayrı zararlı satışta günlük sayaç toplam zarara eşit olmalı."""
    b = _bot(tmp_path, monkeypatch)
    for base_price, exit_price in ((100.0, 90.0), (100.0, 90.0)):
        b._maybe_trade(_signal(price=base_price), prices=[], cash_usd=200.0)
        b.portfolio.mark({"1:WETH": exit_price})
        b._check_exits({"1:WETH": exit_price}, prices=[])
    total_realized = b.portfolio.realized_pnl_usd
    assert abs(b.rm.day_realized_pnl - total_realized) < 1e-6


def test_disabled_strategy_not_in_router(tmp_path, monkeypatch):
    """Kapatılan strateji rejim yönlendiricide görünmemeli."""
    from engine.strategy.router import select_active
    b = _bot(tmp_path, monkeypatch)
    b.set_strategy("trend", enabled=False)
    tech = compute_snapshot([100.0 + i for i in range(40)])
    _regime, weights = select_active(b.strategies, tech)
    assert "trend" not in weights
