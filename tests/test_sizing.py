"""sizing.position_sizing — risk-tabanli boyutlandirma testleri."""
from engine.sizing import position_sizing as ps


def test_risk_based_size():
    # 10000$ sermaye, %1 risk = 100$ risk; stop %5 asagida -> 100/0.05 = 2000$
    size = ps.risk_based_size(10000, 0.01, entry=100, stop_price=95)
    assert abs(size - 2000) < 1e-6


def test_atr_based_size_smaller_when_volatile():
    low_vol = ps.atr_based_size(10000, 0.01, entry=100, atr=1.0)
    high_vol = ps.atr_based_size(10000, 0.01, entry=100, atr=5.0)
    assert high_vol < low_vol  # yuksek oynaklik -> kucuk pozisyon


def test_fractional_kelly_bounds():
    k = ps.fractional_kelly(0.6, 2.0, fraction=0.5)
    assert 0.0 <= k <= 1.0
    # kayipli edge -> 0
    assert ps.fractional_kelly(0.3, 0.5) == 0.0


def test_apply_caps_limits_exposure():
    # istenen 5000 ama varlik tavani %25 * 10000 = 2500
    capped = ps.apply_caps(5000, equity_usd=10000, max_per_asset_pct=0.25)
    assert abs(capped - 2500) < 1e-6


def test_apply_caps_accounts_existing():
    capped = ps.apply_caps(5000, equity_usd=10000, existing_asset_usd=2000,
                           max_per_asset_pct=0.25)
    assert abs(capped - 500) < 1e-6  # 2500 tavan - 2000 mevcut = 500
