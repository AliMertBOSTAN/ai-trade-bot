#!/usr/bin/env python3
"""Coklu-varlik piyasa taramasi — kripto (genis) + ABD hisse. Bulutta kosar.

cloud_scan.py'nin genisletilmis hali. Skorlama mantigi TEK yerde durur:
cloud_scan.score/label buradan import edilir, kopyalanmaz.

Kapsam:
  KRIPTO  iki asamali huni
          1) Binance aynasi /ticker/24hr -> ~490 USDT cifti, hacimle sirala
          2) ilk N'i 1h+4h mumlarla derin tara; HL'de karsiligi varsa
             funding / open interest ile zenginlestir
  HISSE   iki asamali huni
          1) S&P500 (GitHub CSV) U Nasdaq-100 (Nasdaq API) birlesimi,
             Nasdaq screener'dan tek cagrida fiyat+hacim -> dolar hacmiyle sirala
          2) ilk N'i Yahoo 60m+1d mumlarla derin tara

Tum kaynaklar bulut egress'inden erisilebilir olculdu; anahtar gerekmez.
api.binance.com KULLANILMAZ (451 cografi blok) — data-api.binance.vision kullanilir.

Kullanim:
  python3 scripts/market_scan.py --asset all   --top 150 --json-out out.json
  python3 scripts/market_scan.py --asset crypto --top 80
  python3 scripts/market_scan.py --asset stocks --symbols NVDA,AAPL,TSLA
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.indicators.technical import compute_snapshot
from engine.marketdata import hyperliquid as hl
from engine.strategy.regime import detect_regime

from cloud_scan import label, score            # tek kaynak: skorlama kopyalanmaz

UA = "ai-trade-bot-cloud/1.1 (+public-data)"
# Nasdaq uclari bot UA'sini kapatiyor (olculdu: RemoteDisconnected) -> tarayici UA'si
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
BINANCE = "https://data-api.binance.vision/api/v3"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart"
SP500_CSV = ("https://raw.githubusercontent.com/datasets/"
             "s-and-p-500-companies/main/data/constituents.csv")
NDX_URL = "https://api.nasdaq.com/api/quote/list-type/nasdaq100"
SCREENER = ("https://api.nasdaq.com/api/screener/stocks"
            "?tableonly=true&limit=25&offset=0&download=true")

# kaldiracli token / stablecoin ciftleri teknik analiz icin anlamsiz
_BAD_SUFFIX = ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")
_STABLE = {"USDC", "FDUSD", "TUSD", "BUSD", "DAI", "USDP", "EURI", "AEUR",
           "USD1", "XUSD", "EUR", "GBP", "TRY", "BRL", "ARS", "JPY", "PLN",
           "RON", "ZAR", "MXN", "COP", "CZK", "UAH", "NGN", "IDRT", "RUB"}
MIN_BARS = 60


def _get(url: str, timeout: float = 25.0, ua: str = UA) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": ua,
                                               "Accept": "application/json, text/csv, */*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _jget(url: str, timeout: float = 25.0, ua: str = UA):
    return json.loads(_get(url, timeout, ua))


def _jget_retry(url: str, timeout: float = 45.0, ua: str = BROWSER_UA,
                attempts: int = 3):
    """Nasdaq uclari tek tek gevsek; geri cekilerek yeniden dene."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            return _jget(url, timeout, ua)
        except Exception as e:                       # noqa: BLE001 - agir gevseklik
            last = e
            if i < attempts - 1:
                time.sleep(1.5 * (i + 1))
    raise last if last else RuntimeError("bilinmeyen hata")


