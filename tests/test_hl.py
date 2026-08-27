"""Hyperliquid perp masası testleri — AĞ ÇAĞRISI YOK.

`universe()` sahte bir evrenle değiştirilir; böylece kağıt broker'ın matematiği
(dolum, marj, funding, likidasyon, PnL) ve risk kapıları borsa erişimi olmadan
doğrulanır. Canlı imzalama yolu ayrıca `signer_info` üzerinden test edilir —
gerçek anahtar ASLA gerekmez.
"""
from __future__ import annotations

import pytest

from engine.risk import hl_risk
from engine.trading import hl_broker as hb

FAKE_UNIVERSE = {
    "BTC": {"symbol": "BTC", "max_leverage": 40, "sz_decimals": 5, "mark": 100_000.0,
            "funding_hourly": 0.0000125, "open_interest_usd": 1e9,
            "day_volume_usd": 5e9, "prev_day_px": 98_000.0},
    "ETH": {"symbol": "ETH", "max_leverage": 25, "sz_decimals": 4, "mark": 4_000.0,
            "funding_hourly": -0.00002, "open_interest_usd": 5e8,
            "day_volume_usd": 2e9, "prev_day_px": 4_100.0},
}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(hb, "universe", lambda: FAKE_UNIVERSE)
    monkeypatch.setenv("HL_LIVE", "0")
    monkeypatch.delenv("HL_API_WALLET_KEY", raising=False)
    monkeypatch.delenv("HL_ACCOUNT_ADDRESS", raising=False)
    hl_risk.reset_cooldowns()
    broker = hb.HLBroker()
    broker.reset_paper(1000.0)
    yield broker


# --------------------------------------------------------------- yardımcılar
def test_sembol_normalizasyonu():
    assert hb.normalize_symbol("BTCUSDT") == "BTC"
    assert hb.normalize_symbol("eth-perp") == "ETH"
    assert hb.normalize_symbol("WETH") == "ETH"
    assert hb.normalize_symbol("WBTC") == "BTC"
    assert hb.normalize_symbol("HYPE") == "HYPE"


def test_likidasyon_fiyati_yonlu(monkeypatch):
    monkeypatch.setattr(hb, "universe", lambda: FAKE_UNIVERSE)
    long_liq = hb.liquidation_price(100_000, 10, "LONG", "BTC")
    short_liq = hb.liquidation_price(100_000, 10, "SHORT", "BTC")
    assert long_liq is not None and short_liq is not None
    assert long_liq < 100_000 < short_liq, "LONG aşağı, SHORT yukarı likide olur"
    # 10x'te ham mesafe %10; bakım teminatı (BTC: 1/(2*40)=%1,25) likidasyonu
    # girişe DAHA YAKIN getirir -> 100k*(1-0.0875)=91.250
    assert 91_000 < long_liq < 91_500
    assert 108_500 < short_liq < 109_000


def test_yuksek_kaldiracta_likidasyon_daha_yakin():
    lo = hb.liquidation_price(100_000, 2, "LONG", "BTC")
    hi = hb.liquidation_price(100_000, 20, "LONG", "BTC")
    assert hi > lo, "20x likidasyon fiyatı girişe daha yakın olmalı"


def test_liquidation_price_gecersiz_girdi():
    assert hb.liquidation_price(0, 5, "LONG") is None
    assert hb.liquidation_price(100, 0, "LONG") is None


# ------------------------------------------------------------ kağıt broker
def test_kagit_pozisyon_acilir_ve_marj_duser(_isolate):
    b = _isolate
    res = b.open("BTC", "LONG", notional_usd=200, leverage=4)
    assert res["ok"], res
    assert res["mode"] == "paper"
    st = b.state()
    assert len(st["positions"]) == 1
    pos = st["positions"][0]
    assert pos["side"] == "LONG"
    # 200$ nosyonel / 4x = 50$ marj; ücret küçük ama düşülmüş olmalı
    assert 49 < pos["margin_usd"] < 51
    assert st["cash_usd"] < 1000 - 49


def test_asgari_emir_buyuklugu(_isolate):
    assert _isolate.open("BTC", "LONG", notional_usd=5, leverage=2)["ok"] is False


def test_yetersiz_teminat_reddedilir(_isolate):
    r = _isolate.open("BTC", "LONG", notional_usd=100_000, leverage=1)
    assert r["ok"] is False and "teminat" in r["error"].lower()


