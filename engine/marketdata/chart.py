"""Teknik analiz chart beslemesi (lightweight-charts için).

Binance OHLCV mumlarını + motorun custom indikatör overlay serilerini
(EMA, Bollinger, Supertrend) + kural-tabanlı al/sat işaretlerini + güncel
sinyali tek bir JSON'da toplar. Anahtarlar camelCase (renderer ile hizalı).

Karar katmanı tamamen kural-tabanlıdır (LLM çağrısı YOK): endpoint sık
poll edildiğinden hızlı ve maliyetsiz olması gerekir; bu katman zaten
"custom indikatörlere göre al/sat" demektir.
"""
from __future__ import annotations

from engine.indicators import advanced as adv
from engine.indicators import technical as ta
from engine.signals import engine as sig

# Binance'te USD karşılığı olarak fiilen USDT kullanılır.
_QUOTE = "USDT"

# Wrapped/zincire-özel semboller -> Binance spot karşılığı.
_WRAPPED = {"WETH": "ETH", "WBTC": "BTC", "BTCB": "BTC",
            "WBNB": "BNB", "WMATIC": "MATIC"}


def _binance_candles(spot: str, interval: str, limit: int) -> list[dict]:
    """Binance klines; pair yoksa/başarısızsa boş liste (yedek kaynağa düşülür)."""
    from engine.marketdata import binance  # ağ; yerel import

    try:
        return binance.klines(f"{spot}{_QUOTE}", interval=interval, limit=limit)
    except Exception:
        return []


def _line(ts: list[int], values: list[float], start: int = 0) -> list[dict]:
    """ts ile hizalı (t, value) çizgi serisi; start öncesi mumları atlar."""
    return [{"t": ts[i], "value": round(values[i], 8)}
            for i in range(start, len(values))]


def chart_feed(base: str, interval: str = "1h", limit: int = 200) -> dict:
    from engine.marketdata import coingecko  # ağ; yerel import

    base = base.upper()
    spot = _WRAPPED.get(base, base)  # WETH->ETH gibi

    # 1) Binance (en iyi OHLCV)  2) CoinGecko (Binance'te olmayan tokenlar)
    candles = _binance_candles(spot, interval, limit)
    source, quote = "binance", _QUOTE
    if not candles:
        candles = coingecko.ohlc(spot, interval, limit)
        source, quote = "coingecko", "USD"

    empty = {"symbol": spot, "quote": quote, "interval": interval, "source": source,
             "candles": [], "overlays": {}, "markers": [], "signal": None,
             "note": f"{spot} için mum verisi bulunamadı (Binance + CoinGecko)"}
    if not candles:
        return empty

    ts = [c["t"] for c in candles]
    opens = [c["open"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]
    vols = [c["volume"] for c in candles]
    n = len(closes)

    # --- overlay serileri (motorun custom indikatörleri) ---
    ema_fast = ta.ema_series(closes, 12)
    ema_slow = ta.ema_series(closes, 26)

    bb_upper: list[dict] = []
    bb_mid: list[dict] = []
    bb_lower: list[dict] = []
    for i in range(19, n):  # 20-mum Bollinger ısınması
        mid, up, low, _, _ = ta.bollinger(closes[: i + 1])
        bb_mid.append({"t": ts[i], "value": round(mid, 8)})
        bb_upper.append({"t": ts[i], "value": round(up, 8)})
        bb_lower.append({"t": ts[i], "value": round(low, 8)})

    st_series = adv.supertrend_series(highs, lows, closes)
    supertrend = [{"t": ts[i], "value": round(pt[0], 8), "dir": pt[1]}
                  for i, pt in enumerate(st_series) if pt is not None]

    overlays = {
        "emaFast": _line(ts, ema_fast),
        "emaSlow": _line(ts, ema_slow),
        "bbUpper": bb_upper,
        "bbMid": bb_mid,
        "bbLower": bb_lower,
        "supertrend": supertrend,
    }

    # --- geçmiş al/sat işaretleri (kural-tabanlı, indeks -> zaman) ---
    markers = [{"t": ts[m["index"]], "action": m["action"],
                "confidence": m["confidence"], "price": closes[m["index"]]}
               for m in sig.rolling_markers(closes, highs, lows, vols)]

    # --- güncel sinyal (son mumdaki kural kararı) ---
    tech = ta.compute_snapshot(closes, highs, lows, vols)
    action, conf = sig.decide(tech)
    trend_dir = "yukarı" if tech.supertrend_dir >= 0 else "aşağı"
    rationale = (
        f"RSI={tech.rsi:.0f} · StochRSI={tech.stoch_rsi:.0f} · "
        f"ADX={tech.adx:.0f} · Supertrend={trend_dir} · "
        f"BB%B={tech.bb_pct_b:.0f} · mom={tech.momentum:.1f}%"
    )
    signal = {
        "action": action,
        "confidence": round(conf, 3),
        "source": "technical",
        "rationale": rationale,
        "price": closes[-1],
    }

    return {
        "symbol": spot,
        "quote": quote,
        "interval": interval,
        "source": source,
        "candles": candles,
        "overlays": overlays,
        "markers": markers,
        "signal": signal,
    }
