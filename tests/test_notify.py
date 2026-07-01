"""Bildirim + günlük özet testleri (ağ olmadan, mock ile)."""
import time

from engine.notify import notifier
from engine.notify.summary import build_summary


def test_no_channels_falls_back_to_log(monkeypatch):
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "DISCORD_WEBHOOK_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("NOTIFY_DESKTOP", raising=False)
    assert notifier.channels_enabled() == []
    res = notifier.notify("merhaba", "info")
    assert res == {"log": True}


def test_telegram_channel_detected_and_sent(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("NOTIFY_DESKTOP", raising=False)
    sent = {}

    def fake_tg(msg):
        sent["msg"] = msg
        return True
    monkeypatch.setattr(notifier, "_send_telegram", fake_tg)
    assert notifier.channels_enabled() == ["telegram"]
    res = notifier.notify("alım yapıldı", "trade")
    assert res == {"telegram": True}
    assert "alım yapıldı" in sent["msg"]


def test_discord_failure_isolated(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "http://x")
    monkeypatch.delenv("NOTIFY_DESKTOP", raising=False)

    def boom(msg):
        raise RuntimeError("ağ yok")
    monkeypatch.setattr(notifier, "_send_discord", boom)
    res = notifier.notify("test", "warn")  # hata fırlatmamalı
    assert res["discord"] is False


def test_build_summary_pnl_and_counts():
    now = int(time.time() * 1000)
    trades = [
        {"timestamp": now - 1000, "status": "filled", "side": "BUY",
         "base": "ETH", "price": 100, "filledPrice": 100, "feeUsd": 1.0},
        {"timestamp": now - 2000, "status": "filled", "side": "SELL",
         "base": "ETH", "price": 110, "filledPrice": 110, "feeUsd": 1.5},
        {"timestamp": now - 99 * 3600 * 1000, "status": "filled", "side": "BUY",
         "base": "ETH", "price": 90, "feeUsd": 1.0},  # pencere dışı
    ]
    equity = [{"t": now - 23 * 3600 * 1000, "equity": 10000},
              {"t": now, "equity": 10250}]
    text = build_summary(trades, equity, hours=24)
    assert "+250.00 USD" in text
    assert "2 (1 alım / 1 satım)" in text
    assert "Ücret: 2.50 USD" in text


def test_build_summary_empty():
    text = build_summary([], [], hours=24)
    assert "Günlük Özet" in text