def test_gecersiz_yon(_isolate):
    assert _isolate.open("BTC", "YUKARI", notional_usd=100)["ok"] is False


def test_bilinmeyen_sembol(_isolate):
    assert _isolate.open("YOKBOYLECOIN", "LONG", notional_usd=100)["ok"] is False


def test_kar_ile_kapanis_nakdi_arttirir(_isolate, monkeypatch):
    b = _isolate
    b.open("BTC", "LONG", notional_usd=400, leverage=4)
    cash_after_open = b.state()["cash_usd"]
    # Fiyat %10 yukarı
    up = {k: dict(v) for k, v in FAKE_UNIVERSE.items()}
    up["BTC"]["mark"] = 110_000.0
    monkeypatch.setattr(hb, "universe", lambda: up)
    res = b.close("BTC")
    assert res["ok"] and res["pnl_usd"] > 30, res
    assert b.state()["cash_usd"] > cash_after_open


def test_short_dususte_kar_eder(_isolate, monkeypatch):
    b = _isolate
    b.open("ETH", "SHORT", notional_usd=200, leverage=2)
    down = {k: dict(v) for k, v in FAKE_UNIVERSE.items()}
    down["ETH"]["mark"] = 3_600.0     # %10 düşüş
    monkeypatch.setattr(hb, "universe", lambda: down)
    res = b.close("ETH")
    assert res["ok"] and res["pnl_usd"] > 15, res


def test_ters_yon_once_mevcudu_kapatir(_isolate):
    b = _isolate
    b.open("BTC", "LONG", notional_usd=200, leverage=2)
    b.open("BTC", "SHORT", notional_usd=200, leverage=2)
    st = b.state()
    # Aynı boyutta ters emir pozisyonu netler
    assert len(st["positions"]) == 0


def test_likidasyon_kagit_modda_tetiklenir(_isolate, monkeypatch):
    b = _isolate
    b.open("BTC", "LONG", notional_usd=500, leverage=10)
    crash = {k: dict(v) for k, v in FAKE_UNIVERSE.items()}
    crash["BTC"]["mark"] = 80_000.0    # %20 düşüş, 10x'te likidasyon
    monkeypatch.setattr(hb, "universe", lambda: crash)
    st = b.state()
    assert st["positions"] == []
    assert any(h["action"] == "LIQUIDATED" for h in st["history"])
    assert st["day_realized_pnl"] < 0


def test_funding_long_pozitif_oranda_oder(_isolate, monkeypatch):
    import time as _t
    b = _isolate
    b.open("BTC", "LONG", notional_usd=1000, leverage=5)
    pos = b._book.positions["BTC"]
    pos.last_funding_ts = int(_t.time()) - 3600    # 1 saat geriye al
    cash_before = b._book.cash_usd
    b.state()
    assert b._book.cash_usd < cash_before, "pozitif funding'de LONG öder"


def test_kagit_defteri_diske_yazilir_ve_geri_yuklenir(_isolate, tmp_path):
    b = _isolate
    b.open("ETH", "LONG", notional_usd=120, leverage=3)
    b2 = hb.HLBroker()
    st = b2.state()
    assert len(st["positions"]) == 1
    assert st["positions"][0]["symbol"] == "ETH"


# ------------------------------------------------------------- imzalayıcı
def test_imzalayici_anahtarsiz_hazir_degil(monkeypatch):
    monkeypatch.delenv("HL_API_WALLET_KEY", raising=False)
    monkeypatch.setattr("engine.security.keystore.load_private_key", lambda *a, **k: None)
    info = hb.signer_info()
    assert info["ready"] is False and info["reason"]


def test_api_wallet_adres_olmadan_hazir_degil(monkeypatch):
    monkeypatch.setenv("HL_API_WALLET_KEY", "0x" + "11" * 32)
    monkeypatch.delenv("HL_ACCOUNT_ADDRESS", raising=False)
    monkeypatch.setattr("engine.security.keystore.load_private_key", lambda *a, **k: None)
    info = hb.signer_info()
    assert info["ready"] is False
    assert "HL_ACCOUNT_ADDRESS" in info["reason"]


