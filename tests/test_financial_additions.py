"""Finansal eklentiler: ATR trailing çıkış, kısmi TP, ATR boyutlama, performans.

Kapsam:
- pnls_from_trades: işlem geçmişinden doğru PnL çıkarımı (ortalama maliyet)
- ATR trailing: kâr sonrası geri çekilmede trailing-stop tetiklenir
- Kısmi TP: hedefe ulaşınca pozisyonun yarısı satılır, kalan açık kalır
- get_performance: özet metrikleri döner
"""
from __future__ import annotations

from engine.analytics.metrics import pnls_from_trades
from engine.indicators.technical import compute_snapshot
from engine.models import TradeSignal


def _bot(tmp_path, monkeypatch, **env):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("PAPER_SEED_USD", "0")
    monkeypatch.setenv("MIN_CONFIDENCE", "0.5")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import importlib
    import engine.config.settings as st
    importlib.reload(st)
    import engine.storage.db as db
    importlib.reload(db)
    import engine.bot.orchestrator as orch
    importlib.reload(orch)
    b = orch.TradingBot()
    b.portfolio.positions.clear()
    b.portfolio.cash_usd = 10_000.0
    b.portfolio.realized_pnl_usd = 0.0
    b.rm.reset_daily()
    b._seed_pending = False
    return b


def _signal(price=100.0) -> TradeSignal:
    closes = [price * (1 + 0.001 * i) for i in range(40)]
    tech = compute_snapshot(closes)
    tech.price = price
    return TradeSignal(chain_id=1, base="WETH", quote="USDC", action="BUY",
                       confidence=0.9, technical=tech,
                       rationale="test", source="test")


def test_pnls_from_trades_avg_cost():
    trades = [
        {"chainId": 1, "base": "WETH", "side": "BUY", "amount": 1.0,
         "filledPrice": 100.0, "price": 100.0, "feeUsd": 0.0,
         "status": "filled", "timestamp": 1},
        {"chainId": 1, "base": "WETH", "side": "BUY", "amount": 1.0,
         "filledPrice": 200.0, "price": 200.0, "feeUsd": 0.0,
         "status": "filled", "timestamp": 2},
        # ort. giriş 150; 2 adet 180'den satış → pnl = (180-150)*2 = 60
        {"chainId": 1, "base": "WETH", "side": "SELL", "amount": 2.0,
         "filledPrice": 180.0, "price": 180.0, "feeUsd": 1.0,
         "status": "filled", "timestamp": 3},
    ]
    pnls = pnls_from_trades(trades)
    assert len(pnls) == 1
    assert abs(pnls[0] - 59.0) < 1e-9  # 60 - 1 ücret


def test_trailing_stop_locks_profit(tmp_path, monkeypatch):
    """Fiyat yükselip geri çekilince trailing-stop kârı kilitleyerek çıkmalı."""
    b = _bot(tmp_path, monkeypatch, EXIT_STYLE="atr")
    assert b._maybe_trade(_signal(price=100.0), prices=[], cash_usd=500.0)
    key = "1:WETH"
    st = b._exit_states.get(key)
    assert st is not None and st.atr > 0
    entry, atr = st.entry, st.atr
    # tepe: %20 yukarı (kısmi TP de tetiklenir), sonra sert geri çekilme.
    # Hareket, komisyon+slippage'ı net aşacak kadar büyük olmalı ki
    # "kâr kilitlendi" doğrulaması anlamlı olsun.
    peak = entry * 1.2
    b.portfolio.mark({key: peak})
    b._check_exits({key: peak}, prices=[])          # PARTIAL (TP1) beklenir
    assert key in b.portfolio.positions              # kalan yarı hâlâ açık
    dip = peak - 5 * atr                             # trail = tepe - 2.5*ATR üstünden düşüş
    b.portfolio.mark({key: dip})
    b._check_exits({key: dip}, prices=[])
    assert key not in b.portfolio.positions
    reasons = [t["reason"] for t in b.get_trades(10)]
    assert any("trailing-stop" in r for r in reasons)
    assert any("kısmi" in r for r in reasons)
    assert b.portfolio.realized_pnl_usd > 0          # kâr kilitlendi


def test_partial_tp_sells_half(tmp_path, monkeypatch):
    b = _bot(tmp_path, monkeypatch, EXIT_STYLE="atr")
    assert b._maybe_trade(_signal(price=100.0), prices=[], cash_usd=500.0)
    key = "1:WETH"
    st = b._exit_states[key]
    amt0 = b.portfolio.positions[key].amount
    tp = st.entry + 3.1 * st.atr
    b.portfolio.mark({key: tp})
    b._check_exits({key: tp}, prices=[])
    pos = b.portfolio.positions.get(key)
    assert pos is not None
    assert abs(pos.amount - amt0 * 0.5) / amt0 < 0.01


def test_fixed_exit_style_still_works(tmp_path, monkeypatch):
    b = _bot(tmp_path, monkeypatch, EXIT_STYLE="fixed")
    assert b._maybe_trade(_signal(price=100.0), prices=[], cash_usd=500.0)
    b.portfolio.mark({"1:WETH": 90.0})
    b._check_exits({"1:WETH": 90.0}, prices=[])
    assert "1:WETH" not in b.portfolio.positions
    assert "stop-loss" in b.get_trades(5)[0]["reason"]


def test_performance_report_shape(tmp_path, monkeypatch):
    b = _bot(tmp_path, monkeypatch)
    assert b._maybe_trade(_signal(price=100.0), prices=[], cash_usd=500.0)
    b.portfolio.mark({"1:WETH": 90.0})
    b._check_exits({"1:WETH": 90.0}, prices=[])
    p = b.get_performance()
    for k in ("sharpe", "sortino", "max_drawdown_pct", "calmar",
              "equity_usd", "open_positions", "exit_style"):
        assert k in p
    assert p["trades"] >= 1
    assert p["win_rate"] == 0.0  # tek işlem zararla kapandı
