"""TradingView'den uyarlanan pattern / piyasa-yapısı göstergeleri (saf Python).

Kullanıcının verdiği Pine scriptlerinin bot verisine (OHLCV) uyarlanmış,
LLM'siz kural katmanında kullanılabilen halleri:

- ma_cross         : SMA crossover stratejisi (yön + confirm bar)        [Pine: MovingAvg Cross]
- rsi_divergence   : pivot tabanlı DÜZENLİ boğa/ayı uyumsuzluğu          [Pine: RSI Divergence]
- market_structure : SMC (LuxAlgo) — swing BOS/CHoCH trend yönü          [Pine: Smart Money Concepts]
- fair_value_gap   : 3-mum FVG yönü (dolmamış)                            [Pine: SMC -> FVG]

Not: Supertrend zaten engine/indicators/advanced.py'de mevcuttur (sinyal = yön
değişimi). Bu modül onu tekrar etmez.

Hepsi çıktıyı sade skalere indirger (+1 boğa / -1 ayı / 0 nötr) ki kural skoruna
doğrudan ağırlıkla katılabilsin.
"""
from __future__ import annotations

from engine.indicators import technical as ta


# --------------------------------------------------------------------------- #
#  Yardımcı: pivot (swing) noktaları
# --------------------------------------------------------------------------- #
def _pivots(series: list[float], lb_left: int, lb_right: int) -> tuple[list[int], list[int]]:
    """Onaylı pivot LOW / HIGH indekslerini döndürür.

    i bir pivot low'dur: series[i], [i-lb_left, i+lb_right] penceresinin minimumu.
    pivot high benzer (maksimum). Sağda lb_right mum gerektiği için son lb_right
    mum pivot olamaz (TradingView ta.pivot* ile aynı mantık).
    """
    n = len(series)
    plows: list[int] = []
    phighs: list[int] = []
    for i in range(lb_left, n - lb_right):
        # merkez, komşularından KESİNLİKLE düşük/yüksek olmalı (düz tie -> pivot yok)
        nb = series[i - lb_left:i] + series[i + 1:i + lb_right + 1]
        if not nb:
            continue
        if series[i] < min(nb):
            plows.append(i)
        elif series[i] > max(nb):
            phighs.append(i)
    return plows, phighs


# --------------------------------------------------------------------------- #
#  1) MovingAvg Cross (Pine v6 strategy)
# --------------------------------------------------------------------------- #
def ma_cross(closes: list[float], length: int = 9, confirm: int = 1) -> int:
    """SMA crossover -> +1 (long) / -1 (short) / 0.

    Pine: fiyat `confirm` mum boyunca SMA'nın ÜSTÜNDEyse long, ALTINDAysa short.
    """
    if len(closes) < length + confirm:
        return 0
    mas = [ta.sma(closes[:i + 1], length) for i in range(len(closes) - confirm, len(closes))]
    seg = closes[-confirm:]
    if all(seg[k] > mas[k] for k in range(confirm)):
        return 1
    if all(seg[k] < mas[k] for k in range(confirm)):
        return -1
    return 0


# --------------------------------------------------------------------------- #
#  2) RSI Divergence (Pine v6) — düzenli (regular) uyumsuzluk
# --------------------------------------------------------------------------- #
def rsi_divergence(highs: list[float], lows: list[float], closes: list[float],
                   rsi_period: int = 14, lb_left: int = 5, lb_right: int = 5,
                   range_lower: int = 5, range_upper: int = 60) -> int:
    """Düzenli RSI uyumsuzluğu -> +1 boğa / -1 ayı / 0.

    Boğa: fiyat daha düşük dip (LL), RSI daha yüksek dip (HL) -> dönüş yukarı.
    Ayı : fiyat daha yüksek tepe (HH), RSI daha düşük tepe (LH) -> dönüş aşağı.
    """
    need = rsi_period + lb_left + lb_right + range_lower + 2
    if len(closes) < need:
        return 0
    rsi = ta.rsi_series(closes, rsi_period)
    rlows, rhighs = _pivots(rsi, lb_left, lb_right)

    # Boğa uyumsuzluğu — son iki RSI dip pivotu
    if len(rlows) >= 2:
        i1, i2 = rlows[-2], rlows[-1]
        if range_lower <= (i2 - i1) <= range_upper:
            if lows[i2] < lows[i1] and rsi[i2] > rsi[i1]:
                return 1

    # Ayı uyumsuzluğu — son iki RSI tepe pivotu
    if len(rhighs) >= 2:
        j1, j2 = rhighs[-2], rhighs[-1]
        if range_lower <= (j2 - j1) <= range_upper:
            if highs[j2] > highs[j1] and rsi[j2] < rsi[j1]:
                return -1
    return 0


