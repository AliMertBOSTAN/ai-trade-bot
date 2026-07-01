"""Sembol parametrelerini gerçek veriyle ayarla ve kaydet.

    python -m engine.tuning.run_tune --symbol ETHUSDT --interval 1h --limit 1000
    python -m engine.tuning.run_tune --symbol BTCUSDT --tune-exits
"""
from __future__ import annotations

import argparse

from engine.backtest.run_live_backtest import fetch_binance, fetch_coingecko
from engine.config.settings import RiskConfig
from engine.tuning.optimizer import optimize_symbol


def main() -> None:
    p = argparse.ArgumentParser(description="Otomatik parametre ayarı")
    p.add_argument("--symbol", default="ETHUSDT")
    p.add_argument("--interval", default="1h")
    p.add_argument("--limit", type=int, default=1000)
    p.add_argument("--cash", type=float, default=10000.0)
    p.add_argument("--tune-exits", action="store_true",
                   help="stop_loss/take_profit ızgarasını da tara")
    args = p.parse_args()

    base = args.symbol.replace("USDT", "").replace("USD", "") or args.symbol
    try:
        candles = fetch_binance(args.symbol, args.interval, args.limit)
    except Exception as e:
        print(f"Binance hata ({e}); CoinGecko'ya düşülüyor")
        candles = fetch_coingecko(base, 180)
    print(f"Mum: {len(candles)}")

    stop_grid = [0.03, 0.05, 0.08] if args.tune_exits else None
    take_grid = [0.06, 0.10, 0.15] if args.tune_exits else None
    res = optimize_symbol(candles, base, "USD", args.cash, RiskConfig(),
                          interval=args.interval, stop_grid=stop_grid,
                          take_grid=take_grid)
    print("Sonuç:", res)
    if res.get("ok"):
        print(f"En iyi: min_conf={res['min_confidence']} "
              f"SL={res['stop_loss_pct']} TP={res['take_profit_pct']} "
              f"| robust={res['robust']} avg_oos={res['avg_oos_return_pct']}%")


if __name__ == "__main__":
    main()
