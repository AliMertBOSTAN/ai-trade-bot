"""SQLite kalıcı depolama (işlemler, sinyaller, equity eğrisi, arbitraj)."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any

_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                        "data", "bot.db")


class Store:
    def __init__(self, path: str = _DB_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id TEXT PRIMARY KEY, ts INTEGER, mode TEXT, chain_id INTEGER,
                dex TEXT, base TEXT, quote TEXT, side TEXT, amount REAL,
                price REAL, status TEXT, tx_hash TEXT, filled_price REAL,
                fee_usd REAL, reason TEXT, signal_id TEXT
            );
            CREATE TABLE IF NOT EXISTS signals (
                id TEXT PRIMARY KEY, ts INTEGER, chain_id INTEGER, base TEXT,
                quote TEXT, action TEXT, confidence REAL, source TEXT,
                rationale TEXT, payload TEXT
            );
            CREATE TABLE IF NOT EXISTS equity (
                ts INTEGER PRIMARY KEY, equity REAL
            );
            CREATE TABLE IF NOT EXISTS arbitrage (
                id TEXT PRIMARY KEY, ts INTEGER, base TEXT, buy_chain INTEGER,
                sell_chain INTEGER, spread_pct REAL, est_net_profit_usd REAL,
                payload TEXT
            );
            """
        )
        self.conn.commit()

    def save_trade(self, t) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (t.id, t.timestamp, t.mode, t.chain_id, t.dex, t.base, t.quote,
                 t.side, t.amount, t.price, t.status, t.tx_hash, t.filled_price,
                 t.fee_usd, t.reason, t.signal_id))
            self.conn.commit()

    def save_signal(self, s) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO signals VALUES (?,?,?,?,?,?,?,?,?,?)",
                (s.id, s.timestamp, s.chain_id, s.base, s.quote, s.action,
                 s.confidence, s.source, s.rationale, json.dumps(s.to_dict())))
            self.conn.commit()

    def save_equity(self, ts: int, equity: float) -> None:
        with self._lock:
            self.conn.execute("INSERT OR REPLACE INTO equity VALUES (?,?)", (ts, equity))
            self.conn.commit()

    def save_arbitrage(self, o) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO arbitrage VALUES (?,?,?,?,?,?,?,?)",
                (o.id, o.timestamp, o.base, o.buy_chain, o.sell_chain,
                 o.spread_pct, o.est_net_profit_usd, json.dumps(o.to_dict())))
            self.conn.commit()

    def recent_trades(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM trades ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def equity_curve(self, limit: int = 500) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT ts, equity FROM equity ORDER BY ts ASC LIMIT ?", (limit,)).fetchall()
        return [{"t": r["ts"], "equity": r["equity"]} for r in rows]


store = Store()
