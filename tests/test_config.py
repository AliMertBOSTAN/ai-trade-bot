"""config/settings — baslangic dogrulama (fail-fast) testleri."""
import dataclasses

import pytest

from engine.config.settings import RiskConfig, Settings


def _mk(**over):
    return dataclasses.replace(Settings(), **over)


def test_valid_default_has_no_errors():
    errors, _ = Settings().validate()
    assert errors == []


def test_invalid_mode_is_error():
    errors, _ = _mk(trading_mode="banana").validate()
    assert any("TRADING_MODE" in e for e in errors)


def test_invalid_provider_is_error():
    errors, _ = _mk(llm_provider="madeup").validate()
    assert any("LLM_PROVIDER" in e for e in errors)


def test_nonpositive_cash_is_error():
    errors, _ = _mk(starting_cash_usd=0).validate()
    assert any("STARTING_CASH_USD" in e for e in errors)


def test_bad_min_confidence_is_error():
    errors, _ = _mk(risk=RiskConfig(min_confidence=1.5)).validate()
    assert any("min_confidence" in e for e in errors)


def test_live_without_wallet_is_error():
    errors, _ = _mk(trading_mode="live", wallet_private_key="").validate()
    assert any("WALLET_PRIVATE_KEY" in e or "Live" in e for e in errors)


def test_missing_llm_key_is_warning_not_error():
    s = _mk(llm_provider="deepseek", deepseek_api_key="")
    errors, warnings = s.validate()
    assert errors == []
    assert any("anahtar" in w for w in warnings)


def test_validate_or_raise_raises_on_error():
    with pytest.raises(RuntimeError):
        _mk(trading_mode="banana").validate_or_raise()


def test_validate_or_raise_passes_on_valid():
    Settings().validate_or_raise()
