#!/usr/bin/env python3
"""Bulut-taraflı piyasa taraması — bilgisayar KAPALI olsa da çalışır.

ai-trade-bot projesinden kurtarılan parçalar:
  • engine/indicators/{technical,advanced,patterns}.py  → 47 alanlı TechnicalSnapshot
  • engine/strategy/regime.py                          → rejim tespiti
  • engine/marketdata/hyperliquid.py                   → perp bağlamları (funding/OI)
Hepsi saf stdlib; bulut konteynerinde harici bağımlılık gerekmez.

Veri kaynakları (bulut egress'inden erişilebilir olduğu ölçülenler):
  • Hyperliquid  api.hyperliquid.xyz/info   → mum, funding, open interest
  • Binance aynası data-api.binance.vision  → spot klines (api.binance.com 451 veriyor)

Kullanım:
  python3 cloud_scan.py --top 12 --min-vol 20000000
  python3 cloud_scan.py --symbols BTC,ETH,SOL --tf 1h,4h
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

# scripts/ altindan kosuldugunda Python repo kokunu sys.path'e koymaz; ekle.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.indicators.technical import compute_snapshot
from engine.marketdata import hyperliquid as hl
from engine.strategy.regime import detect_regime

HL_URL = "https://api.hyperliquid.xyz/info"
BINANCE_MIRROR = "https://data-api.binance.vision/api/v3/klines"
UA = "ai-trade-bot-cloud/1.0 (+public-data)"

TF_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


# ---------------------------------------------------------------- veri çekme
def hl_post(payload: dict, timeout: float = 20.0):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        HL_URL, data=data, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def hl_candles(coin: str, interval: str = "1h", bars: int = 300) -> dict:
    """Hyperliquid mumları → {highs, lows, closes, volumes}."""
    step = TF_MS.get(interval, 3_600_000)
    end = int(time.time() * 1000)
    start = end - step * (bars + 5)
    raw = hl_post({"type": "candleSnapshot",
                   "req": {"coin": coin, "interval": interval,
                           "startTime": start, "endTime": end}})
    if not raw:
        return {}
    return {
        "highs": [float(c["h"]) for c in raw],
        "lows": [float(c["l"]) for c in raw],
        "closes": [float(c["c"]) for c in raw],
        "volumes": [float(c["v"]) for c in raw],
        "last_ts": raw[-1]["t"],
        "bars": len(raw),
    }


def binance_candles(symbol: str, interval: str = "1h", bars: int = 300) -> dict:
    """Binance aynasından spot klines — HL'de olmayan/ince sembollerde çapraz kontrol."""
    url = f"{BINANCE_MIRROR}?symbol={symbol}&interval={interval}&limit={bars}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = json.load(r)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return {}
    if not raw:
        return {}
    return {
        "highs": [float(k[2]) for k in raw],
        "lows": [float(k[3]) for k in raw],
        "closes": [float(k[4]) for k in raw],
        "volumes": [float(k[5]) for k in raw],
        "last_ts": raw[-1][0],
        "bars": len(raw),
    }


# ---------------------------------------------------------------- skorlama
def score(snap, ctx: dict | None = None) -> tuple[int, list[str]]:
    """47 indikatörden ağırlıklı bir yön skoru (-100..+100) + gerekçeler.

    Ağırlıklar kasıtlı olarak sade ve okunur: her biri neden-gösterilebilir
    olsun diye. Bu, bir 'al/sat' emri değil, dikkat sıralamasıdır.
    """
    pts: list[tuple[str, int]] = []

    # trend yapısı
    pts.append(("supertrend", 12 * snap.supertrend_dir))
    pts.append(("psar", 6 * snap.psar_dir))
    pts.append(("ma_cross", 6 * snap.ma_cross_dir))
    pts.append(("smc_yapisi", 10 * snap.smc_trend))
    pts.append(("swing(Dow)", 8 * snap.swing_trend))
    pts.append(("ema_dizilim", 8 if snap.ema_fast > snap.ema_slow else -8))

    # momentum
    pts.append(("macd", 8 if snap.macd > snap.macd_signal else -8))
    if snap.rsi >= 70:
        pts.append(("rsi_asiri_alim", -6))
    elif snap.rsi <= 30:
        pts.append(("rsi_asiri_satim", 6))
    else:
        pts.append(("rsi_nötr", 4 if snap.rsi > 50 else -4))
    pts.append(("wavetrend", 5 if snap.wavetrend1 > snap.wavetrend2 else -5))
    pts.append(("awesome", 4 if snap.awesome > 0 else -4))
    pts.append(("rsi_div", 7 * snap.rsi_div))

    # konum / oynaklık
    if snap.bb_pct_b > 1.0:
        pts.append(("bb_üst_kirilim", -5))
    elif snap.bb_pct_b < 0.0:
        pts.append(("bb_alt_kirilim", 5))
    pts.append(("fvg", 5 * snap.fvg_bias))

    # ichimoku bulut konumu
    cloud_top = max(snap.ichimoku_senkou_a, snap.ichimoku_senkou_b)
    cloud_bot = min(snap.ichimoku_senkou_a, snap.ichimoku_senkou_b)
    if snap.price > cloud_top:
        pts.append(("ichimoku_bulut_üstü", 7))
    elif snap.price < cloud_bot:
        pts.append(("ichimoku_bulut_altı", -7))

    # trend gücü çarpanı
    total = sum(p for _, p in pts)
    if snap.adx < 20:
        total = int(total * 0.6)          # zayıf trend → skoru sönümle
        pts.append(("adx<20_sönümleme", 0))

    # funding aşırılığı (kalabalık pozisyon = ters risk)
    if ctx:
        f = ctx.get("funding_pct") or 0.0
        if f > 0.01:
            total -= 8
            pts.append(("funding_long_kalabalık", -8))
        elif f < -0.01:
            total += 8
            pts.append(("funding_short_kalabalık", 8))

    total = int(max(-100, min(100, total)))   # gösterge yönleri float dönebilir
    drivers = sorted((p for p in pts if p[1] != 0),
                     key=lambda x: -abs(x[1]))[:6]
    return total, [f"{n}{'+' if v > 0 else ''}{int(v)}" for n, v in drivers]