# ------------------------------------------------------------------ KRIPTO
def crypto_universe(top: int, min_vol_usd: float) -> list[dict]:
    """Asama 1: tum USDT ciftleri, 24s quote hacmine gore siralanmis."""
    rows = _jget(f"{BINANCE}/ticker/24hr", timeout=40)
    out = []
    for r in rows:
        s = r["symbol"]
        if not s.endswith("USDT") or s.endswith(_BAD_SUFFIX):
            continue
        base = s[:-4]
        if base in _STABLE or not base:
            continue
        try:
            qv = float(r["quoteVolume"])
        except (KeyError, ValueError):
            continue
        if qv < min_vol_usd:
            continue
        out.append({"symbol": base, "pair": s, "volume_usd": qv,
                    "change_pct_24h": float(r.get("priceChangePercent") or 0)})
    out.sort(key=lambda x: -x["volume_usd"])
    return out[:top]


def binance_klines(pair: str, interval: str, bars: int = 300) -> dict:
    try:
        raw = _jget(f"{BINANCE}/klines?symbol={pair}&interval={interval}&limit={bars}")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError):
        return {}
    if not raw or len(raw) < MIN_BARS:
        return {}
    return {"highs": [float(k[2]) for k in raw], "lows": [float(k[3]) for k in raw],
            "closes": [float(k[4]) for k in raw], "volumes": [float(k[5]) for k in raw],
            "last_ts": raw[-1][0], "bars": len(raw), "source": "binance-mirror"}


# ------------------------------------------------------------------ HISSE
def stock_universe(top: int, min_dollar_vol: float) -> list[dict]:
    """Asama 1: S&P500 U NDX100, Nasdaq screener'dan dolar hacmiyle siralanmis."""
    tickers: set[str] = set()
    try:
        txt = _get(SP500_CSV, timeout=30).decode("utf-8", "ignore")
        for row in csv.DictReader(io.StringIO(txt)):
            sym = (row.get("Symbol") or "").strip().upper()
            if sym:
                tickers.add(sym)
    except Exception as e:
        print(f"  ! S&P500 listesi alinamadi: {e}", file=sys.stderr)
    try:
        d = _jget_retry(NDX_URL, timeout=40)
        data = d.get("data") or {}
        rows = (data.get("data") or {}).get("rows") or data.get("rows") or []
        for r in rows:
            sym = (r.get("symbol") or "").strip().upper()
            if sym:
                tickers.add(sym)
    except Exception as e:
        print(f"  ! Nasdaq-100 listesi alinamadi: {e}", file=sys.stderr)

    if not tickers:
        return []

    stats: dict[str, dict] = {}
    try:
        d = _jget_retry(SCREENER, timeout=60)
        for r in (d.get("data") or {}).get("rows", []):
            sym = (r.get("symbol") or "").strip().upper()
            if sym not in tickers:
                continue
            try:
                px = float(str(r.get("lastsale", "")).replace("$", "").replace(",", ""))
                vol = float(str(r.get("volume", "0")).replace(",", "") or 0)
            except ValueError:
                continue
            stats[sym] = {"symbol": sym, "price": px, "volume_usd": px * vol,
                          "sector": r.get("sector") or "", "name": r.get("name") or ""}
    except Exception as e:
        print(f"  ! screener alinamadi: {e}", file=sys.stderr)

    out = [v for v in stats.values() if v["volume_usd"] >= min_dollar_vol]
    out.sort(key=lambda x: -x["volume_usd"])
    return out[:top]


