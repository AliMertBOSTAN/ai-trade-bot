"""SQLite kalıcı depolama (işlemler, sinyaller, equity eğrisi, arbitraj)."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any

_DATA_DIR = os.environ.get("DATA_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
_DB_PATH = os.path.join(_DATA_DIR, "bot.db")
_STATE_PATH = os.path.join(_DATA_DIR, "state.json")

# Şema sürümü (PRAGMA user_version). Değiştiğinde artır + _MIGRATIONS'a ekle.
_SCHEMA_VERSION = 2
# {hedef_sürüm: [SQL, ...]}. v1 baseline; v2 trades'e nonce sütunu ekler.
_MIGRATIONS: dict[int, list[str]] = {
    2: ["ALTER TABLE trades ADD COLUMN nonce INTEGER DEFAULT -1"],
}


class Store:
    def __init__(self, path: str = _DB_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._path = path
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
        self._migrate()

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

    def _migrate(self) -> None:
        """PRAGMA user_version'a göre sıralı migrasyon (idempotent)."""
        with self._lock:
            cur = self.conn.execute("PRAGMA user_version").fetchone()[0]
            if cur >= _SCHEMA_VERSION:
                return
            start = 1 if cur == 0 else cur + 1
            for target in range(start, _SCHEMA_VERSION + 1):
                for sql in _MIGRATIONS.get(target, []):
                    try:
                        self.conn.execute(sql)
                    except sqlite3.OperationalError as e:
                        # "duplicate column" gibi zaten-uygulanmış migrasyonu yoksay
                        if "duplicate column" not in str(e).lower():
                            raise
            self.conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
            self.conn.commit()

    def backup(self, keep: int = 5) -> str:
        """Veritabanını data/backups/ altına kopyalar (online backup). En yeni `keep`."""
        import glob
        import time as _time

        backup_dir = os.path.join(os.path.dirname(self._path), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        dest = os.path.join(backup_dir, f"bot-{int(_time.time()*1000)}.db")
        with self._lock:
            dst = sqlite3.connect(dest)
            try:
                self.conn.backup(dst)
            finally:
                dst.close()
        files = sorted(glob.glob(os.path.join(backup_dir, "bot-*.db")))
        for old in (files[:-keep] if keep > 0 else []):
            try:
                os.remove(old)
            except OSError:
                pass
        return dest

    def schema_version(self) -> int:
        return self.conn.execute("PRAGMA user_version").fetchone()[0]

    def save_trade(self, t) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO trades "
                "(id, ts, mode, chain_id, dex, base, quote, side, amount, price, "
                " status, tx_hash, filled_price, fee_usd, reason, signal_id, nonce) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (t.id, t.timestamp, t.mode, t.chain_id, t.dex, t.base, t.quote,
                 t.side, t.amount, t.price, t.status, t.tx_hash, t.filled_price,
                 t.fee_usd, t.reason, t.signal_id, getattr(t, "nonce", -1)))
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
        out = []
        for r in rows:
            keys = r.keys()
            out.append({
                "id": r["id"], "mode": r["mode"], "chainId": r["chain_id"],
                "dex": r["dex"], "base": r["base"], "quote": r["quote"],
                "side": r["side"], "amount": r["amount"], "price": r["price"],
                "status": r["status"], "txHash": r["tx_hash"],
                "filledPrice": r["filled_price"], "feeUsd": r["fee_usd"],
                "reason": r["reason"], "signalId": r["signal_id"],
                "venueType": "dex",
                "nonce": (r["nonce"] if "nonce" in keys and r["nonce"] is not None else -1),
                "timestamp": r["ts"],
            })
        return out

    def clear_trades(self) -> int:
        """İşlem geçmişini siler (kullanıcı isteğiyle). Silinen satır sayısını döner."""
        with self._lock:
            cur = self.conn.execute("DELETE FROM trades")
            self.conn.commit()
            return cur.rowcount

    def clear_equity(self) -> int:
        """Equity (öz sermaye) eğrisini siler — paper sıfırlamada temiz başlangıç."""
        with self._lock:
            cur = self.conn.execute("DELETE FROM equity")
            self.conn.commit()
            return cur.rowcount

    def equity_curve(self, limit: int = 500) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT ts, equity FROM equity ORDER BY ts ASC LIMIT ?", (limit,)).fetchall()
        return [{"t": r["ts"], "equity": r["equity"]} for r in rows]

    # ---- state.json (git-friendly snapshot) ----
    @property
    def state_path(self) -> str:
        return _STATE_PATH

    def save_state(self, payload: dict) -> None:
        """state.json'a atomik yazım (kısmi yazımdan korunma)."""
        with self._lock:
            os.makedirs(os.path.dirname(_STATE_PATH), exist_ok=True)
            tmp = _STATE_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, sort_keys=True)
            os.replace(tmp, _STATE_PATH)

    def load_state(self) -> dict | None:
        if not os.path.exists(_STATE_PATH):
            return None
        try:
            with open(_STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None


store = Store()
