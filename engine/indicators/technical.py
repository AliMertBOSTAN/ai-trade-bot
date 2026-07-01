"""Teknik göstergeler (saf Python, bağımlılık yok).

Bu modül LLM'den BAĞIMSIZ, klasik/kural-tabanlı gösterge katmanıdır.
Trade'de yaygın kullanılan göstergeler: trend (EMA/SMA/MACD/ADX),
momentum (RSI/Stochastic/StochRSI/CCI/Williams %R/ROC), oynaklık
(Bollinger/ATR) ve hacim (OBV/VWAP/MFI).

TradingView'de popüler "geliştirilmiş" göstergeler (Supertrend, Ichimoku,
Parabolic SAR, Keltner/Donchian, Awesome Oscillator, TTM Squeeze, WaveTrend)
``engine/indicators/advanced.py`` dosyasındadır.

Tüm fonksiyonlar OHLCV verisini kullanır; yalnızca kapanışlar mevcutsa
high/low yerine close, hacim yerine 0 kullanılarak güvenli şekilde
"close-only" moduna düşülür (canlı DEX akışı gibi).
"""
from __future__ import annotations

import math

from engine.models import TechnicalSnapshot

# --------------------------------------------------------------------------- #
#  Yardımcılar
# --------------------------------------------------------------------------- #


def sma(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    w = values[-period:]
    return sum(w) / len(w)


def stdev(values: list[float], period: int) -> float:
    w = values[-period:]
    if len(w) < 2:
        return 0.0
    m = sum(w) / len(w)
    var = sum((v - m) ** 2 for v in w) / len(w)
    return math.sqrt(var)


def ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    k = 2 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


def ema_series(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def _rma_series(values: list[float], period: int) -> list[float]:
    """Wilder'ın yumuşatması (RSI/ATR/ADX bunu kullanır)."""
    if not values:
        return []
    out = [values[0]]
    a = 1 / period
    for v in values[1:]:
        out.append(v * a + out[-1] * (1 - a))
    return out


# --------------------------------------------------------------------------- #
#  Momentum
# --------------------------------------------------------------------------- #


def rsi(values: list[float], period: int = 14) -> float:
    if len(values) < period + 1:
        return 50.0
    gains, losses = 0.0, 0.0
    for i in range(-period, 0):
        diff = values[i] - values[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def rsi_series(values: list[float], period: int = 14) -> list[float]:
    """StochRSI için RSI dizisi (Wilder yumuşatması)."""
    if len(values) < period + 1:
        return [50.0] * len(values)
    out: list[float] = [50.0] * period
    gains = [max(values[i] - values[i - 1], 0.0) for i in range(1, len(values))]
    losses = [max(values[i - 1] - values[i], 0.0) for i in range(1, len(values))]
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
        if avg_l == 0:
            out.append(100.0)
        else:
            rs = avg_g / avg_l
            out.append(100 - (100 / (1 + rs)))
    return out


def stoch_rsi(values: list[float], period: int = 14) -> float:
    """0-100 arası normalize StochRSI (TradingView'de çok kullanılır)."""
    rs = rsi_series(values, period)
    w = rs[-period:]
    if len(w) < 2:
        return 50.0
    lo, hi = min(w), max(w)
    if hi - lo == 0:
        return 50.0
    return (rs[-1] - lo) / (hi - lo) * 100


def macd(values: list[float], fast: int = 12, slow: int = 26,
         signal: int = 9) -> tuple[float, float]:
    if len(values) < slow:
        return 0.0, 0.0
    fast_s = ema_series(values, fast)
    slow_s = ema_series(values, slow)
    macd_line = [f - s for f, s in zip(fast_s, slow_s)]
    signal_line = ema(macd_line[-signal * 3:] or macd_line, signal)
    return macd_line[-1], signal_line


def momentum(values: list[float], period: int = 10) -> float:
    if len(values) <= period:
        return 0.0
    return (values[-1] - values[-period - 1]) / values[-period - 1] * 100


def roc(values: list[float], period: int = 12) -> float:
    """Rate of Change (%)."""
    return momentum(values, period)


def stochastic(highs: list[float], lows: list[float], closes: list[float],
               k_period: int = 14, d_period: int = 3) -> tuple[float, float]:
    """Stochastic Oscillator -> (%K, %D)."""
    if len(closes) < k_period:
        return 50.0, 50.0
    ks: list[float] = []
    start = max(k_period, len(closes) - (k_period + d_period))
    for i in range(start, len(closes) + 1):
        hh = max(highs[i - k_period:i])
        ll = min(lows[i - k_period:i])
        c = closes[i - 1]
        ks.append(50.0 if hh == ll else (c - ll) / (hh - ll) * 100)
    k = ks[-1] if ks else 50.0
    d = sum(ks[-d_period:]) / min(len(ks), d_period) if ks else 50.0
    return k, d


def cci(highs: list[float], lows: list[float], closes: list[float],
        period: int = 20) -> float:
    """Commodity Channel Index."""
    if len(closes) < period:
        return 0.0
    tp = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(len(closes))]
    w = tp[-period:]
    ma = sum(w) / period
    md = sum(abs(x - ma) for x in w) / period
    if md == 0:
        return 0.0
    return (tp[-1] - ma) / (0.015 * md)


def williams_r(highs: list[float], lows: list[float], closes: list[float],
               period: int = 14) -> float:
    """Williams %R (-100..0)."""
    if len(closes) < period:
        return -50.0
    hh = max(highs[-period:])
    ll = min(lows[-period:])
    if hh == ll:
        return -50.0
    return (hh - closes[-1]) / (hh - ll) * -100


# --------------------------------------------------------------------------- #
#  Oynaklık
# --------------------------------------------------------------------------- #


def bollinger(values: list[float], period: int = 20,
              mult: float = 2.0) -> tuple[float, float, float, float, float]:
    """Bollinger Bands -> (mid, upper, lower, %B, bandwidth%)."""
    mid = sma(values, period)
    sd = stdev(values, period)
    upper = mid + mult * sd
    lower = mid - mult * sd
    pct_b = 50.0 if upper == lower else (values[-1] - lower) / (upper - lower) * 100
    bw = 0.0 if mid == 0 else (upper - lower) / mid * 100
    return mid, upper, lower, pct_b, bw


def true_range_series(highs: list[float], lows: list[float],
                      closes: list[float]) -> list[float]:
    trs: list[float] = []
    for i in range(len(closes)):
        if i == 0:
            trs.append(highs[i] - lows[i])
        else:
            trs.append(max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            ))
    return trs


def atr(highs: list[float], lows: list[float], closes: list[float],
        period: int = 14) -> float:
    """Average True Range (Wilder)."""
    if len(closes) < 2:
        return 0.0
    trs = true_range_series(highs, lows, closes)
    return _rma_series(trs, period)[-1]


# --------------------------------------------------------------------------- #
#  Trend gücü
# --------------------------------------------------------------------------- #


def adx(highs: list[float], lows: list[float], closes: list[float],
        period: int = 14) -> tuple[float, float, float]:
    """ADX / DMI -> (ADX, +DI, -DI). Trend gücü filtresi olarak kullanılır."""
    n = len(closes)
    if n < period * 2:
        return 0.0, 0.0, 0.0
    plus_dm, minus_dm, tr = [], [], []
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(up if (up > down and up > 0) else 0.0)
        minus_dm.append(down if (down > up and down > 0) else 0.0)
        tr.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        ))
    atr_s = _rma_series(tr, period)
    pdm_s = _rma_series(plus_dm, period)
    mdm_s = _rma_series(minus_dm, period)
    dx: list[float] = []
    for a, p, m in zip(atr_s, pdm_s, mdm_s):
        if a == 0:
            dx.append(0.0)
            continue
        pdi = 100 * p / a
        mdi = 100 * m / a
        s = pdi + mdi
        dx.append(0.0 if s == 0 else 100 * abs(pdi - mdi) / s)
    adx_v = _rma_series(dx, period)[-1] if dx else 0.0
    last_atr = atr_s[-1] or 1e-9
    plus_di = 100 * pdm_s[-1] / last_atr
    minus_di = 100 * mdm_s[-1] / last_atr
    return adx_v, plus_di, minus_di


