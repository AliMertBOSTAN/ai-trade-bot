"""TradingView'de en popüler "geliştirilmiş" göstergeler (saf Python).

Hepsi LLM'den bağımsız, kural-tabanlı katmanın parçasıdır:

- Supertrend            : ATR tabanlı trend takip + yön
- Ichimoku Cloud        : Tenkan/Kijun/Senkou A/B
- Parabolic SAR         : trend dönüş noktaları
- Keltner Channels      : EMA ± ATR bandı
- Donchian Channels     : N-mum en yüksek/en düşük kanalı
- Awesome Oscillator    : Bill Williams momentum
- TTM Squeeze Momentum  : BB ile KC sıkışması (LazyBear)
- WaveTrend Oscillator  : LazyBear; aşırı alım/satım + crossover

OHLCV girişleri eşit uzunlukta beklenir (technical.compute_snapshot bunu
``_coerce_ohlcv`` ile garanti eder).
"""
from __future__ import annotations

from engine.indicators import technical as ta


def supertrend(highs: list[float], lows: list[float], closes: list[float],
               period: int = 10, mult: float = 3.0) -> tuple[float, float]:
    """Supertrend -> (çizgi_değeri, yön).  yön: +1 yükseliş, -1 düşüş."""
    n = len(closes)
    if n < period + 1:
        return (closes[-1] if closes else 0.0), 0.0
    trs = ta.true_range_series(highs, lows, closes)
    atr_s = ta._rma_series(trs, period)
    direction = 1.0
    final_upper = 0.0
    final_lower = 0.0
    st = closes[period]
    prev_upper = prev_lower = 0.0
    for i in range(period, n):
        hl2 = (highs[i] + lows[i]) / 2
        basic_upper = hl2 + mult * atr_s[i]
        basic_lower = hl2 - mult * atr_s[i]
        if i == period:
            final_upper, final_lower = basic_upper, basic_lower
        else:
            final_upper = (basic_upper
                           if (basic_upper < prev_upper or closes[i - 1] > prev_upper)
                           else prev_upper)
            final_lower = (basic_lower
                           if (basic_lower > prev_lower or closes[i - 1] < prev_lower)
                           else prev_lower)
        if closes[i] > final_upper:
            direction = 1.0
        elif closes[i] < final_lower:
            direction = -1.0
        st = final_lower if direction > 0 else final_upper
        prev_upper, prev_lower = final_upper, final_lower
    return st, direction


def ichimoku(highs: list[float], lows: list[float], closes: list[float],
             tenkan_p: int = 9, kijun_p: int = 26,
             senkou_p: int = 52) -> tuple[float, float, float, float]:
    """Ichimoku Cloud -> (Tenkan, Kijun, Senkou A, Senkou B)."""
    def mid(period: int) -> float:
        if len(highs) < period:
            period = len(highs)
        if period == 0:
            return 0.0
        return (max(highs[-period:]) + min(lows[-period:])) / 2

    tenkan = mid(tenkan_p)
    kijun = mid(kijun_p)
    senkou_a = (tenkan + kijun) / 2
    senkou_b = mid(senkou_p)
    return tenkan, kijun, senkou_a, senkou_b


def parabolic_sar(highs: list[float], lows: list[float],
                  step: float = 0.02, max_step: float = 0.2) -> tuple[float, float]:
    """Parabolic SAR -> (sar_değeri, yön).  yön: +1 long, -1 short."""
    n = len(highs)
    if n < 3:
        return (lows[-1] if lows else 0.0), 0.0
    up = True
    af = step
    ep = highs[0]
    sar = lows[0]
    for i in range(1, n):
        prev_sar = sar
        sar = prev_sar + af * (ep - prev_sar)
        if up:
            sar = min(sar, lows[i - 1], lows[i - 2] if i >= 2 else lows[i - 1])
            if highs[i] > ep:
                ep = highs[i]
                af = min(af + step, max_step)
            if lows[i] < sar:
                up = False
                sar = ep
                ep = lows[i]
                af = step
        else:
            sar = max(sar, highs[i - 1], highs[i - 2] if i >= 2 else highs[i - 1])
            if lows[i] < ep:
                ep = lows[i]
                af = min(af + step, max_step)
            if highs[i] > sar:
                up = True
                sar = ep
                ep = highs[i]
                af = step
    return sar, (1.0 if up else -1.0)


