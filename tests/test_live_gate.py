"""Kanıt kapısı testleri — canlıya geçiş için ölçülmüş kenar şartı."""
from __future__ import annotations

import pytest

from engine.trading import live_gate


def _trade(side, price, amount=1.0, fee=0.0, ts=0, base="ETH"):
    return {"status": "filled", "side": side, "price": price, "filledPrice": price,
            "amount": amount, "feeUsd": fee, "timestamp": ts, "chainId": 8453,
            "base": base}


def _kazancli(n_win=25, n_loss=5, win=10.0, loss=2.0):
    """n_win kârlı (+win$) + n_loss zararlı (-loss$) kapanmış işlem üretir."""
    rows, ts = [], 0
    for _ in range(n_win):
        ts += 1
        rows += [_trade("BUY", 100.0, ts=ts), _trade("SELL", 100.0 + win, ts=ts + 1)]
        ts += 1
    for _ in range(n_loss):
        ts += 1
        rows += [_trade("BUY", 100.0, ts=ts), _trade("SELL", 100.0 - loss, ts=ts + 1)]
        ts += 1
    return rows


@pytest.fixture(autouse=True)
def temiz_env(monkeypatch):
    for k in ("LIVE_GATE", "LIVE_GATE_MIN_TRADES", "LIVE_GATE_MIN_PROFIT_FACTOR",
              "LIVE_GATE_MIN_NET_USD", "LIVE_GATE_MAX_DD_PCT", "LIVE_GATE_WINDOW"):
        monkeypatch.delenv(k, raising=False)


def test_kanitli_kenar_kapiyi_acar():
    out = live_gate.evaluate(_kazancli(), equity=[10000, 10200, 10400])
    assert out["ready"] is True and out["reasons"] == []
    assert out["stats"]["closed_trades"] == 30
    assert out["stats"]["net_pnl_usd"] > 0
    assert out["stats"]["profit_factor"] > 1.2


def test_az_islemle_kapi_acilmaz():
    out = live_gate.evaluate(_kazancli(n_win=5, n_loss=0), equity=[10000, 10100])
    assert out["ready"] is False
    assert any("kapanan işlem yok" in r for r in out["reasons"])


def test_zarardaysa_kapi_acilmaz():
    out = live_gate.evaluate(_kazancli(n_win=5, n_loss=25), equity=[10000, 9000])
    assert out["ready"] is False
    assert any("net PnL" in r for r in out["reasons"])


def test_dusuk_profit_factor_reddedilir(monkeypatch):
    monkeypatch.setenv("LIVE_GATE_MIN_TRADES", "10")
    monkeypatch.setenv("LIVE_GATE_MIN_PROFIT_FACTOR", "3.0")
    # 6 kazanç (+10) / 4 kayıp (-10) -> PF = 1.5 (< 3.0 eşiği)
    out = live_gate.evaluate(_kazancli(n_win=6, n_loss=4, win=10.0, loss=10.0),
                             equity=[10000, 10500])
    assert out["ready"] is False
    assert any("profit factor" in r for r in out["reasons"])


def test_yuksek_dusus_reddedilir(monkeypatch):
    monkeypatch.setenv("LIVE_GATE_MAX_DD_PCT", "5")
    out = live_gate.evaluate(_kazancli(), equity=[10000, 12000, 9000, 11000])
    assert out["ready"] is False
    assert any("düşüş" in r for r in out["reasons"])


def test_kapi_env_ile_kapatilabilir(monkeypatch):
    monkeypatch.setenv("LIVE_GATE", "0")
    out = live_gate.evaluate([], equity=[])
    assert out["ready"] is True and out["enabled"] is False


def test_esikler_envden_okunur(monkeypatch):
    monkeypatch.setenv("LIVE_GATE_MIN_TRADES", "7")
    monkeypatch.setenv("LIVE_GATE_MIN_NET_USD", "42")
    th = live_gate.thresholds()
    assert th["min_trades"] == 7 and th["min_net_usd"] == 42.0


def test_bozuk_env_degeri_varsayilana_duser(monkeypatch):
    monkeypatch.setenv("LIVE_GATE_MIN_TRADES", "abc")
    assert live_gate.thresholds()["min_trades"] == 30


def test_bos_gecmis_guvenli_tarafa_duser():
    out = live_gate.evaluate([], equity=[])
    assert out["ready"] is False and out["stats"]["closed_trades"] == 0


def test_db_hatasinda_kapi_kapali_kalir(monkeypatch):
    class _Patlak:
        def recent_trades(self, n):
            raise OSError("db kilitli")

    monkeypatch.setattr("engine.storage.db.store", _Patlak())
    out = live_gate.evaluate()
    assert out["ready"] is False and out["reasons"]


def test_onucus_kanit_kapisini_kontrol_olarak_icerir(monkeypatch):
    """live_preflight çıktısı 'proven_edge' kontrolünü taşımalı."""
    from engine.bot.orchestrator import bot
    monkeypatch.setattr(bot, "enabled_chains", [])
    monkeypatch.setattr(live_gate, "evaluate", lambda: {"ready": False, "reasons": ["x"]})
    rep = bot.live_preflight()
    assert "proven_edge" in rep["checks"] and rep["checks"]["proven_edge"] is False
    assert rep["ready"] is False


# --------------------------------------------- kaldıraçlı canlı yol envanteri

def test_kaldirac_envanteri_durustur(monkeypatch):
    """`leverage_status` bugün NE OLMADIĞINI da açıkça bildirmeli."""
    from engine.trading import live_gate as LG
    st = LG.leverage_status()
    assert st["have"]["spot_live_base"] is True
    assert st["have"]["kelly_engine"] is True
    # imzalı perp emir yolu kurulmadı -> açıkça False ve engelleyici
    assert st["have"]["perp_live_orders"] is False
    assert any("perp" in b.lower() for b in st["blockers"])
    assert st["ready"] is False


def test_kaldirac_motoru_kapaliyken_tavan_1x(monkeypatch):
    from engine.trading import live_gate as LG
    monkeypatch.setenv("LEVERAGE_ENABLED", "0")
    assert LG.leverage_status()["current_max_leverage"] == 1.0


def test_kanit_kapisi_engelleri_kaldirac_durumuna_yansir(monkeypatch):
    from engine.trading import live_gate as LG
    monkeypatch.setattr(LG, "evaluate",
                        lambda: {"ready": False, "reasons": ["ÖZEL-ENGEL"]})
    assert "ÖZEL-ENGEL" in LG.leverage_status()["blockers"]
