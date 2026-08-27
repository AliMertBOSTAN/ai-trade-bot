"""Kaldıraç motoru testleri — kaldıracı KENAR belirler, iştah değil."""
from __future__ import annotations

import pytest

from engine.risk import leverage as L


@pytest.fixture(autouse=True)
def acik(monkeypatch):
    """Testlerde motor açık; diğer eşikler varsayılan."""
    monkeypatch.setenv("LEVERAGE_ENABLED", "1")
    for k in ("LEVERAGE_MAX", "LEVERAGE_KELLY_FRACTION", "LEVERAGE_MIN_SAMPLES"):
        monkeypatch.delenv(k, raising=False)


def _kenarli(n_win=20, n_loss=10, win=3.0, loss=1.0):
    return [win] * n_win + [-loss] * n_loss


# ------------------------------------------------------------- Kelly

@pytest.mark.parametrize("p,b,beklenen", [
    (0.60, 2.0, 0.40),    # 0.6 - 0.4/2
    (0.50, 1.0, 0.0),     # adil oyun -> bahis yok
    (0.40, 1.0, 0.0),     # negatif kenar -> 0 (ters bahis DEĞİL)
    (1.00, 1.0, 1.0),     # kesin kazanç
])
def test_kelly_kesri(p, b, beklenen):
    assert L.kelly_fraction(p, b) == pytest.approx(beklenen, abs=1e-6)


def test_kelly_bozuk_orana_dayanikli():
    assert L.kelly_fraction(0.9, 0.0) == 0.0
    assert L.kelly_fraction(0.9, -5) == 0.0


# --------------------------------------------------- kaldıraç kararı

def test_motor_kapaliyken_kaldirac_yok(monkeypatch):
    monkeypatch.setenv("LEVERAGE_ENABLED", "0")
    d = L.decide_leverage(1.0, _kenarli())
    assert d["leverage"] == 1.0 and "kapalı" in d["reason"]


def test_yetersiz_ornekte_kaldirac_yok():
    d = L.decide_leverage(1.0, _kenarli(n_win=4, n_loss=1))
    assert d["leverage"] == 1.0 and "yetersiz örnek" in d["reason"]


def test_net_zarardayken_kaldirac_yok():
    d = L.decide_leverage(1.0, [1.0] * 10 + [-3.0] * 20)
    assert d["leverage"] == 1.0 and "kenar yok" in d["reason"]


def test_kelly_sifirsa_kaldirac_yok(monkeypatch):
    """Kelly 0 dönerse (savunma kapısı) kaldıraç açılmaz."""
    monkeypatch.setattr(L, "kelly_fraction", lambda p, b: 0.0)
    d = L.decide_leverage(1.0, _kenarli())
    assert d["leverage"] == 1.0 and "kenar yok" in d["reason"]


def test_net_pozitif_ise_kelly_de_pozitiftir():
    """Matematiksel özdeşlik: net PnL > 0  <=>  p*b > (1-p)  <=>  Kelly > 0.
    Düşük kazanma oranı, yüksek ödeme oranıyla telafi edilebilir."""
    pnls = [10.0] * 3 + [-0.3] * 27          # p=0.10 ama b=33 -> Kelly > 0
    d = L.decide_leverage(1.0, pnls)
    assert d["stats"]["net"] > 0 and d["kelly"] > 0 and d["leverage"] > 1.0


def test_kanitli_kenarda_kaldirac_acilir():
    d = L.decide_leverage(0.90, _kenarli())
    assert d["leverage"] > 1.0
    assert d["kelly"] > 0 and "Kelly" in d["reason"]


def test_guven_dustukce_kaldirac_duser():
    yuksek = L.decide_leverage(0.95, _kenarli())["leverage"]
    dusuk = L.decide_leverage(0.50, _kenarli())["leverage"]
    assert dusuk < yuksek


def test_sert_tavan_asilamaz(monkeypatch):
    """Kelly ne kadar yüksek olursa olsun LEVERAGE_MAX aşılamaz."""
    monkeypatch.setenv("LEVERAGE_MAX", "2")
    monkeypatch.setenv("LEVERAGE_KELLY_FRACTION", "1.0")
    monkeypatch.setattr(L, "kelly_fraction", lambda p, b: 99.0)   # absürt kenar
    d = L.decide_leverage(1.0, _kenarli())
    assert d["leverage"] == 2.0 and d["capped"] is True


