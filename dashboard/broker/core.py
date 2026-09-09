"""Equity quote parsing and an isolated, long-only paper ledger.

Binary field offsets follow Angel One WebSocket 2.0's quote protocol. Monetary
ledger values use integer paise. This module contains no broker order API.
"""

import math
import os
import re
import sqlite3
import struct
import time
from pathlib import Path


class BrokerError(Exception):
    """A safe, user-facing broker validation error."""


def parse_tick(data):
    if (
        not isinstance(data, bytes)
        or len(data) < 123
        or data[0] not in (2, 3)
        or data[1] not in (1, 3)
    ):
        return None
    token = data[2:27].split(b"\0", 1)[0].decode("ascii", errors="ignore")
    if not token.isdigit():
        return None

    def integer(offset):
        return struct.unpack_from("<q", data, offset)[0]

    price = integer(43) / 100
    timestamp = integer(35) / 1000
    if price <= 0 or timestamp <= 0 or timestamp > time.time() + 60:
        return None
    exchange = "NSE" if data[1] == 1 else "BSE"
    previous = integer(115) / 100
    return {
        "key": f"{exchange}:{token}",
        "exchange": exchange,
        "token": token,
        "price": price,
        "timestamp": timestamp,
        "received": time.time(),
        "sequence": integer(27),
        "volume": max(0, integer(67)),
        "open": integer(91) / 100,
        "high": integer(99) / 100,
        "low": integer(107) / 100,
        "previous_close": previous,
        "change_percent": round((price / previous - 1) * 100, 2) if previous > 0 else None,
        "source": "Angel One WebSocket",
    }


class PaperLedger:
    def __init__(self, root):
        self.path = Path(root) / "paper.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.db() as db:
            db.executescript("""PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS wallet(id INTEGER PRIMARY KEY CHECK(id=1),cash INTEGER NOT NULL);
            INSERT OR IGNORE INTO wallet VALUES(1,100000000);
            CREATE TABLE IF NOT EXISTS positions(key TEXT PRIMARY KEY,symbol TEXT,exchange TEXT,token TEXT,quantity INTEGER,cost INTEGER);
            CREATE TABLE IF NOT EXISTS trades(id TEXT PRIMARY KEY,created REAL,key TEXT,symbol TEXT,side TEXT,quantity INTEGER,price INTEGER,realized INTEGER);
            """)
        os.chmod(self.path, 0o600)

    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def fill(self, order, instrument, tick):
        if order.get("mode") != "paper":
            raise BrokerError("Real-money order placement is disabled.")
        request_id = order.get("request_id", "")
        if not isinstance(request_id, str) or not re.fullmatch(r"[a-f0-9]{32}", request_id):
            raise BrokerError("Invalid order reference. Reload and try again.")
        side = order.get("side")
        quantity = order.get("quantity")
        if side not in ("BUY", "SELL") or type(quantity) is not int or not 1 <= quantity <= 100000:
            raise BrokerError("Choose Buy or Sell and a whole quantity between 1 and 100000.")
        now = time.time()
        if (
            not tick
            or not 0 <= now - tick.get("timestamp", 0) <= 15
            or not 0 <= now - tick.get("received", 0) <= 15
        ):
            raise BrokerError(
                "Paper fills require a fresh live quote. The market may be closed or the feed disconnected."
            )
        raw = tick.get("price", 0)
        if not isinstance(raw, (float, int)) or not math.isfinite(raw) or raw <= 0:
            raise BrokerError("No valid live price is available.")
        price = round(raw * 100)
        key = instrument["key"]
        db = self.db()
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                existing = db.execute("SELECT * FROM trades WHERE id=?", (request_id,)).fetchone()
                if existing:
                    if (
                        existing["key"] != key
                        or existing["side"] != side
                        or existing["quantity"] != quantity
                    ):
                        raise BrokerError(
                            "This order reference was already used for another order."
                        )
                    return dict(existing)
                cash = db.execute("SELECT cash FROM wallet WHERE id=1").fetchone()[0]
                row = db.execute("SELECT * FROM positions WHERE key=?", (key,)).fetchone()
                held = row["quantity"] if row else 0
                cost = row["cost"] if row else 0
                total = quantity * price
                realized = 0
                if side == "BUY":
                    if total > cash:
                        raise BrokerError("Insufficient paper cash.")
                    cash -= total
                    held += quantity
                    cost += total
                else:
                    if quantity > held:
                        raise BrokerError(
                            "Paper short selling is disabled. Sell no more than your held quantity."
                        )
                    basis = round(cost * quantity / held)
                    realized = total - basis
                    cash += total
                    held -= quantity
                    cost -= basis
                db.execute("UPDATE wallet SET cash=? WHERE id=1", (cash,))
                db.execute(
                    "INSERT OR REPLACE INTO positions VALUES(?,?,?,?,?,?)",
                    (
                        key,
                        instrument["symbol"],
                        instrument["exchange"],
                        instrument["token"],
                        held,
                        cost,
                    ),
                )
                db.execute(
                    "INSERT INTO trades VALUES(?,?,?,?,?,?,?,?)",
                    (request_id, now, key, instrument["symbol"], side, quantity, price, realized),
                )
                return dict(db.execute("SELECT * FROM trades WHERE id=?", (request_id,)).fetchone())
        finally:
            db.close()

    def summary(self, ticks):
        db = self.db()
        try:
            cash = db.execute("SELECT cash FROM wallet WHERE id=1").fetchone()[0] / 100
            positions = []
            for row in db.execute("SELECT * FROM positions WHERE quantity>0"):
                item = dict(row)
                tick = ticks.get(row["key"], {})
                price = tick.get("price")
                item.update(
                    average_price=row["cost"] / 100 / row["quantity"],
                    price=price,
                    unrealized=round(price * row["quantity"] - row["cost"] / 100, 2)
                    if price is not None
                    else None,
                    quote_timestamp=tick.get("timestamp"),
                )
                positions.append(item)
            orders = [
                {
                    **dict(r),
                    "price": r["price"] / 100,
                    "realized": r["realized"] / 100,
                    "status": "FILLED (SIMULATED)",
                }
                for r in db.execute("SELECT * FROM trades ORDER BY created DESC LIMIT 100")
            ]
            realized = (
                db.execute("SELECT COALESCE(SUM(realized),0) FROM trades").fetchone()[0] / 100
            )
            return {
                "mode": "paper",
                "cash": cash,
                "starting_balance": 1000000,
                "positions": positions,
                "orders": orders,
                "realized": realized,
                "equity": round(cash + sum(p["price"] * p["quantity"] for p in positions), 2)
                if all(p["price"] is not None for p in positions)
                else None,
                "execution_model": "Latest fresh LTP; no fees, slippage, shorting or exchange execution.",
            }
        finally:
            db.close()
