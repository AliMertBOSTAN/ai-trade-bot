"""Paper modu ETH tohumlama + reset testleri."""
import os


def _bot(tmp_path, monkeypatch, seed="100"):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("PAPER_SEED_USD", seed)
    # settings/orchestrator'i taze yukle
    import importlib
    import engine.config.settings as st
    importlib.reload(st)
    import engine.bot.orchestrator as orch
    importlib.reload(orch)
    return orch.TradingBot()


def test_seed_pending_on_fresh_paper(tmp_path, monkeypatch):
    b = _bot(tmp_path, monkeypatch)
    assert b._seed_pending is True
    assert b.portfolio.cash_usd == 100.0


def test_seed_converts_cash_to_eth(tmp_path, monkeypatch):
    b = _bot(tmp_path, monkeypatch)
    b._maybe_seed({"1:WETH": 2500.0})
    snap = b.portfolio.snapshot()
    assert abs(snap["equity_usd"] - 100.0) < 1e-6
    assert abs(snap["cash_usd"]) < 1e-6
    pos = snap["positions"][0]
    assert pos["base"] == "WETH"
    assert abs(pos["amount"] - 0.04) < 1e-9
    assert pos["dex"] == "seed"


def test_seed_idempotent(tmp_path, monkeypatch):
    b = _bot(tmp_path, monkeypatch)
    b._maybe_seed({"1:WETH": 2500.0})
    b._maybe_seed({"1:WETH": 3000.0})
    assert len(b.portfolio.snapshot()["positions"]) == 1
    assert b._seed_pending is False




def test_seed_disabled_when_zero(tmp_path, monkeypatch):
    b = _bot(tmp_path, monkeypatch, seed="0")
    assert b._seed_pending is False


def test_reset_paper_rearms_seed(tmp_path, monkeypatch):
    b = _bot(tmp_path, monkeypatch)
    b._maybe_seed({"1:WETH": 2500.0})
    # şimdi sıfırla
    r = b.reset_paper()
    assert r["ok"] is True
    assert b._seed_pending is True
    assert b.portfolio.cash_usd == 100.0
    assert len(b.portfolio.positions) == 0