def _stooq_daily(symbol: str) -> dict:
    """Yedek gunluk kaynak. stooq.com engelli, stooq.pl acik (olculdu)."""
    url = f"https://stooq.pl/q/d/l/?s={symbol.lower()}.us&i=d"
    try:
        txt = _get(url, timeout=25).decode("utf-8", "ignore")
    except Exception:
        return {}
    rows = []
    for row in csv.DictReader(io.StringIO(txt)):
        try:
            rows.append((row["Data"] if "Data" in row else row["Date"],
                         float(row["Otwarcie"] if "Otwarcie" in row else row["Open"]),
                         float(row["Najwyzszy"] if "Najwyzszy" in row else row["High"]),
                         float(row["Najnizszy"] if "Najnizszy" in row else row["Low"]),
                         float(row["Zamkniecie"] if "Zamkniecie" in row else row["Close"]),
                         float(row.get("Wolumen") or row.get("Volume") or 0)))
        except (KeyError, ValueError):
            continue
    if len(rows) < MIN_BARS:
        return {}
    rows = rows[-400:]
    last = datetime.strptime(rows[-1][0], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return {"highs": [r[2] for r in rows], "lows": [r[3] for r in rows],
            "closes": [r[4] for r in rows], "volumes": [r[5] for r in rows],
            "last_ts": int(last.timestamp() * 1000), "bars": len(rows),
            "source": "stooq"}


def yahoo_candles(symbol: str, interval: str, attempts: int = 3) -> dict:
    """Yahoo OHLCV. 429 paylasimli IP'de sik gorulur -> geri cekilerek yeniden
    dene, query1/query2 arasinda donusumlu git; gunlukte Stooq'a dus."""
    rng = {"60m": "3mo", "1h": "3mo", "1d": "1y", "1wk": "5y"}.get(interval, "1y")
    iv = "60m" if interval == "1h" else interval
    rows: list = []
    for i in range(attempts):
        host = "query1" if i % 2 == 0 else "query2"
        url = (f"https://{host}.finance.yahoo.com/v8/finance/chart/"
               f"{symbol}?range={rng}&interval={iv}")
        try:
            d = _jget(url, timeout=30)
            res = (d.get("chart") or {}).get("result")
            if not res:
                return {}
            r = res[0]
            q = r["indicators"]["quote"][0]
            ts = r.get("timestamp") or []
            rows = [(t, o, h, l, c, v) for t, o, h, l, c, v
                    in zip(ts, q.get("open", []), q.get("high", []), q.get("low", []),
                           q.get("close", []), q.get("volume", []))
                    if None not in (o, h, l, c)]
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 503, 502) and i < attempts - 1:
                time.sleep(1.5 * (i + 1) + 0.4)
                continue
            break
        except (urllib.error.URLError, TimeoutError, ValueError,
                KeyError, IndexError):
            break

    if len(rows) < MIN_BARS:
        return _stooq_daily(symbol) if iv == "1d" else {}
    return {"highs": [r[2] for r in rows], "lows": [r[3] for r in rows],
            "closes": [r[4] for r in rows],
            "volumes": [float(r[5] or 0) for r in rows],
            "last_ts": rows[-1][0] * 1000, "bars": len(rows), "source": "yahoo"}


def _px(x: float) -> float:
    """Kurus alti tokenlerde sabit ondalik anlamli basamaklari yiyor
    (PEPE 0.000005144 -> 0.000005). 6 ANLAMLI basamaga yuvarla."""
    if not x:
        return 0.0
    return float(f"{x:.6g}") if abs(x) < 1 else round(x, 6)


# ------------------------------------------------------------------ analiz
def analyze(name: str, tfs: list[str], fetch, ctx: dict | None) -> dict | None:
    out = {"symbol": name, "tf": {}}
    for tf in tfs:
        c = fetch(tf)
        if not c:
            continue
        snap = compute_snapshot(c["closes"], c["highs"], c["lows"], c["volumes"])
        sc, drivers = score(snap, ctx)
        out["tf"][tf] = {
            "source": c["source"], "bars": c["bars"],
            "price": _px(snap.price), "score": sc, "label": label(sc),
            "regime": detect_regime(snap), "rsi": round(snap.rsi, 1),
            "adx": round(snap.adx, 1),
            "atr_pct": round(snap.atr / snap.price * 100, 2) if snap.price else None,
            "bb_pct_b": round(snap.bb_pct_b, 2),
            "last_bar_utc": datetime.fromtimestamp(
                c["last_ts"] / 1000, timezone.utc).isoformat(timespec="minutes"),
            "drivers": drivers,
        }
    if not out["tf"]:
        return None
    scores = [v["score"] for v in out["tf"].values()]
    out["consensus_score"] = round(sum(scores) / len(scores))
    out["mtf_agree"] = all(s > 0 for s in scores) or all(s < 0 for s in scores)
    out["label"] = label(out["consensus_score"])
    if ctx:
        for k in ("funding_pct", "open_interest_usd", "volume_usd",
                  "change_pct_24h", "sector", "name"):
            if ctx.get(k) is not None:
                out[k] = ctx[k]
    return out


