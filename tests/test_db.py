"""storage/db — işlem kaydı + geçmiş temizleme testleri."""
from engine.models import TradeOrder
from engine.storage.db import Store


def _order(base="ETH"):
    return TradeOrder(mode="paper", chain_id=1, dex="uniswap-v3", base=base,
                      quote="USDC", side="BUY", amount=1.0, price=2000.0,
                      status="filled")


def test_save_and_recent(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    store.save_trade(_order("ETH"))
    store.save_trade(_order("BTC"))
    rows = store.recent_trades(10)
    assert len(rows) == 2
    assert {r["base"] for r in rows} == {"ETH", "BTC"}
    assert rows[0]["venueType"] == "dex"  # camelCase API şekli


def test_clear_trades_empties_and_reports_count(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    store.save_trade(_order("ETH"))
    store.save_trade(_order("BTC"))
    deleted = store.clear_trades()
    assert deleted == 2
    assert store.recent_trades(10) == []


def test_clear_on_empty_is_safe(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    assert store.clear_trades() == 0