def test_tavan_her_zaman_uygulanir(monkeypatch):
    monkeypatch.setenv("LEVERAGE_MAX", "3")
    for conf in (0.1, 0.5, 0.9, 1.0):
        assert L.decide_leverage(conf, _kenarli(n_win=29, n_loss=1,
                                                win=50.0))["leverage"] <= 3.0


def test_kaldirac_hicbir_kosulda_1in_altina_inmez():
    for pnls in ([], [-1.0] * 50, _kenarli()):
        assert L.decide_leverage(0.0, pnls)["leverage"] >= 1.0


# --------------------------------------------------------- likidasyon

def test_kaldiracsiz_longda_likidasyon_yok():
    assert L.liquidation_price(1860.0, 1.0, "LONG") is None


@pytest.mark.parametrize("lev,beklenen_mesafe", [
    (2.0, 49.5), (5.0, 19.5), (10.0, 9.5), (20.0, 4.5), (50.0, 1.5),
])
def test_likidasyon_mesafesi(lev, beklenen_mesafe):
    assert L.liquidation_distance_pct(lev) == pytest.approx(beklenen_mesafe, abs=0.01)


def test_long_likidasyonu_girisin_altinda_short_ustunde():
    lo = L.liquidation_price(1000.0, 10.0, "LONG")
    sh = L.liquidation_price(1000.0, 10.0, "SHORT")
    assert lo < 1000.0 < sh
    assert lo == pytest.approx(905.0, abs=0.5)
    assert sh == pytest.approx(1095.0, abs=0.5)


# ---------------------------------------------------------- iflas riski

def test_kenar_yoksa_iflas_kesindir():
    """Beklenen değeri ≤ 0 olan oyunda uzun vadede iflas olasılığı 1.0'dır."""
    assert L.risk_of_ruin(0.50, 0.10, 1.0) == 1.0
    assert L.risk_of_ruin(0.40, 0.10, 1.0) == 1.0


def test_kenar_varsa_iflas_olasiligi_1in_altinda():
    r = L.risk_of_ruin(0.60, 0.02, 2.0)
    assert 0.0 <= r < 1.0


def test_risk_arttikca_iflas_olasiligi_artar():
    az = L.risk_of_ruin(0.60, 0.01, 2.0)
    cok = L.risk_of_ruin(0.60, 0.25, 2.0)
    assert cok > az


# ------------------------------------------------------ hedef olasılığı

def test_420k_hedefinin_ust_siniri_1_bolu_4200():
    t = L.probability_of_target(100.0, 420000.0)
    assert t["multiple"] == 4200.0
    assert t["fair_upper_bound"] == pytest.approx(1 / 4200, rel=1e-9)
    assert t["one_in"] == 4200


def test_hedef_siniri_kaldiractan_bagimsizdir():
    """Aynı başlangıç/hedef için sınır tek bir sayıdır — kaldıraç girmez."""
    a = L.probability_of_target(100.0, 420000.0)["fair_upper_bound"]
    b = L.probability_of_target(100.0, 420000.0)["fair_upper_bound"]
    assert a == b
    assert "kaldıraçla DEĞİŞMEZ" in L.probability_of_target(100.0, 420000.0)["note"]


def test_ulasilmis_hedef_icin_sinir_1():
    assert L.probability_of_target(500.0, 100.0)["fair_upper_bound"] == 1.0


# ------------------------------------------------------------ toplu rapor

def test_assess_gercek_durumda_kaldiracsiz_ve_uyarili():
    r = L.assess(confidence=0.95, entry_price=1860.0, pnls=[-1.0, -2.0, 1.0],
                 start_usd=100.0, target_usd=420000.0)
    assert r["decision"]["leverage"] == 1.0
    assert r["liquidation_price"] is None          # 1× long -> likidasyon yok
    assert r["target"]["one_in"] == 4200


def test_assess_kenarli_durumda_likidasyon_fiyati_dondurur():
    r = L.assess(confidence=0.9, entry_price=1860.0, pnls=_kenarli())
    assert r["decision"]["leverage"] > 1.0
    assert r["liquidation_price"] is not None and r["liquidation_price"] < 1860.0
    assert r["risk_per_trade_effective_pct"] > 2.0   # kaldıraç riski büyütür
