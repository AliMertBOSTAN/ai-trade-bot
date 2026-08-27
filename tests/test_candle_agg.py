"""CandleAggregator (sinyal hizalaması) + ATR-modu auto-tune testleri."""
import random

from engine.config.settings import RiskConfig
from engine.marketdata.candle_agg import INTERVAL_MS, CandleAggregator
from engine.tuning import optimizer

H = 3600_000


def test_aggregator_builds_ohlc_from_ticks():
    agg = CandleAggregator(H)
    # 1. mum: 3 tick (100 -> 105 -> 99); kapanış 2. kovaya geçişte gelir
    assert agg.update(100.0, 0) is False
    assert agg.update(105.0, 10 * 60_000) is False
    assert agg.update(99.0, 50 * 60_000) is False
    closed = agg.update(101.0, H + 1)      # yeni kova -> önceki mum kapandı
    assert closed is True
    c = list(agg.candles)[-1]
    assert c["open"] == 100.0 and c["high"] == 105.0
    assert c["low"] == 99.0 and c["close"] == 99.0


def test_aggregator_seed_excludes_forming_candle():
    agg = CandleAggregator(H)
    klines = [{"t": i * H, "open": 1.0, "high": 2.0, "low": 0.5,
               "close": 1.5, "volume": 10.0} for i in range(50)]
    agg.seed(klines)
    assert len(agg.candles) == 49          # son (oluşan) kline alınmaz
    agg.seed(klines)                        # dolu iken tekrar tohumlanmaz
    assert len(agg.candles) == 49


def test_aggregator_htf_resample():
    agg = CandleAggregator(H)
    klines = [{"t": i * H, "open": 100 + i, "high": 101 + i, "low": 99 + i,
               "close": 100 + i, "volume": 1.0} for i in range(200)]
    agg.seed(klines)
    htf = agg.htf(4)
    assert htf is not None
    closes, highs, lows, vols = htf
    assert len(closes) >= 35 and len(closes) == len(highs) == len(lows) == len(vols)
    # yükselen seride üst-TF kapanışları da yükselir
    assert closes[-1] > closes[0]
    # yetersiz geçmişte None (MTF pasif)
    small = CandleAggregator(H)
    small.seed(klines[:40])
    assert small.htf(4) is None


def test_interval_map_has_common_intervals():
    for iv in ("1m", "5m", "15m", "1h", "4h", "1d"):
        assert iv in INTERVAL_MS and INTERVAL_MS[iv] > 0


def _candles(n=400, drift=0.25, noise=1.2, seed=3):
    rng = random.Random(seed)
    price = 100.0
    out = []
    for i in range(n):
        price = max(1.0, price + drift + rng.uniform(-noise, noise))
        out.append({"t": i * H, "open": price, "high": price * 1.005,
                    "low": price * 0.995, "close": price, "volume": 1000.0})
    return out


def test_optimize_symbol_atr_and_store(tmp_path, monkeypatch):
    """ATR-modu auto-tune: küçük ızgarayla koşar, kaydeder, mode=atr işaretler."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    grid = {"min_confidence": [0.3, 0.5], "trail_mult": [2.5],
            "atr_stop_mult": [2.0], "cooldown_bars": [0, 8], "risk_pct": [0.0]}
    res = optimizer.optimize_symbol_atr(_candles(), "ETH", "USD", 10000.0,
                                        RiskConfig(min_confidence=0.3),
                                        interval="1h", param_grid=grid)
    assert res["ok"] is True and res["mode"] == "atr"
    assert 0.0 <= res["min_confidence"] <= 1.0
    t = optimizer.get_tuned("ETH")
    assert t is not None and t.get("mode") == "atr"
