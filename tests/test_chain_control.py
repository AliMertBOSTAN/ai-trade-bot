"""Ağ (zincir) kullanıcı kontrolü + kalıcılık testleri."""
from engine.bot.orchestrator import TradingBot


def test_default_all_chains_active(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    b = TradingBot()
    assert b.enabled_chains == b.all_chains
    assert len(b.all_chains) >= 1


def test_set_chains_subset(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    b = TradingBot()
    b.set_chains([8453])
    assert b.enabled_chains == [8453]
    rows = {c["chain_id"]: c["active"] for c in b.get_chains()["chains"]}
    assert rows[8453] is True
    assert rows.get(1) is False


def test_set_chain_toggle(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    b = TradingBot()
    b.set_chains([8453])
    b.set_chain(42161, True)
    assert set(b.enabled_chains) == {8453, 42161}
    b.set_chain(8453, False)
    assert b.enabled_chains == [42161]


def test_invalid_chain_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    b = TradingBot()
    b.set_chains([999999, 8453])  # 999999 geçersiz
    assert b.enabled_chains == [8453]


def test_empty_selection_allowed(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    b = TradingBot()
    b.set_chains([])
    assert b.enabled_chains == []
    assert b.get_chains()["active_count"] == 0


def test_persistence(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    b = TradingBot()
    b.set_chains([42161, 56])
    b2 = TradingBot()  # ayni DATA_DIR -> kayittan okur
    assert set(b2.enabled_chains) == {42161, 56}