# --------------------------------------------------------------------------- #
#  Hacim
# --------------------------------------------------------------------------- #


def obv(closes: list[float], volumes: list[float]) -> float:
    """On-Balance Volume."""
    if not volumes or len(volumes) != len(closes):
        return 0.0
    o = 0.0
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            o += volumes[i]
        elif closes[i] < closes[i - 1]:
            o -= volumes[i]
    return o


def vwap(highs: list[float], lows: list[float], closes: list[float],
         volumes: list[float], period: int = 20) -> float:
    """Rolling VWAP (son `period` mum)."""
    if not volumes or sum(volumes[-period:]) == 0:
        return closes[-1] if closes else 0.0
    pv = 0.0
    vol = 0.0
    for i in range(max(0, len(closes) - period), len(closes)):
        tp = (highs[i] + lows[i] + closes[i]) / 3
        pv += tp * volumes[i]
        vol += volumes[i]
    return pv / vol if vol else (closes[-1] if closes else 0.0)


def mfi(highs: list[float], lows: list[float], closes: list[float],
        volumes: list[float], period: int = 14) -> float:
    """Money Flow Index (hacim ağırlıklı RSI)."""
    if not volumes or len(closes) < period + 1:
        return 50.0
    pos, neg = 0.0, 0.0
    for i in range(len(closes) - period, len(closes)):
        tp = (highs[i] + lows[i] + closes[i]) / 3
        tp_prev = (highs[i - 1] + lows[i - 1] + closes[i - 1]) / 3
        mf = tp * volumes[i]
        if tp > tp_prev:
            pos += mf
        elif tp < tp_prev:
            neg += mf
    if neg == 0:
        return 100.0
    return 100 - (100 / (1 + pos / neg))