def run_pool(items, worker, workers: int = 6):
    results = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(worker, it): it for it in items}
        for f in as_completed(futs):
            try:
                r = f.result()
            except Exception as e:
                print(f"  ! {futs[f]}: {type(e).__name__}: {e}", file=sys.stderr)
                continue
            if r:
                results.append(r)
                print(f"  ✓ {r['symbol']:<12} {r['consensus_score']:+4d}  {r['label']}",
                      file=sys.stderr)
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", choices=["crypto", "stocks", "all"], default="all")
    ap.add_argument("--top", type=int, default=150)
    ap.add_argument("--min-vol", type=float, default=2_000_000,
                    help="kripto: min 24s quote hacmi (USD). Bu bir taban: asil "
                         "secimi --top yapar. Tabanin altinda indikatorler gurultu.")
    ap.add_argument("--min-dollar-vol", type=float, default=50_000_000,
                    help="hisse: min gunluk dolar hacmi")
    ap.add_argument("--symbols", type=str, default="")
    ap.add_argument("--crypto-tf", type=str, default="1h,4h")
    ap.add_argument("--stock-tf", type=str, default="1h,1d")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--json-out", type=str, default="")
    args = ap.parse_args()

    ctf = [t.strip() for t in args.crypto_tf.split(",") if t.strip()]
    stf = [t.strip() for t in args.stock_tf.split(",") if t.strip()]
    picked = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    payload: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "asset_classes": {},
    }

    # ---------------- kripto ----------------
    if args.asset in ("crypto", "all"):
        t0 = time.time()
        if picked:
            uni = [{"symbol": s, "pair": f"{s}USDT", "volume_usd": None} for s in picked]
        else:
            uni = crypto_universe(args.top, args.min_vol)
        hl_ctx = {c["symbol"]: c for c in hl.perp_contexts()}
        print(f"\nKRIPTO: {len(uni)} sembol (HL zenginlestirme: "
              f"{len(hl_ctx)} perp mevcut)", file=sys.stderr)

        def cw(u):
            ctx = dict(u)
            h = hl_ctx.get(u["symbol"])
            if h:
                ctx["funding_pct"] = round(h.get("funding_pct") or 0.0, 4)
                ctx["open_interest_usd"] = round(h.get("open_interest_usd") or 0.0)
            return analyze(u["symbol"], ctf,
                           lambda tf, p=u["pair"]: binance_klines(p, tf), ctx)

        res = run_pool(uni, cw, args.workers)
        res.sort(key=lambda r: -abs(r["consensus_score"]))
        payload["asset_classes"]["crypto"] = {
            "universe_considered": len(uni), "scanned": len(res),
            "timeframes": ctf, "seconds": round(time.time() - t0, 1),
            "results": res,
        }

    # ---------------- hisse ----------------
    if args.asset in ("stocks", "all"):
        t0 = time.time()
        if picked:
            uni = [{"symbol": s, "volume_usd": None} for s in picked]
        else:
            uni = stock_universe(args.top, args.min_dollar_vol)
        print(f"\nHISSE: {len(uni)} sembol", file=sys.stderr)

        def sw(u):
            return analyze(u["symbol"], stf,
                           lambda tf, s=u["symbol"]: yahoo_candles(s, tf), dict(u))

        # Yahoo paylasimli IP'de hizli sikar; hisse tarafinda daha az paralellik
        res = run_pool(uni, sw, max(2, args.workers // 2))
        res.sort(key=lambda r: -abs(r["consensus_score"]))
        payload["asset_classes"]["stocks"] = {
            "universe_considered": len(uni), "scanned": len(res),
            "timeframes": stf, "seconds": round(time.time() - t0, 1),
            "results": res,
        }

    out = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"\nYazildi: {args.json_out}", file=sys.stderr)
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
