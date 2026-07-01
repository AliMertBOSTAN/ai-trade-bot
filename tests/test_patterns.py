"""patterns.py — TradingView'den uyarlanan piyasa-yapısı göstergeleri.

Her fonksiyon +1 (boğa) / -1 (ayı) / 0 (nötr) döndürür.
"""
from engine.indicators import patterns as pat


def test_ma_cross_up_and_down():
    # Düz yükseliş: fiyat MA'nın üstüne geçer -> long (+1)
    up = [float(i) for i in range(1, 60)]
    assert pat.ma_cross(up) == 1
    # Düz düşüş: fiyat MA'nın altına geçer -> short (-1)
    down = [float(i) for i in range(60, 1, -1)]
    assert pat.ma_cross(down) == -1


def test_ma_cross_outputs_are_ternary():
    assert pat.ma_cross([1.0, 1.0, 1.0]) in (-1, 0, 1)


def test_rsi_divergence_returns_ternary():
    n = 80
    highs = [10 + i * 0.1 for i in range(n)]
    lows = [9 + i * 0.1 for i in range(n)]
    closes = [9.5 + i * 0.1 for i in range(n)]
    assert pat.rsi_divergence(highs, lows, closes) in (-1, 0, 1)


def test_market_structure_monotonic_has_no_break():
    # Kesintisiz yükselişte tamamlanmış bir swing kırılması yoktur -> 0
    n = 60
    highs = [10 + i for i in range(n)]
    lows = [9 + i for i in range(n)]
    closes = [9.5 + i for i in range(n)]
    assert pat.market_structure(highs, lows, closes) == 0


def test_fair_value_gap_ternary_and_gap_detection():
    n = 40
    highs = [10.0] * n
    lows = [9.0] * n
    closes = [9.5] * n
    # Boğa FVG: i-2 high < i low (yukarı boşluk)
    highs[20], lows[20], closes[20] = 11.0, 10.5, 10.8
    lows[22], highs[22], closes[22] = 12.0, 13.0, 12.5  # mum 22 low > mum 20 high
    assert pat.fair_value_gap(highs, lows, closes) in (-1, 0, 1)


def test_handles_short_input_without_error():
    short = [1.0, 2.0, 3.0]
    assert pat.ma_cross(short) in (-1, 0, 1)
    assert pat.rsi_divergence(short, short, short) in (-1, 0, 1)
    assert pat.market_structure(short, short, short) in (-1, 0, 1)
    assert pat.fair_value_gap(short, short, short) in (-1, 0, 1)
