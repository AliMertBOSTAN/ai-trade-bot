"""Tick akışından sabit aralıklı OHLCV mum üretimi (sinyal hizalaması).

Sorun: canlı motor sinyalleri "1h kline tohumu + 8sn tick" karışımı bir seriden
üretiyordu — göstergeler (RSI-14, ADX...) tutarsız zaman adımları görüyor ve
backtest'te kanıtlanan davranış canlıya taşınmıyordu.

Çözüm: tick'ler sabit aralıklı kovalara toplanır; sinyaller yalnız KAPANMIŞ
mumlarla hesaplanır (oluşan mum karara girmez). Böylece canlı sinyal,
backtest'in bar-kapanışı semantiğiyle birebir aynı veriyi görür.
"""
from __future__ import annotations

from collections import deque

INTERVAL_MS = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
}


class CandleAggregator:
    """Tek sembol için tick → sabit aralıklı mum toplayıcı."""

    def __init__(self, interval_ms: int, maxlen: int = 400):
        self.interval_ms = max(1, int(interval_ms))
        self.candles: deque[dict] = deque(maxlen=maxlen)   # kapanmış mumlar
        self._cur: dict | None = None                      # oluşan mum

    def seed(self, klines: list[dict]) -> None:
        """Kapanmış geçmiş mumlarla ön-doldur (yalnız boşken).

        Borsa kline listesinin SON öğesi henüz oluşan mumdur — alınmaz.
        """
        if self.candles or not klines:
            return
        for c in klines[:-1]:
            try:
                self.candles.append({
                    "t": int(c["t"]),
                    "open": float(c["open"]), "high": float(c["high"]),
                    "low": float(c["low"]), "close": float(c["close"]),
                    "volume": float(c.get("volume", 0.0)),
                })
            except (KeyError, TypeError, ValueError):
                continue

    def update(self, price: float, now_ms: int, volume: float = 0.0) -> bool:
        """Bir tick işle; bu tick'le bir mum KAPANDIYSA True döner."""
        if price <= 0:
            return False
        b = int(now_ms) // self.interval_ms
        if self._cur is not None and self._cur["b"] == b:
            cur = self._cur
            cur["high"] = max(cur["high"], price)
            cur["low"] = min(cur["low"], price)
            cur["close"] = price
            cur["volume"] += volume
            return False
        closed = False
        if self._cur is not None:
            done = dict(self._cur)
            done.pop("b", None)
            self.candles.append(done)
            closed = True
        self._cur = {"b": b, "t": b * self.interval_ms,
                     "open": price, "high": price, "low": price,
                     "close": price, "volume": volume}
        return closed

    # ---- kapanmış mum serileri (sinyal beslemesi) ----
    def closes(self) -> list[float]:
        return [c["close"] for c in self.candles]

    def highs(self) -> list[float]:
        return [c["high"] for c in self.candles]

    def lows(self) -> list[float]:
        return [c["low"] for c in self.candles]

    def volumes(self) -> list[float]:
        return [c["volume"] for c in self.candles]

    def htf(self, factor: int = 4, min_buckets: int = 35
            ) -> tuple[list[float], list[float], list[float], list[float]] | None:
        """Kapanmış mumlardan üst zaman dilimi serileri (closes/highs/lows/vols).

        Son (muhtemelen eksik) kova atılır. Yetersiz geçmişte None (MTF pasif).
        """
        span = self.interval_ms * max(2, int(factor))
        buckets: list[dict] = []
        for c in self.candles:
            b = c["t"] // span
            if not buckets or buckets[-1]["b"] != b:
                buckets.append({"b": b, "close": c["close"], "high": c["high"],
                                "low": c["low"], "volume": c["volume"]})
            else:
                cur = buckets[-1]
                cur["close"] = c["close"]
                cur["high"] = max(cur["high"], c["high"])
                cur["low"] = min(cur["low"], c["low"])
                cur["volume"] += c["volume"]
        buckets = buckets[:-1]   # son kova tamamlanmamış olabilir
        if len(buckets) < min_buckets:
            return None
        return ([x["close"] for x in buckets], [x["high"] for x in buckets],
                [x["low"] for x in buckets], [x["volume"] for x in buckets])