def test_canli_bayrak_kapaliyken_hazir_degil(_isolate, monkeypatch):
    monkeypatch.setenv("HL_API_WALLET_KEY", "0x" + "11" * 32)
    monkeypatch.setenv("HL_ACCOUNT_ADDRESS", "0x" + "22" * 20)
    monkeypatch.setenv("HL_LIVE", "0")
    assert _isolate.live_ready()["ready"] is False
    assert any("HL_LIVE" in r for r in _isolate.live_ready()["reasons"])


# ------------------------------------------------------------- risk kapıları
def _state(cash=1000.0, positions=None, day_pnl=0.0):
    return {"cash_usd": cash, "positions": positions or [],
            "day_realized_pnl": day_pnl}


def test_kapi_normal_emri_onaylar():
    d = hl_risk.check(symbol="BTC", side="LONG", notional_usd=200,
                      leverage=3, state=_state())
    assert d.approved and d.leverage == 3


def test_kapi_kaldiraci_tavana_kirpar(monkeypatch):
    monkeypatch.setenv("HL_MAX_LEVERAGE", "5")
    d = hl_risk.check(symbol="BTC", side="LONG", notional_usd=200,
                      leverage=25, state=_state())
    assert d.approved and d.leverage == 5
    assert any("kaldıraç" in w for w in d.warnings)


def test_kapi_nosyoneli_kirpar(monkeypatch):
    monkeypatch.setenv("HL_MAX_NOTIONAL_USD", "150")
    d = hl_risk.check(symbol="BTC", side="LONG", notional_usd=900,
                      leverage=3, state=_state())
    assert d.approved and d.notional_usd == 150


def test_gunluk_zarar_kill_switch(monkeypatch):
    monkeypatch.setenv("HL_MAX_DAILY_LOSS_USD", "50")
    d = hl_risk.check(symbol="BTC", side="LONG", notional_usd=100,
                      leverage=2, state=_state(day_pnl=-60))
    assert not d.approved and "kill-switch" in d.reason


def test_azami_pozisyon_sayisi(monkeypatch):
    monkeypatch.setenv("HL_MAX_POSITIONS", "2")
    pos = [{"symbol": "BTC", "notional_usd": 100},
           {"symbol": "ETH", "notional_usd": 100}]
    d = hl_risk.check(symbol="SOL", side="LONG", notional_usd=100,
                      leverage=2, state=_state(positions=pos))
    assert not d.approved and "pozisyon sayısı" in d.reason


def test_toplam_maruziyet_tavani(monkeypatch):
    monkeypatch.setenv("HL_MAX_TOTAL_NOTIONAL", "300")
    pos = [{"symbol": "BTC", "notional_usd": 295}]
    d = hl_risk.check(symbol="ETH", side="LONG", notional_usd=200,
                      leverage=2, state=_state(positions=pos))
    assert not d.approved and "maruziyet" in d.reason


def test_likidasyon_mesafesi_kaldiraci_kisar(monkeypatch):
    monkeypatch.setenv("HL_MIN_LIQ_DISTANCE", "20")
    monkeypatch.setenv("HL_MAX_LEVERAGE", "20")
    d = hl_risk.check(symbol="BTC", side="LONG", notional_usd=100,
                      leverage=20, state=_state())
    assert d.approved and d.leverage <= 5, d


def test_cooldown_ayni_sembolde_engeller(monkeypatch):
    monkeypatch.setenv("HL_COOLDOWN_S", "600")
    hl_risk.note_order("BTC")
    d = hl_risk.check(symbol="BTC", side="LONG", notional_usd=100,
                      leverage=2, state=_state())
    assert not d.approved and "bekleme" in d.reason
    # Başka sembol etkilenmez
    assert hl_risk.check(symbol="ETH", side="LONG", notional_usd=100,
                         leverage=2, state=_state()).approved


def test_ai_otopilot_kapaliyken_reddeder(monkeypatch):
    monkeypatch.setenv("HL_AI_AUTOPILOT", "0")
    d = hl_risk.check(symbol="BTC", side="LONG", notional_usd=100, leverage=2,
                      state=_state(), for_ai=True, confidence=0.9)
    assert not d.approved and "otopilot" in d.reason


