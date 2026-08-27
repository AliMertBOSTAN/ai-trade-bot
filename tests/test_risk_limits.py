"""Çalışma anında düzenlenebilir risk limitleri: kırpma, kalıcılık, fail-fast."""
from __future__ import annotations

import json

import pytest

from engine.bot.orchestrator import TradingBot


@pytest.fixture()
def bot(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return TradingBot()


def test_set_risk_limits_uygular_ve_kirpar(bot):
    r = bot.set_risk_limits(max_position_usd=250, max_daily_loss_usd=5,   # 5 -> 10'a kirpilir
                            max_gas_gwei=9999, slippage_bps=25,
                            daily_spend_limit_usd=1000)
    assert r["ok"] is True
    assert bot.risk.max_position_usd == 250
    assert bot.risk.max_daily_loss_usd == 10        # alt sinir
    assert bot.risk.max_gas_gwei == 500             # ust sinir
    assert bot.risk.slippage_bps == 25
    assert bot._spending.daily_limit_usd == 1000
    # RiskManager ve Executor ayni yeni nesneyi gormeli (kapilar tutarli)
    assert bot.rm.risk is bot.risk
    assert bot.executor.risk is bot.risk


def test_limitler_kalici_ve_geri_yuklenir(bot, tmp_path):
    bot.set_risk_limits(max_position_usd=333, daily_spend_limit_usd=750)
    cfg = json.loads((tmp_path / "risk.json").read_text(encoding="utf-8"))
    assert cfg["limits"]["max_position_usd"] == 333
    assert cfg["limits"]["daily_spend_limit_usd"] == 750
    # Yeni bot ayni DATA_DIR'dan acilinca limitleri geri yukler
    bot2 = TradingBot()
    assert bot2.risk.max_position_usd == 333
    assert bot2._spending.daily_limit_usd == 750


def test_gecersiz_deger_fail_fast(bot):
    with pytest.raises(ValueError):
        bot.set_risk_limits(max_position_usd="abc")


def test_kill_switch_sayaci_korunur(bot):
    # Gun ici gerceklesen zarar varken limit dusurulurse switch tetiklenebilir;
    # sayac ASLA sifirlanmaz (limit degisikligi zarari silemez).
    bot.rm.record_realized(-150.0)
    bot.set_risk_limits(max_daily_loss_usd=100)
    assert bot.rm.day_realized_pnl == -150.0
    assert bot.rm.kill_switch_triggered() is True
    bot.set_risk_limits(max_daily_loss_usd=200)
    assert bot.rm.kill_switch_triggered() is False


def test_get_risk_limits_semasi(bot):
    lim = bot.get_risk_limits()
    assert set(lim) >= {"min_confidence", "max_position_usd", "max_open_positions",
                        "max_daily_loss_usd", "max_gas_gwei", "slippage_bps",
                        "daily_spend_limit_usd", "preset", "bounds"}
    assert lim["bounds"]["max_gas_gwei"] == [5.0, 500.0]
