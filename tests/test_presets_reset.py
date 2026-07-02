"""Strateji profilleri (preset) + giriş eşiği + esnek paper sıfırlama testleri."""
from __future__ import annotations


def _bot(tmp_path, monkeypatch):
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
    b.portfolio.positions.clear()
    b.portfolio.cash_usd = 10_000.0
    b.portfolio.realized_pnl_usd = 0.0
    b._seed_pending = False
    return b


def test_apply_preset_sets_weights_and_threshold(tmp_path, monkeypatch):
    b = _bot(tmp_path, monkeypatch)
    r = b.apply_preset("aggressive")
    assert r["ok"] is True
    assert b._preset == "aggressive"
    assert abs(b.risk.min_confidence - 0.62) < 1e-9
    assert b.rm.risk.min_confidence == b.risk.min_confidence
    weights = {a.strategy.name: a.weight for a in b.strategies.allocations}
    assert weights["breakout"] == 1.5

    r = b.apply_preset("safe")
    assert abs(b.risk.min_confidence - 0.80) < 1e-9
    enabled = {a.strategy.name: a.enabled for a in b.strategies.allocations}
    assert enabled["breakout"] is False


def test_unknown_preset_rejected(tmp_path, monkeypatch):
    b = _bot(tmp_path, monkeypatch)
    r = b.apply_preset("yolo")
    assert r["ok"] is False


def test_min_confidence_persists_and_marks_custom(tmp_path, monkeypatch):
    b = _bot(tmp_path, monkeypatch)
    b.apply_preset("balanced")
    r = b.set_min_confidence(0.66)
    assert r["ok"] and abs(r["min_confidence"] - 0.66) < 1e-9
    assert b._preset == "custom"  # elle ayar profili özelleştirir
    # kalıcılık: risk.json'dan geri yüklenir
    b2 = _bot.__wrapped__(tmp_path, monkeypatch) if hasattr(_bot, "__wrapped__") else None
    import engine.bot.orchestrator as orch
    nb = orch.TradingBot()
    assert abs(nb.risk.min_confidence - 0.66) < 1e-9


def test_manual_strategy_change_marks_custom(tmp_path, monkeypatch):
    b = _bot(tmp_path, monkeypatch)
    b.apply_preset("balanced")
    assert b._preset == "balanced"
    b.set_strategy("trend", weight=2.0)
    assert b._preset == "custom"


def test_reset_paper_custom_amount_cash(tmp_path, monkeypatch):
    b = _bot(tmp_path, monkeypatch)
    r = b.reset_paper(seed_usd=2500.0, cash_only=True)
    assert r["ok"] is True
    assert b.portfolio.cash_usd == 2500.0
    assert b._seed_pending is False       # nakit başlangıç: tohum yok
    assert len(b.portfolio.positions) == 0
    assert r["asset"] == "USD"


def test_reset_paper_custom_amount_eth_seed(tmp_path, monkeypatch):
    b = _bot(tmp_path, monkeypatch)
    r = b.reset_paper(seed_usd=5000.0, cash_only=False)
    assert r["ok"] is True
    assert b.portfolio.cash_usd == 5000.0
    assert b._seed_pending is True        # ilk tick'te ETH'ye çevrilecek
    b._maybe_seed({"1:WETH": 2500.0})
    assert abs(b.portfolio.positions["1:WETH"].amount - 2.0) < 1e-9


def test_reset_paper_rejects_nonpositive(tmp_path, monkeypatch):
    b = _bot(tmp_path, monkeypatch)
    assert b.reset_paper(seed_usd=0)["ok"] is False
    assert b.reset_paper(seed_usd=-5)["ok"] is False
