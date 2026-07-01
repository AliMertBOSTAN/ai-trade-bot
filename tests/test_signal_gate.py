"""signals/engine — LLM token kapısı + kural-tabanlı karar testleri."""
from types import SimpleNamespace

from engine.signals import engine as sig


def _reset_gate():
    sig._llm_last.clear()


def test_gate_skips_hold_and_low_conf():
    _reset_gate()
    assert sig._should_consult_llm("ETH", "HOLD", 0.99) is False
    assert sig._should_consult_llm("ETH", "BUY", 0.40) is False


def test_gate_allows_strong_then_cooldown(monkeypatch):
    _reset_gate()
    # sağlayıcıyı garanti açık tut (testin determinizmi için)
    monkeypatch.setattr(sig, "settings", SimpleNamespace(llm_provider="deepseek"))
    first = sig._should_consult_llm("BTC", "BUY", 0.80)
    second = sig._should_consult_llm("BTC", "BUY", 0.80)  # cooldown
    assert first is True
    assert second is False
    assert sig._should_consult_llm("BTC", "SELL", 0.80) is True  # farklı aksiyon


def test_gate_respects_provider_none(monkeypatch):
    _reset_gate()
    monkeypatch.setattr(sig, "settings", SimpleNamespace(llm_provider="none"))
    assert sig._should_consult_llm("ETH", "BUY", 0.95) is False


def test_rule_decision_returns_valid_action():
    from engine.indicators.technical import compute_snapshot
    closes = [100 + i for i in range(60)]
    snap = compute_snapshot(closes)
    action, conf = sig._rule_decision(snap)
    assert action in ("BUY", "SELL", "HOLD")
    assert 0.0 <= conf <= 1.0