# --------------------------------------------------------------------------- #
#  3) Smart Money Concepts (LuxAlgo) — basitleştirilmiş piyasa yapısı
# --------------------------------------------------------------------------- #
def market_structure(highs: list[float], lows: list[float], closes: list[float],
                     swing: int = 10) -> int:
    """Swing tabanlı BOS/CHoCH trend yönü -> +1 boğa / -1 ayı / 0.

    SMC mantığının sade hali: son onaylı swing high/low'a göre kapanış kırılımı.
    Kapanış son swing high'ı yukarı kırarsa boğa yapısı (BOS/CHoCH); son swing
    low'u aşağı kırarsa ayı yapısı. (Tam LuxAlgo OB/FVG/zonları değil; bot için
    aksiyon alınabilir trend yönü.)
    """
    n = len(closes)
    if n < swing * 2 + 2:
        return 0
    _, phighs = _pivots(highs, swing, swing)
    plows, _ = _pivots(lows, swing, swing)
    c = closes[-1]
    last_high = highs[phighs[-1]] if phighs else None
    last_low = lows[plows[-1]] if plows else None
    if last_high is not None and c > last_high:
        return 1
    if last_low is not None and c < last_low:
        return -1
    return 0


# --------------------------------------------------------------------------- #
#  4) Fair Value Gap (SMC) — son dolmamış 3-mum boşluğu
# --------------------------------------------------------------------------- #
def fair_value_gap(highs: list[float], lows: list[float], closes: list[float],
                   lookback: int = 20) -> int:
    """Son dolmamış 3-mum FVG yönü -> +1 boğa / -1 ayı / 0.

    Boğa FVG: low[i] > high[i-2] (yukarı boşluk) ve henüz doldurulmamış.
    Ayı  FVG: high[i] < low[i-2] (aşağı boşluk) ve henüz doldurulmamış.
    """
    n = len(closes)
    if n < 3:
        return 0
    start = max(2, n - lookback)
    for i in range(n - 1, start - 1, -1):
        # Boğa FVG
        if lows[i] > highs[i - 2]:
            gap_bottom = highs[i - 2]
            if min(lows[i:]) >= gap_bottom:   # boşluk hâlâ açık
                return 1
        # Ayı FVG
        if highs[i] < lows[i - 2]:
            gap_top = lows[i - 2]
            if max(highs[i:]) <= gap_top:
                return -1
    return 0


# --------------------------------------------------------------------------- #
#  5) Swing yapısı (Dow): Yükselen Tepe+Dip / Düşen Tepe+Dip
# --------------------------------------------------------------------------- #
def swing_trend(highs: list[float], lows: list[float],
                left: int = 3, right: int = 3) -> int:
    """Klasik trend yapısı analizi -> +1 yükseliş / -1 düşüş / 0 yatay.

    Pivot (swing) tepelerini ve diplerini bulur, son ikisini karşılaştırır:
      • Yükselen Tepe (HH) VE Yükselen Dip (HL)  -> yükseliş trendi (+1)
      • Düşen Tepe (LH)   VE Düşen Dip (LL)       -> düşüş trendi  (-1)
      • Karışık (ör. HH ama LL)                   -> 0 (belirsiz/yatay)
    """
    need = left + right + 2
    if len(highs) < need or len(lows) < need:
        return 0
    _, ph = _pivots(highs, left, right)   # tepe (high) pivot indeksleri
    pl, _ = _pivots(lows, left, right)     # dip (low) pivot indeksleri
    if len(ph) < 2 or len(pl) < 2:
        return 0
    sh = [highs[i] for i in ph[-2:]]       # son iki swing TEPE fiyatı
    sl = [lows[i] for i in pl[-2:]]         # son iki swing DİP fiyatı
    higher_high = sh[-1] > sh[-2]
    higher_low = sl[-1] > sl[-2]
    lower_high = sh[-1] < sh[-2]
    lower_low = sl[-1] < sl[-2]
    if higher_high and higher_low:
        return 1
    if lower_high and lower_low:
        return -1
    return 0
