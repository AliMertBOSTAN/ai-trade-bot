"""Gerçek geçmiş veriyle backtest çalıştırıcı.

Bir borsadan (varsayılan: Binance public klines, yedek: CoinGecko) gerçek
OHLC mum verisi çeker ve engine.backtest.backtester ile stratejiyi koşturur.
Ek bağımlılık gerektirmez (yalnızca stdlib urllib).

Kullanım:
    python -m engine.backtest.run_live_backtest --symbol ETHUSDT --interval 1h --limit 500
    python -m engine.backtest.run_live_backtest --symbol BTCUSDT --interval 4h --limit 720 --cash 25000
    python -m engine.backtest.run_live_backtest --symbol WETH --source coingecko --days 90

Çıktı: özet metrikler + isteğe bağlı equity_curve.json
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from typing import Any

from engine.backtest.backtester import run_backtest
from engine.config.settings import RiskConfig
from engine.trading.exits import ExitConfig

# CoinGecko id eşlemesi (yedek kaynak)
COINGECKO_IDS = {
    "WETH": "ethereum", "ETH": "ethereum", "ETHUSDT": "ethereum",
    "BTC": "bitcoin", "WBTC": "bitcoin", "BTCUSDT": "bitcoin",
    "ARB": "arbitrum", "OP": "optimism", "MATIC": "matic-network",
    "WMATIC": "matic-network", "BNB": "binancecoin", "WBNB": "binancecoin",
    "LINK": "chainlink", "UNI": "uniswap", "CAKE": "pancakeswap-token",
}


def _http_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "ai-trade-bot/0.1"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def fetch_binance(symbol: str, interval: str, limit: int) -> list[dict]:
    """Binance klines -> candle listesi."""
    url = (f"https://api.binance.com/api/v3/klines"
           f"?symbol={symbol.upper()}&interval={interval}&limit={min(limit, 1000)}")
    raw = _http_json(url)
    candles = []
    for k in raw:
        candles.append({
            "t": int(k[0]),
            "open": float(k[1]), "high": float(k[2]),
            "low": float(k[3]), "close": float(k[4]),
            "volume": float(k[5]),
        })
    return candles


def fetch_coingecko(symbol: str, days: int) -> list[dict]:
    """CoinGecko OHLC (yedek). days: 1/7/14/30/90/180/365."""
    cid = COINGECKO_IDS.get(symbol.upper())
    if not cid:
        raise ValueError(f"CoinGecko id bilinmiyor: {symbol}")
    url = (f"https://api.coingecko.com/api/v3/coins/{cid}/ohlc"
           f"?vs_currency=usd&days={days}")
    raw = _http_json(url)
    candles = []
    for o in raw:
        candles.append({
            "t": int(o[0]),
            "open": float(o[1]), "high": float(o[2]),
            "low": float(o[3]), "close": float(o[4]),
            "volume": 0.0,
        })
    return candles


def main() -> None:
    p = argparse.ArgumentParser(description="Gerçek veriyle backtest")
    p.add_argument("--symbol", default="ETHUSDT",
                   help="Binance: ETHUSDT/BTCUSDT; CoinGecko: WETH/BTC ...")
    p.add_argument("--source", choices=["binance", "coingecko"], default="binance")
    p.add_argument("--interval", default="1h", help="Binance interval: 1h/4h/1d")
    p.add_argument("--limit", type=int, default=500, help="Binance mum sayısı")
    p.add_argument("--days", type=int, default=90, help="CoinGecko gün sayısı")
    p.add_argument("--cash", type=float, default=10000.0)
    p.add_argument("--min-confidence", type=float, default=0.60)
    p.add_argument("--stop", type=float, default=0.05)
    p.add_argument("--take", type=float, default=0.10)
    p.add_argument("--exit-style", choices=["fixed", "atr"], default="fixed",
                   help="fixed: sabit SL/TP · atr: canlı-eşdeğer (trailing+cooldown)")
    p.add_argument("--trail-mult", type=float, default=2.5,
                   help="ATR trailing stop çarpanı (exit-style=atr)")
    p.add_argument("--atr-stop-mult", type=float, default=2.0,
                   help="İlk ATR stop çarpanı (exit-style=atr)")
    p.add_argument("--cooldown", type=int, default=0,
                   help="Pozisyon kapanışı sonrası yeni alım için bekleme (bar)")
    p.add_argument("--risk-pct", type=float, default=0.0,
                   help="İşlem başına sermaye riski (örn. 0.01) — ATR boyut tavanı")
    p.add_argument("--htf-filter", choices=["off", "ema"], default="off",
                   help="Üst-TF (4x) EMA trendi aşağıyken yeni alım engelle")
    p.add_argument("--allow-short", action="store_true",
                   help="Çift yön: SELL sinyali pozisyon yokken SHORT açar "
                        "(backtest/perp simülasyonu; spot DEX'te yapılamaz)")
    p.add_argument("--min-edge", type=float, default=0.0,
                   help="Beklenen hareket / tur maliyeti alt oranı (örn. 2.0; 0=kapalı)")
    p.add_argument("--compare", action="store_true",
                   help="Aynı veride fixed ve atr modlarını yan yana karşılaştır")
    p.add_argument("--save", default="", help="equity_curve'u bu JSON'a yaz")
    args = p.parse_args()

    print(f"Veri çekiliyor: {args.source} {args.symbol} ...")
    try:
        if args.source == "binance":
            candles = fetch_binance(args.symbol, args.interval, args.limit)
        else:
            candles = fetch_coingecko(args.symbol, args.days)
    except Exception as e:
        print(f"[!] {args.source} başarısız ({e}); CoinGecko'ya geçiliyor...")
        candles = fetch_coingecko(args.symbol.replace("USDT", ""), args.days)

    if len(candles) < 40:
        raise SystemExit(f"Yetersiz mum: {len(candles)} (en az 40 gerekli)")

    base = args.symbol.upper().replace("USDT", "")
    risk = RiskConfig(min_confidence=args.min_confidence,
                      stop_loss_pct=args.stop, take_profit_pct=args.take,
                      min_edge_ratio=args.min_edge)
    exit_cfg = ExitConfig(atr_stop_mult=args.atr_stop_mult,
                          trail_mult=args.trail_mult)

    def _run(style: str) -> dict:
        return run_backtest(candles, base, "USD", args.cash, risk,
                            args.interval, exit_style=style, exit_cfg=exit_cfg,
                            cooldown_bars=args.cooldown, risk_pct=args.risk_pct,
                            htf_filter=args.htf_filter,
                            allow_short=args.allow_short)

    first, last = candles[0]["close"], candles[-1]["close"]
    buy_hold = (last - first) / first * 100

    if args.compare:
        # Aynı veri üzerinde eski (fixed) ve yeni (atr) modu yan yana ölç.
        a = _run("fixed")
        b = _run("atr")
        print("\n" + "=" * 64)
        print(f"  KARŞILAŞTIRMA  {base}/USD  ({len(candles)} mum, "
              f"al-tut {buy_hold:+.2f}%)")
        print("=" * 64)
        rows = [
            ("Toplam getiri %", "total_return_pct", "+.2f"),
            ("Maks. düşüş %", "max_drawdown_pct", ".2f"),
            ("Kazanma oranı", "win_rate", ".2f"),
            ("Profit factor", "profit_factor", ".2f"),
            ("Sharpe (yıllık)", "sharpe", ".2f"),
            ("Kapanan işlem", "num_closed_trades", "d"),
            ("Son equity $", "final_equity_usd", ",.2f"),
        ]
        print(f"  {'Metrik':<18}{'fixed (eski)':>16}{'atr (yeni)':>16}")
        for label, key, fmt in rows:
            print(f"  {label:<18}{format(a[key], fmt):>16}{format(b[key], fmt):>16}")
        print(f"  Çıkış dağılımı (atr): {b['exit_breakdown']}")
        print("=" * 64)
        r = b
    else:
        r = _run(args.exit_style)
        print("\n" + "=" * 52)
        print(f"  BACKTEST  {base}/USD  ({len(candles)} mum, {args.source}, "
              f"exit={args.exit_style})")
        print("=" * 52)
        print(f"  Başlangıç fiyatı : {first:,.2f}")
        print(f"  Bitiş fiyatı     : {last:,.2f}")
        print(f"  İşlem sayısı     : {len(r['trades'])}")
        print(f"  Toplam getiri    : {r['total_return_pct']:+.2f}%")
        print(f"  Al-tut (buy&hold): {buy_hold:+.2f}%")
        print(f"  Maks. düşüş      : {r['max_drawdown_pct']:.2f}%")
        print(f"  Kazanma oranı    : {r['win_rate'] * 100:.1f}%")
        print(f"  Sharpe (yıllık)  : {r['sharpe']:.2f}")
        print(f"  Son equity       : ${r['final_equity_usd']:,.2f}")
        if r.get("exit_breakdown"):
            print(f"  Çıkış dağılımı   : {r['exit_breakdown']}")
        print("=" * 52)
        edge = r["total_return_pct"] - buy_hold
        print(f"  Strateji al-tut'a karşı: {edge:+.2f}% "
              f"({'üstün' if edge > 0 else 'altında'})")

    if args.save:
        with open(args.save, "w") as f:
            json.dump({"meta": {"symbol": base, "source": args.source},
                       "metrics": {k: v for k, v in r.items()
                                   if k not in ("trades", "equity_curve")},
                       "equity_curve": r["equity_curve"],
                       "trades": r["trades"]}, f, indent=2)
        print(f"  -> kaydedildi: {args.save}")


if __name__ == "__main__":
    main()
