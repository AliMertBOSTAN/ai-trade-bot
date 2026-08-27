"""Kaldıraçlı backtest testleri — likidasyon bariyeri ve maliyet modeli."""
from __future__ import annotations

import pytest

from engine.backtest import leveraged as LB


def _sabit(n: int, r: float) -> list[float]:
    return [r] * n


def test_equity_egrisi_hem_dict_hem_sayi_kabul_eder():
    a = LB.equity_returns([{"equity": 100.0}, {"equity": 110.0}])
    b = LB.equity_returns([100.0, 110.0])
    assert a == b == [pytest.approx(0.1)]


def test_sifir_bolme_korumasi():
    assert LB.equity_returns([0.0, 100.0, 110.0]) == [pytest.approx(0.1)]


def test_kaldirac_getiriyi_carpar():
    r = LB.apply_leverage([0.10], 3, funding_per_bar=0.0, taker_fee=0.0)
    assert r["total_return_pct"] == pytest.approx(30.0, abs=0.01)


def test_likidasyon_mutlak_bariyerdir():
    """Bir kez likide olduysa sonraki kazançlar sermayeyi GERİ GETİRMEZ."""
    rets = [-0.5, +10.0, +10.0]          # 3x ile ilk bar likidasyon
    r = LB.apply_leverage(rets, 3, funding_per_bar=0.0, taker_fee=0.0)
    assert r["liquidated"] is True
    assert r["liquidation_bar"] == 0
    assert r["final_multiple"] == 0.0
    assert r["total_return_pct"] == -100.0


def test_kaldiracsizken_ayni_barlar_likide_olmaz():
    r = LB.apply_leverage([-0.5, +10.0], 1, funding_per_bar=0.0, taker_fee=0.0)
    assert r["liquidated"] is False and r["total_return_pct"] > 0


def test_oynaklik_suruklenmesi_kaldirakta_buyur():
    """+%10 / -%10 salınımı: kaldıraç arttıkça kayıp hızlanır (drag)."""
    rets = [0.10, -0.10] * 20
    x1 = LB.apply_leverage(rets, 1, funding_per_bar=0.0, taker_fee=0.0)
    x5 = LB.apply_leverage(rets, 5, funding_per_bar=0.0, taker_fee=0.0)
    assert x5["total_return_pct"] < x1["total_return_pct"] < 0


def test_funding_yalnizca_pozisyondayken_islenir():
    rets = [0.0, 0.0, 0.01, 0.0]          # yalnızca 1 bar pozisyonda
    r = LB.apply_leverage(rets, 2, funding_per_bar=0.001, taker_fee=0.0)
    assert r["in_position_bars"] == 1
    assert r["funding_cost_pct"] == pytest.approx(0.2, abs=1e-6)   # 0.001*2*1


def test_komisyon_bar_basina_degil_islem_basina():
    rets = _sabit(100, 0.001)
    az = LB.apply_leverage(rets, 1, n_trades=1, funding_per_bar=0.0)
    cok = LB.apply_leverage(rets, 1, n_trades=10, funding_per_bar=0.0)
    assert cok["fee_cost_pct"] == pytest.approx(10 * az["fee_cost_pct"])
    assert az["fee_cost_pct"] < 1.0       # 1 işlem, bar sayısından bağımsız


def test_komisyon_kaldiracla_buyur():
    rets = _sabit(10, 0.001)
    a = LB.apply_leverage(rets, 1, n_trades=5, funding_per_bar=0.0)
    b = LB.apply_leverage(rets, 4, n_trades=5, funding_per_bar=0.0)
    assert b["fee_cost_pct"] == pytest.approx(4 * a["fee_cost_pct"])


def test_bos_egri_cokmez():
    assert LB.leverage_sweep([], levels=(1, 2))["bars"] == 0


def test_sweep_ilk_likide_olan_kaldiraci_isaretler():
    """%1'lik 50 bar yükseliş, sonra -%57 çakılma.

    1× hayatta kalır; 2× (-%114) likide olur. `first_liquidating_leverage`
    likide olan EN DÜŞÜK kaldıracı bildirir — kullanıcının görmesi gereken sayı.
    """
    egri = [100 * (1.01 ** i) for i in range(50)] + [70.0]
    sw = LB.leverage_sweep(egri, levels=(1, 2, 5, 10),
                           funding_per_bar=0.0, taker_fee=0.0)
    assert sw["first_liquidating_leverage"] == 2.0
    ayakta = [r for r in sw["rows"] if not r["liquidated"]]
    assert [r["leverage"] for r in ayakta] == [1.0]


def test_sweep_likide_olan_kaldiraci_en_iyi_secmez():
    egri = [100.0, 110.0, 60.0]           # sert çakılma
    sw = LB.leverage_sweep(egri, levels=(1, 3), funding_per_bar=0.0, taker_fee=0.0)
    en_iyi = next(r for r in sw["rows"] if r["leverage"] == sw["best_leverage"])
    assert en_iyi["liquidated"] is False


def test_hedef_olasilik_siniri():
    assert LB.growth_probability_bound(100, 420000) == pytest.approx(1 / 4200)
    assert LB.growth_probability_bound(100, 50) == 1.0


def test_gereken_bar_sayisi():
    assert LB.bars_needed(4200, 0.10) == pytest.approx(87.5, abs=0.5)
    assert LB.bars_needed(4200, 0.0) is None      # getiri yoksa asla
    assert LB.bars_needed(0.5, 0.1) is None       # hedef zaten altında