def test_require_autopilot_false_gercek_kapiyi_degerlendirir(monkeypatch):
    """Şalter kapalıyken bile RİSK kapısının gerçek sonucu görülebilmeli."""
    monkeypatch.setenv("HL_AI_AUTOPILOT", "0")
    d = hl_risk.check(symbol="BTC", side="LONG", notional_usd=100, leverage=2,
                      state=_state(), for_ai=True, confidence=0.9,
                      require_autopilot=False)
    assert d.approved, d.reason
    # Risk kuralları yine AI tavanlarıyla uygulanır
    monkeypatch.setenv("HL_AI_MAX_NOTIONAL_USD", "50")
    d2 = hl_risk.check(symbol="BTC", side="LONG", notional_usd=900, leverage=2,
                       state=_state(), for_ai=True, confidence=0.9,
                       require_autopilot=False)
    assert d2.approved and d2.notional_usd == 50


def test_ai_guven_esigi(monkeypatch):
    monkeypatch.setenv("HL_AI_AUTOPILOT", "1")
    monkeypatch.setenv("HL_AI_MIN_CONFIDENCE", "0.8")
    d = hl_risk.check(symbol="BTC", side="LONG", notional_usd=100, leverage=2,
                      state=_state(), for_ai=True, confidence=0.6)
    assert not d.approved and "güveni" in d.reason


def test_ai_tavanlari_elle_tavandan_dar(monkeypatch):
    monkeypatch.setenv("HL_AI_AUTOPILOT", "1")
    monkeypatch.setenv("HL_MAX_NOTIONAL_USD", "1000")
    monkeypatch.setenv("HL_AI_MAX_NOTIONAL_USD", "100")
    monkeypatch.setenv("HL_MAX_LEVERAGE", "10")
    monkeypatch.setenv("HL_AI_MAX_LEVERAGE", "2")
    d = hl_risk.check(symbol="BTC", side="LONG", notional_usd=900, leverage=10,
                      state=_state(), for_ai=True, confidence=0.95)
    assert d.approved and d.notional_usd == 100 and d.leverage == 2


def test_intel_ters_yapida_reddeder(monkeypatch):
    monkeypatch.setenv("INTEL_BLOCK_SCORE", "0.5")
    d = hl_risk.check(symbol="BTC", side="LONG", notional_usd=100, leverage=2,
                      state=_state(), intel_score=-0.8)
    assert not d.approved and "yapısı" in d.reason
    # SHORT için aynı skor DESTEKLEYİCİ
    assert hl_risk.check(symbol="BTC", side="SHORT", notional_usd=100,
                         leverage=2, state=_state(), intel_score=-0.8).approved


# --------------------------------------------------------- analist derinliği
def test_analiz_derinligi_token_butcesi():
    from engine.marketdata import analyst
    assert analyst.depth_tokens("kisa") < analyst.depth_tokens("normal")
    assert analyst.depth_tokens("normal") < analyst.depth_tokens("derin")
    assert analyst.depth_tokens("derin") < analyst.depth_tokens("cok_derin")
    assert analyst.depth_tokens("bilinmeyen") == analyst.DEPTHS["normal"]
    assert analyst.depth_tokens("1800") == 1800
    assert analyst.depth_tokens("99999") == 8000, "üst sınır kırpılır"
    assert analyst.depth_tokens("10") == 200, "alt sınır kırpılır"


def test_intel_satirlari_cache_bosken_bos():
    from engine.marketdata import analyst
    from engine.marketdata.intel import cache
    cache.clear()
    assert analyst._intel_lines() == []


def test_otonom_analist_varsayilan_kapali(monkeypatch):
    monkeypatch.delenv("ANALYST_AUTO", raising=False)
    from engine.marketdata.ai_analyst import AIAnalyst
    assert AIAnalyst.enabled() is False


# ------------------------------------------------------- AI karar makinesi
def _analyst(monkeypatch, tmp_path, **env):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from engine.marketdata.ai_analyst import AIAnalyst
    return AIAnalyst()


def test_karar_llm_kapaliyken_bekle(monkeypatch, tmp_path):
    a = _analyst(monkeypatch, tmp_path, HL_AI_AUTOPILOT="1")
    d = a.decide({"symbol": "BTC", "heuristic": True, "confidence": 0.99,
                  "trade": {"side": "LONG", "leverage": 3, "size_hint_pct": 20}})
    assert d["state"] == "HEURISTIC" and d["verdict"] == "wait"
    assert d["label"] == "BEKLE" and d["executed"] is False


def test_karar_plan_yoksa_bekle(monkeypatch, tmp_path):
    a = _analyst(monkeypatch, tmp_path, HL_AI_AUTOPILOT="1")
    d = a.decide({"symbol": "BTC", "heuristic": False, "trade": {"side": "YOK"}})
    assert d["state"] == "NO_PLAN" and d["verdict"] == "wait"


