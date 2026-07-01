"""ML sinyal modelini gerçek Binance verisiyle eğitip diske kaydeder.

Kullanım:
    python -m engine.ml.train --symbol ETHUSDT --interval 1h --limit 1000
    python -m engine.ml.train --symbol BTCUSDT --interval 4h --limit 1000 --horizon 6

Çıktı: data/ml_model.json  (sunucu açılışta otomatik yükler)
"""
from __future__ import annotations

import argparse
import os

from engine.backtest.run_live_backtest import fetch_binance, fetch_coingecko
from engine.ml.model import train_from_candles, walk_forward_models

DEFAULT_PATH = os.path.join(os.environ.get("DATA_DIR", "data"), "ml_model.json")


def main() -> None:
    p = argparse.ArgumentParser(description="ML sinyal modeli eğitimi")
    p.add_argument("--symbol", default="ETHUSDT")
    p.add_argument("--interval", default="1h")
    p.add_argument("--limit", type=int, default=1000)
    p.add_argument("--horizon", type=int, default=4, help="kaç bar sonrası tahmin")
    p.add_argument("--out", default=DEFAULT_PATH)
    p.add_argument("--source", choices=["binance", "coingecko"], default="binance")
    p.add_argument("--days", type=int, default=180)
    args = p.parse_args()

    if args.source == "binance":
        try:
            candles = fetch_binance(args.symbol, args.interval, args.limit)
        except Exception as e:
            print(f"Binance hata ({e}); CoinGecko'ya düşülüyor")
            candles = fetch_coingecko(args.symbol.replace("USDT", ""), args.days)
    else:
        candles = fetch_coingecko(args.symbol.replace("USDT", ""), args.days)

    print(f"Mum sayısı: {len(candles)}")
    if len(candles) < 120:
        raise SystemExit("Eğitim için en az 120 mum gerekli")

    # Walk-forward ile aşırı-uyum kontrolü (sızıntısız)
    wf = walk_forward_models(candles, folds=4, horizon=args.horizon)
    if wf:
        avg = sum(r["accuracy"] for r in wf) / len(wf)
        print("Walk-forward doğruluk:", [r["accuracy"] for r in wf],
              f"| ort={avg:.3f}")
    else:
        print("Walk-forward atlandı (yetersiz veri)")

    ml = train_from_candles(candles, horizon=args.horizon)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    ml.save(args.out)
    print("En etkili özellikler:",
          [(n, round(w, 3)) for n, w in ml.feature_importance()[:6]])
    print(f"Model kaydedildi -> {args.out}")


if __name__ == "__main__":
    main()
