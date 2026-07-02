"""LLM danışman katmanı sağlamlık testleri (ağ gerektirmez)."""
from __future__ import annotations

from engine.signals.llm import _parse, _validate, complete


def test_validate_normalizes_good_advice():
    a = _validate({"action": "buy", "confidence": "0.8", "rationale": "x" * 500})
    assert a == {"action": "BUY", "confidence": 0.8, "rationale": "x" * 300}


def test_validate_rejects_bad_action():
    assert _validate({"action": "YOLO", "confidence": 0.9}) is None
    assert _validate({"confidence": 0.9}) is None
    assert _validate(None) is None
    assert _validate("BUY") is None


def test_validate_clamps_confidence():
    assert _validate({"action": "SELL", "confidence": 7})["confidence"] == 1.0
    assert _validate({"action": "SELL", "confidence": -3})["confidence"] == 0.0
    assert _validate({"action": "HOLD", "confidence": "bozuk"})["confidence"] == 0.5


def test_parse_extracts_json_from_noise():
    txt = 'Elbette! İşte karar:\n```json\n{"action":"HOLD","confidence":0.6,"rationale":"nötr"}\n``` umarım yardımcı olur'
    d = _parse(txt)
    assert d and d["action"] == "HOLD"


def test_complete_without_keys_returns_none(monkeypatch):
    """API anahtarı yokken LLM katmanı sessizce None dönmeli (fail-safe)."""
    import importlib
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    import engine.config.settings as st
    importlib.reload(st)
    import engine.signals.llm as llm
    importlib.reload(llm)
    assert llm.complete("sys", "user") is None