def test_karar_dusuk_guvende_bekle(monkeypatch, tmp_path):
    a = _analyst(monkeypatch, tmp_path, HL_AI_AUTOPILOT="1",
                 HL_AI_MIN_CONFIDENCE="0.8")
    d = a.decide({"symbol": "BTC", "heuristic": False, "confidence": 0.5,
                  "trade": {"side": "LONG", "leverage": 3, "size_hint_pct": 20}})
    assert d["state"] == "LOW_CONF" and d["verdict"] == "wait"


def test_karar_otopilot_kapaliyken_de_uretilir(_isolate, monkeypatch, tmp_path):
    """En kritik davranış: otopilot KAPALIYKEN bile karar görünür olmalı."""
    monkeypatch.setenv("HL_AI_AUTOPILOT", "0")
    a = _analyst(monkeypatch, tmp_path, HL_AI_AUTOPILOT="0")
    monkeypatch.setattr("engine.trading.hl_broker.hl", _isolate)
    d = a.decide({"symbol": "BTC", "heuristic": False, "confidence": 0.9,
                  "trade": {"side": "LONG", "leverage": 3, "size_hint_pct": 20}})
    assert d["autopilot"] is False
    assert d["executed"] is False
    # Şalter kapalı olması BAŞLI BAŞINA "GİRME" sebebi DEĞİLDİR: risk kapısı
    # geçiyorsa karar POZİSYON AL olur, sadece emir gönderilmez.
    assert d["state"] == "READY", d
    assert d["verdict"] == "enter" and "Otopilot kapalı" in d["reason"]
    assert d["plan"]["requested_leverage"] == 3
    assert d["plan"]["approved_leverage"] == 3


def test_karar_ai_kaldiracini_kullanir(_isolate, monkeypatch, tmp_path):
    monkeypatch.setattr("engine.trading.hl_broker.hl", _isolate)
    a = _analyst(monkeypatch, tmp_path, HL_AI_AUTOPILOT="0",
                 HL_AI_MAX_LEVERAGE="10", HL_MAX_LEVERAGE="10",
                 HL_MIN_LIQ_DISTANCE="5")
    d = a.decide({"symbol": "ETH", "heuristic": False, "confidence": 0.9,
                  "trade": {"side": "LONG", "leverage": 7, "size_hint_pct": 10,
                            "leverage_note": "stop %9 uzakta"}})
    assert d["plan"]["requested_leverage"] == 7
    assert d["plan"]["leverage_note"] == "stop %9 uzakta"
    assert d["plan"]["exchange_max_leverage"] == 25


def test_karar_kaldiraci_borsa_tavaniyla_kirpar(_isolate, monkeypatch, tmp_path):
    monkeypatch.setattr("engine.trading.hl_broker.hl", _isolate)
    a = _analyst(monkeypatch, tmp_path, HL_AI_AUTOPILOT="0")
    # FAKE evrende BTC azami 40x; AI 99 isterse borsa tavanina kirpilir
    d = a.decide({"symbol": "BTC", "heuristic": False, "confidence": 0.9,
                  "trade": {"side": "LONG", "leverage": 99, "size_hint_pct": 10}})
    assert d["plan"]["requested_leverage"] == 40


def test_karar_kaldirac_verilmezse_muhafazakar_taban(_isolate, monkeypatch, tmp_path):
    monkeypatch.setattr("engine.trading.hl_broker.hl", _isolate)
    a = _analyst(monkeypatch, tmp_path, HL_AI_AUTOPILOT="0")
    d = a.decide({"symbol": "BTC", "heuristic": False, "confidence": 0.9,
                  "trade": {"side": "LONG", "size_hint_pct": 10}})
    assert d["plan"]["requested_leverage"] == 2