# --------------------------------------------------------------------------- #
#  Anlık görüntü
# --------------------------------------------------------------------------- #


def _coerce_ohlcv(
    closes: list[float],
    highs: list[float] | None,
    lows: list[float] | None,
    volumes: list[float] | None,
) -> tuple[list[float], list[float], list[float]]:
    """High/low/volume yoksa close-only moduna güvenli düşür."""
    h = highs if highs and len(highs) == len(closes) else list(closes)
    l = lows if lows and len(lows) == len(closes) else list(closes)
    v = volumes if volumes and len(volumes) == len(closes) else [0.0] * len(closes)
    return h, l, v


def compute_snapshot(
    closes: list[float],
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    volumes: list[float] | None = None,
) -> TechnicalSnapshot:
    """Tüm göstergeleri hesaplayıp tek bir TechnicalSnapshot döndürür.

    OHLCV verilirse hacim/oynaklık göstergeleri gerçek veriyle, yalnızca
    kapanışlar verilirse güvenli yaklaşımla hesaplanır.
    """
    # advanced.py / patterns.py döngüsel import'tan kaçınmak için yerel import
    from engine.indicators import advanced as adv
    from engine.indicators import patterns as pat

    highs, lows, volumes = _coerce_ohlcv(closes, highs, lows, volumes)
    price = closes[-1] if closes else 0.0

    macd_v, macd_sig = macd(closes)
    bb_mid, bb_up, bb_low, bb_pct_b, bb_bw = bollinger(closes)
    st_k, st_d = stochastic(highs, lows, closes)
    adx_v, plus_di, minus_di = adx(highs, lows, closes)
    atr_v = atr(highs, lows, closes)

    # Gelişmiş (TradingView) göstergeler
    st_val, st_dir = adv.supertrend(highs, lows, closes)
    tenkan, kijun, senkou_a, senkou_b = adv.ichimoku(highs, lows, closes)
    psar_v, psar_dir = adv.parabolic_sar(highs, lows)
    kc_up, kc_mid, kc_low = adv.keltner(highs, lows, closes)
    dc_up, dc_mid, dc_low = adv.donchian(highs, lows)
    ao_v = adv.awesome_oscillator(highs, lows)
    sq_on, sq_mom = adv.squeeze_momentum(highs, lows, closes)
    wt1, wt2 = adv.wavetrend(highs, lows, closes)

    # Pattern / piyasa-yapısı (TradingView'den uyarlanan)
    ma_x = pat.ma_cross(closes)
    rsi_d = pat.rsi_divergence(highs, lows, closes)
    smc = pat.market_structure(highs, lows, closes)
    fvg = pat.fair_value_gap(highs, lows, closes)
    swing = pat.swing_trend(highs, lows)   # Dow yapısı: HH+HL / LH+LL

    return TechnicalSnapshot(
        # --- klasik ---
        rsi=rsi(closes),
        ema_fast=ema(closes[-50:] or closes, 12),
        ema_slow=ema(closes[-50:] or closes, 26),
        macd=macd_v,
        macd_signal=macd_sig,
        momentum=momentum(closes),
        price=price,
        sma_20=sma(closes, 20),
        roc=roc(closes),
        stoch_k=st_k,
        stoch_d=st_d,
        stoch_rsi=stoch_rsi(closes),
        cci=cci(highs, lows, closes),
        williams_r=williams_r(highs, lows, closes),
        bb_upper=bb_up,
        bb_lower=bb_low,
        bb_mid=bb_mid,
        bb_pct_b=bb_pct_b,
        bb_bandwidth=bb_bw,
        atr=atr_v,
        adx=adx_v,
        plus_di=plus_di,
        minus_di=minus_di,
        obv=obv(closes, volumes),
        vwap=vwap(highs, lows, closes, volumes),
        mfi=mfi(highs, lows, closes, volumes),
        # --- gelişmiş / TradingView ---
        supertrend=st_val,
        supertrend_dir=st_dir,
        ichimoku_tenkan=tenkan,
        ichimoku_kijun=kijun,
        ichimoku_senkou_a=senkou_a,
        ichimoku_senkou_b=senkou_b,
        psar=psar_v,
        psar_dir=psar_dir,
        keltner_upper=kc_up,
        keltner_lower=kc_low,
        donchian_upper=dc_up,
        donchian_lower=dc_low,
        awesome=ao_v,
        squeeze_on=sq_on,
        squeeze_momentum=sq_mom,
        wavetrend1=wt1,
        wavetrend2=wt2,
        # --- pattern / piyasa-yapısı ---
        ma_cross_dir=float(ma_x),
        rsi_div=float(rsi_d),
        smc_trend=float(smc),
        fvg_bias=float(fvg),
        swing_trend=float(swing),
    )
