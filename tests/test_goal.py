"""Hedef takip modülü testleri — aritmetik ve gerçekçilik bantları."""
from __future__ import annotations

import time

import pytest

from engine.analytics import goal as G


@pytest.fixture(autouse=True)
def izole(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "_PATH", str(tmp_path / "goal.json"))
    monkeypatch.delenv("GOAL_ASSUMED_CAGR", raising=False)


def test_hedef_tanimsizken_pasif_rapor():
    r = G.report(equity_curve=[], current_equity=100.0)
    assert r["active"] is False


def test_hedef_kaydedilir_ve_geri_yuklenir():
    G.set_goal(420000, 24, start_equity_usd=100.0, note="test")
    g = G.load_goal()
    assert g.target_usd == 420000 and g.horizon_months == 24 and g.active


def test_gereken_carpan_ve_cagr_dogru_hesaplanir():
    G.set_goal(400.0, 12, start_equity_usd=100.0)
    r = G.report(equity_curve=[100.0], current_equity=100.0)
    assert r["required_multiple"] == 4.0
    # 1 yılda 4× -> %300 CAGR
    assert r["required_cagr_pct"] == pytest.approx(300.0, abs=0.5)


def test_420k_hedefi_gercekci_degil_olarak_isaretlenir():
    G.set_goal(420000, 24, start_equity_usd=100.0)
    r = G.report(equity_curve=[100.0], current_equity=100.0)
    assert r["required_multiple"] == 4200.0
    assert r["feasibility"] == "gerçekçi değil"
    assert r["required_cagr_pct"] > 1000
    assert any("bahis" in w for w in r["warnings"])
    assert any("4,200 katı" in w or "4200 katı" in w for w in r["warnings"])


@pytest.mark.parametrize("hedef,ay,beklenen", [
    (115.0, 12, "makul"),        # ~%15/yıl
    (140.0, 12, "zorlu"),        # ~%40/yıl
    (190.0, 12, "çok riskli"),   # ~%90/yıl
    (300.0, 12, "gerçekçi değil"),  # ~%200/yıl
])
def test_gerceklik_bantlari(hedef, ay, beklenen):
    G.set_goal(hedef, ay, start_equity_usd=100.0)
    assert G.report(equity_curve=[100.0], current_equity=100.0)["feasibility"] == beklenen


def test_gunluk_gereken_oran_hesaplanir():
    G.set_goal(420000, 24, start_equity_usd=100.0)
    r = G.report(equity_curve=[100.0], current_equity=100.0)
    # 4200x / 2 yıl -> günde ~%1.15, her gün, hiç kaybetmeden
    assert r["required_daily_pct"] == pytest.approx(1.15, abs=0.05)


def test_olculen_hiz_equity_egrisinden_gelir():
    g = G.set_goal(1000.0, 24, start_equity_usd=100.0)
    g.start_ts = time.time() - 365.25 * 86400      # 1 yıl geçti
    G.save_goal(g)
    r = G.report(equity_curve=[100.0, 120.0], current_equity=120.0, now=time.time())
    assert r["actual_cagr_pct"] == pytest.approx(20.0, abs=1.0)
    assert r["years_to_target_at_actual"] is not None


def test_kayipta_olan_bot_icin_varis_tarihi_yok():
    g = G.set_goal(1000.0, 24, start_equity_usd=100.0)
    g.start_ts = time.time() - 365.25 * 86400
    G.save_goal(g)
    r = G.report(equity_curve=[100.0, 80.0], current_equity=80.0)
    assert r["actual_cagr_pct"] < 0
    assert r["years_to_target_at_actual"] is None and r["eta_at_actual"] is None
    assert any("altında" in w for w in r["warnings"])


def test_aylik_dca_ihtiyaci_hesaplanir():
    G.set_goal(10000.0, 12, start_equity_usd=100.0)
    r = G.report(equity_curve=[100.0], current_equity=100.0)
    dca = r["monthly_dca_needed_usd"]
    # ~10k'ya 1 yılda varmak icin aylik ~800$ (getiri katkisiyla) gerekir
    assert 700 < dca < 850


def test_hedefe_ulasildiysa_ek_katki_gerekmez():
    G.set_goal(100.0, 12, start_equity_usd=500.0)
    assert G.report(equity_curve=[500.0], current_equity=500.0)["monthly_dca_needed_usd"] == 0.0


def test_varsayilan_getiri_env_ile_degisir(monkeypatch):
    monkeypatch.setenv("GOAL_ASSUMED_CAGR", "0.30")
    G.set_goal(1000.0, 24, start_equity_usd=100.0)
    assert G.report(equity_curve=[100.0], current_equity=100.0)["assumed_cagr_pct"] == 30.0


def test_rapor_hicbir_risk_ayarini_degistirmez(monkeypatch):
    """Hedef modülü pasiftir: risk/strateji nesnelerine DOKUNMAMALI."""
    from engine.bot.orchestrator import bot
    onceki = (bot.risk.min_confidence, bot.risk.max_position_usd,
              bot.risk.max_daily_loss_usd)
    G.set_goal(420000, 24, start_equity_usd=100.0)
    G.report(equity_curve=[100.0], current_equity=100.0)
    assert (bot.risk.min_confidence, bot.risk.max_position_usd,
            bot.risk.max_daily_loss_usd) == onceki


def test_hedef_temizlenebilir():
    G.set_goal(1000.0, 12, start_equity_usd=100.0)
    G.clear_goal()
    assert G.load_goal().active is False


def test_bozuk_goal_dosyasi_cokmez(tmp_path, monkeypatch):
    p = tmp_path / "bozuk.json"
    p.write_text("{bu json degil", encoding="utf-8")
    monkeypatch.setattr(G, "_PATH", str(p))
    assert G.load_goal().active is False


# ---------------------------------------------------- küçük sermaye profili

def test_asgari_islem_buyuklugu_env_ile_ayarlanir(monkeypatch):
    from engine.bot import orchestrator as O
    monkeypatch.delenv("MIN_TRADE_USD", raising=False)
    assert O._min_trade_usd() == 10.0
    monkeypatch.setenv("MIN_TRADE_USD", "5")
    assert O._min_trade_usd() == 5.0


def test_asgari_islem_buyuklugu_kirpilir(monkeypatch):
    from engine.bot import orchestrator as O
    monkeypatch.setenv("MIN_TRADE_USD", "0.001")
    assert O._min_trade_usd() == 1.0
    monkeypatch.setenv("MIN_TRADE_USD", "999999")
    assert O._min_trade_usd() == 1000.0
    monkeypatch.setenv("MIN_TRADE_USD", "abc")
    assert O._min_trade_usd() == 10.0


def test_base_watchlistinde_var(monkeypatch):
    """Canlı hedef ağ Base olduğu için sinyal listesinde bulunmalı."""
    from engine.bot.orchestrator import SIGNAL_WATCHLIST
    base = [w for w in SIGNAL_WATCHLIST if w[0] == 8453]
    assert base, "Base (8453) sinyal listesinde yok"
    assert {w[1] for w in base} >= {"WETH", "cbBTC"}
