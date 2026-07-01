"""strategy.config — coklu-strateji manager kurulumu (yeni dosya adi: mount cache busted)."""
from engine.strategy.config import default_manager, parse_strategies


def test_parse_strategies_basic():
    cfg = parse_strategies("hybrid:1, trend:0.5, mean_reversion")
    assert [c["name"] for c in cfg] == ["hybrid", "trend", "mean_reversion"]
    assert cfg[1]["weight"] == 0.5
    assert cfg[2]["weight"] == 1.0


def test_parse_skips_unknown():
    cfg = parse_strategies("hybrid:1, bogus:2, trend:1")
    assert [c["name"] for c in cfg] == ["hybrid", "trend"]


def test_default_manager_env_override(monkeypatch):
    monkeypatch.setenv("STRATEGIES", "trend:1, mean_reversion:1")
    m = default_manager()
    assert set(m.active_names()) == {"trend", "mean_reversion"}


def test_default_manager_fallback_multi(monkeypatch):
    monkeypatch.delenv("STRATEGIES", raising=False)
    m = default_manager()
    assert set(m.active_names()) == {"hybrid", "trend", "mean_reversion", "breakout"}
