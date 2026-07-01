"""marketdata.whales — balina baskisi siniflandirma (saf, agsiz)."""
from engine.marketdata import whales


def test_pressure_buy_dominant():
    trades = [
        {"usd": 200_000, "side": "buy"},
        {"usd": 100_000, "side": "buy"},
        {"usd": 100_000, "side": "sell"},
    ]
    r = whales._pressure_from_trades(trades)
    assert r["buy_usd"] == 300_000 and r["sell_usd"] == 100_000
    assert r["buy_count"] == 2 and r["sell_count"] == 1
    assert abs(r["score"] - 0.5) < 1e-9   # (300-100)/400


def test_pressure_balanced_and_empty():
    r = whales._pressure_from_trades([{"usd": 50_000, "side": "buy"},
                                      {"usd": 50_000, "side": "sell"}])
    assert abs(r["score"]) < 1e-9
    e = whales._pressure_from_trades([])
    assert e["score"] == 0.0 and e["big_count"] == 0


def test_to_spot_helper():
    assert whales._to_spot("ETH") == "ETHUSDT"
    assert whales._to_spot("ethusdt") == "ETHUSDT"