def keltner(highs: list[float], lows: list[float], closes: list[float],
            period: int = 20, mult: float = 2.0) -> tuple[float, float, float]:
    """Keltner Channels -> (upper, mid, lower).  mid=EMA, bant=ATR."""
    mid = ta.ema(closes[-(period * 2):] or closes, period)
    atr_v = ta.atr(highs, lows, closes, period)
    return mid + mult * atr_v, mid, mid - mult * atr_v


def donchian(highs: list[float], lows: list[float],
             period: int = 20) -> tuple[float, float, float]:
    """Donchian Channels -> (upper, mid, lower)."""
    if not highs:
        return 0.0, 0.0, 0.0
    p = min(period, len(highs))
    upper = max(highs[-p:])
    lower = min(lows[-p:])
    return upper, (upper + lower) / 2, lower


def awesome_oscillator(highs: list[float], lows: list[float],
                       fast: int = 5, slow: int = 34) -> float:
    """Awesome Oscillator (Bill Williams) = SMA5(HL2) - SMA34(HL2)."""
    if len(highs) < slow:
        return 0.0
    hl2 = [(highs[i] + lows[i]) / 2 for i in range(len(highs))]
    return ta.sma(hl2, fast) - ta.sma(hl2, slow)


def squeeze_momentum(highs: list[float], lows: list[float], closes: list[float],
                     bb_p: int = 20, bb_mult: float = 2.0,
                     kc_p: int = 20, kc_mult: float = 1.5) -> tuple[float, float]:
    """TTM Squeeze (LazyBear) -> (squeeze_on, momentum).

    squeeze_on: 1.0 = BB, KC içinde (sıkışma/patlama beklentisi), 0.0 = değil.
    momentum  : lineer regresyon temelli momentum histogramı (işaret = yön).
    """
    n = len(closes)
    if n < max(bb_p, kc_p) + 1:
        return 0.0, 0.0
    bb_mid, bb_up, bb_low, _, _ = ta.bollinger(closes, bb_p, bb_mult)
    atr_v = ta.atr(highs, lows, closes, kc_p)
    kc_mid = ta.sma(closes, kc_p)
    kc_up = kc_mid + kc_mult * atr_v
    kc_low = kc_mid - kc_mult * atr_v
    squeeze_on = 1.0 if (bb_low > kc_low and bb_up < kc_up) else 0.0

    # momentum: kapanış - (donchian orta + sma) ortalaması, lineer regresyonla
    p = min(kc_p, n)
    hh = max(highs[-p:])
    ll = min(lows[-p:])
    avg = ((hh + ll) / 2 + ta.sma(closes, p)) / 2
    series = [closes[i] - avg for i in range(n - p, n)]
    mom = _linreg_last(series)
    return squeeze_on, mom


def _linreg_last(y: list[float]) -> float:
    """y serisine en küçük kareler doğrusu uydurup son noktanın değerini döndürür."""
    m = len(y)
    if m < 2:
        return y[-1] if y else 0.0
    xs = list(range(m))
    mean_x = sum(xs) / m
    mean_y = sum(y) / m
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return mean_y
    slope = sum((xs[i] - mean_x) * (y[i] - mean_y) for i in range(m)) / denom
    intercept = mean_y - slope * mean_x
    return slope * (m - 1) + intercept


def wavetrend(highs: list[float], lows: list[float], closes: list[float],
              chan_len: int = 10, avg_len: int = 21) -> tuple[float, float]:
    """WaveTrend Oscillator (LazyBear) -> (wt1, wt2).

    wt1 ve wt2 crossover'ı al/sat tetiği; ±60 aşırı bölgelerdir.
    """
    n = len(closes)
    if n < chan_len + avg_len:
        return 0.0, 0.0
    ap = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(n)]
    esa = ta.ema_series(ap, chan_len)
    d = ta.ema_series([abs(ap[i] - esa[i]) for i in range(n)], chan_len)
    ci = [(ap[i] - esa[i]) / (0.015 * d[i]) if d[i] != 0 else 0.0 for i in range(n)]
    tci = ta.ema_series(ci, avg_len)
    wt1 = tci[-1]
    wt2 = ta.sma(tci, 4)
    return wt1, wt2