def label(s: int) -> str:
    if s >= 40:
        return "GÜÇLÜ YUKARI"
    if s >= 15:
        return "yukarı eğilim"
    if s <= -40:
        return "GÜÇLÜ AŞAĞI"
    if s <= -15:
        return "aşağı eğilim"
    return "nötr / kararsız"


# ---------------------------------------------------------------- tarama
def analyze(coin: str, tfs: list[str], ctx: dict | None) -> dict | None:
    out = {"symbol": coin, "tf": {}}
    for tf in tfs:
        c = hl_candles(coin, tf, bars=300)
        src = "hyperliquid"
        if not c or c["bars"] < 60:
            c = binance_candles(f"{coin}USDT", tf, bars=300)
            src = "binance-mirror"
        if not c or c["bars"] < 60:
            continue
        snap = compute_snapshot(c["closes"], c["highs"], c["lows"], c["volumes"])
        sc, drivers = score(snap, ctx)
        out["tf"][tf] = {
            "source": src,
            "bars": c["bars"],
            "price": round(snap.price, 6),
            "score": sc,
            "label": label(sc),
            "regime": detect_regime(snap),
            "rsi": round(snap.rsi, 1),
            "adx": round(snap.adx, 1),
            "atr_pct": round(snap.atr / snap.price * 100, 2) if snap.price else None,
            "bb_pct_b": round(snap.bb_pct_b, 2),
            "supertrend_dir": snap.supertrend_dir,
            "drivers": drivers,
        }
    if not out["tf"]:
        return None

    # MTF uzlaşma: tüm zaman dilimleri aynı yöne mi bakıyor?
    scores = [v["score"] for v in out["tf"].values()]
    agree = all(s > 0 for s in scores) or all(s < 0 for s in scores)
    out["consensus_score"] = round(sum(scores) / len(scores))
    out["mtf_agree"] = agree
    out["label"] = label(out["consensus_score"])
    if ctx:
        out["funding_pct"] = round(ctx.get("funding_pct") or 0.0, 4)
        out["open_interest_usd"] = round(ctx.get("open_interest_usd") or 0.0)
        out["volume_usd_24h"] = round(ctx.get("volume_usd") or 0.0)
        out["change_pct_24h"] = ctx.get("change_pct_24h")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=10, help="hacme göre ilk N perp")
    ap.add_argument("--min-vol", type=float, default=20_000_000,
                    help="min 24s notional hacim (USD)")
    ap.add_argument("--symbols", type=str, default="",
                    help="virgüllü liste; verilirse --top yoksayılır")
    ap.add_argument("--tf", type=str, default="1h,4h")
    ap.add_argument("--json-out", type=str, default="")
    args = ap.parse_args()

    tfs = [t.strip() for t in args.tf.split(",") if t.strip()]

    ctxs = hl.perp_contexts()
    by_sym = {c["symbol"]: c for c in ctxs}
    print(f"Hyperliquid evreni: {len(ctxs)} perp", file=sys.stderr)

    if args.symbols:
        coins = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        elig = [c for c in ctxs if (c.get("volume_usd") or 0) >= args.min_vol]
        elig.sort(key=lambda c: -(c.get("volume_usd") or 0))
        coins = [c["symbol"] for c in elig[: args.top]]

    print(f"Taranıyor: {', '.join(coins)}", file=sys.stderr)

    results = []
    for coin in coins:
        try:
            r = analyze(coin, tfs, by_sym.get(coin))
            if r:
                results.append(r)
                print(f"  ✓ {coin:<8} {r['consensus_score']:+4d}  {r['label']}",
                      file=sys.stderr)
            else:
                print(f"  – {coin:<8} veri yok", file=sys.stderr)
        except Exception as e:                    # tek sembol hatası taramayı kesmez
            print(f"  ! {coin:<8} hata: {type(e).__name__}: {e}", file=sys.stderr)
        time.sleep(0.25)                          # nazik rate-limit

    results.sort(key=lambda r: -abs(r["consensus_score"]))
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "timeframes": tfs,
        "universe_size": len(ctxs),
        "scanned": len(results),
        "results": results,
    }
    out = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"\nYazıldı: {args.json_out}", file=sys.stderr)
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