def test_karar_kapi_reddedince_girme(_isolate, monkeypatch, tmp_path):
    monkeypatch.setattr("engine.trading.hl_broker.hl", _isolate)
    a = _analyst(monkeypatch, tmp_path, HL_AI_AUTOPILOT="1",
                 HL_MAX_DAILY_LOSS_USD="1")
    # Once state() cagir ki gun anahtari bugune ayarlansin; aksi halde
    # _roll_day() gunluk PnL'i sifirlar ve kill-switch tetiklenmez.
    _isolate.state()
    _isolate._book.day_realized_pnl_usd = -50.0
    d = a.decide({"symbol": "BTC", "heuristic": False, "confidence": 0.95,
                  "trade": {"side": "LONG", "leverage": 3, "size_hint_pct": 20}})
    assert d["state"] == "BLOCKED" and d["verdict"] == "avoid"
    assert d["label"] == "GİRME" and "kill-switch" in d["reason"]


def test_karar_dry_run_emir_gondermez(_isolate, monkeypatch, tmp_path):
    monkeypatch.setattr("engine.trading.hl_broker.hl", _isolate)
    a = _analyst(monkeypatch, tmp_path, HL_AI_AUTOPILOT="1")
    d = a.decide({"symbol": "BTC", "heuristic": False, "confidence": 0.95,
                  "trade": {"side": "LONG", "leverage": 3, "size_hint_pct": 20}},
                 execute=False)
    assert d["executed"] is False
    assert _isolate.state()["positions"] == []


def test_karar_kaydi_yoksa_aninda_hesaplanir(_isolate, monkeypatch, tmp_path):
    """Eski rapor formatı: karar kaydı yok -> kart boş kalmamalı, hesaplanmalı."""
    monkeypatch.setattr("engine.trading.hl_broker.hl", _isolate)
    a = _analyst(monkeypatch, tmp_path, HL_AI_AUTOPILOT="0")
    a._loaded = True
    a.reports = {"BTC": {"symbol": "BTC", "confidence": 0.9, "heuristic": False,
                         "ts": 1, "trade": {"side": "LONG", "leverage": 3,
                                            "size_hint_pct": 10}}}
    d = a.last_decision("BTC")
    assert d["state"] == "READY" and d["verdict"] == "enter"
    assert d["plan"]["requested_leverage"] == 3
    assert d["report"]["symbol"] == "BTC"


def test_taranmamis_pair_no_scan(monkeypatch, tmp_path):
    a = _analyst(monkeypatch, tmp_path)
    d = a.last_decision("DOGE")
    assert d["state"] == "NO_SCAN" and d["verdict"] == "wait"
    assert "henüz analiz" in d["reason"]


# ------------------------------------------------------------ /hl uçları
def test_universe_ucu_hata_gerekcesi_dondurur(monkeypatch):
    """Piyasa listesi alınamazsa arayüz SEBEBİ görmeli — sessiz boş liste yok."""
    from engine.api import hl as hl_api

    def patlar():
        raise RuntimeError("baglanti yok")

    monkeypatch.setattr(hl_api, "universe", patlar)
    out = hl_api.hl_universe(limit=10)
    assert out["ok"] is False
    assert out["rows"] == []
    assert "baglanti yok" in out["error"]


def test_universe_bos_evren_de_gerekce_dondurur(monkeypatch):
    from engine.api import hl as hl_api
    monkeypatch.setattr(hl_api, "universe", dict)
    out = hl_api.hl_universe()
    assert out["ok"] is False and out["error"]


def test_universe_24s_degisimi_hesaplar(monkeypatch):
    from engine.api import hl as hl_api
    monkeypatch.setattr(hl_api, "universe", lambda: FAKE_UNIVERSE)
    out = hl_api.hl_universe()
    assert out["ok"] is True and out["count"] == 2
    btc = next(r for r in out["rows"] if r["symbol"] == "BTC")
    # 100.000 / 98.000 -> +%2.04
    assert btc["change_pct_24h"] == pytest.approx(2.04, abs=0.01)
    # hacme gore sirali
    assert out["rows"][0]["symbol"] == "BTC"


def test_health_ucu_hangi_halkanin_koptugunu_soyler(monkeypatch):
    from engine.api import hl as hl_api
    monkeypatch.setattr(hl_api, "universe", lambda: FAKE_UNIVERSE)
    h = hl_api.health()
    assert h["engine"] is True and h["hyperliquid"] is True and h["markets"] == 2
    assert h["error"] is None and "live" in h and "limits" in h

    def patlar():
        raise RuntimeError("HL erisilemiyor")

    monkeypatch.setattr(hl_api, "universe", patlar)
    h2 = hl_api.health()
    assert h2["engine"] is True and h2["hyperliquid"] is False
    assert "HL erisilemiyor" in h2["error"]
