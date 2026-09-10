"""Transaction-local paper risk limits and audit events; monetary limits are INR."""

import json
import math
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from dashboard.broker.core import BrokerError

DEFAULTS = {
    "halted": False,
    "max_order_value": 250000,
    "max_position_cost": 500000,
    "max_invested_capital": 1000000,
    "max_daily_realized_loss": 10000,
    "max_daily_orders": 100,
}


def setup(db):
    db.executescript("""CREATE TABLE IF NOT EXISTS risk_settings(id INTEGER PRIMARY KEY CHECK(id=1),value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS audit_events(id INTEGER PRIMARY KEY AUTOINCREMENT,created REAL NOT NULL,kind TEXT NOT NULL,detail TEXT NOT NULL);""")
    db.execute("INSERT OR IGNORE INTO risk_settings VALUES(1,?)", (json.dumps(DEFAULTS),))


def read(db):
    return {
        **DEFAULTS,
        **json.loads(db.execute("SELECT value FROM risk_settings WHERE id=1").fetchone()[0]),
    }


def event(db, kind, detail):
    db.execute(
        "INSERT INTO audit_events(created,kind,detail) VALUES(?,?,?)",
        (time.time(), kind, json.dumps(detail)),
    )


def update(db, fields):
    values = read(db)
    if set(fields) - set(DEFAULTS):
        raise BrokerError("Unknown risk setting.")
    for key, value in fields.items():
        if key == "halted":
            if type(value) is not bool:
                raise BrokerError("Invalid halt state.")
        else:
            try:
                value = float(value)
            except (ValueError, TypeError):
                raise BrokerError("Risk limits must be positive numbers.") from None
            if not math.isfinite(value) or not 1 <= value <= 10000000:
                raise BrokerError("Risk limits must be between 1 and 10000000.")
            if key == "max_daily_orders":
                if int(value) != value or value > 10000:
                    raise BrokerError("Daily order limit must be a whole number up to 10000.")
                value = int(value)
        values[key] = value
    db.execute("UPDATE risk_settings SET value=? WHERE id=1", (json.dumps(values),))
    event(db, "risk_updated", values)
    return values


def check(db, side, total, cost):
    limits = read(db)
    if limits["halted"]:
        raise BrokerError("Paper execution is halted by the kill switch.")
    if total / 100 > limits["max_order_value"]:
        raise BrokerError("Maximum paper order value exceeded.")
    day = (
        datetime.now(ZoneInfo("Asia/Kolkata"))
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .timestamp()
    )
    count, realized = db.execute(
        "SELECT COUNT(*),COALESCE(SUM(realized),0) FROM trades WHERE created>=?", (day,)
    ).fetchone()
    if count >= limits["max_daily_orders"]:
        raise BrokerError("Daily paper order limit reached.")
    if side == "BUY":
        if realized / 100 <= -limits["max_daily_realized_loss"]:
            raise BrokerError("Daily realized loss limit reached; new buys are blocked.")
        if (cost + total) / 100 > limits["max_position_cost"]:
            raise BrokerError("Maximum position cost exceeded.")
        invested = db.execute("SELECT COALESCE(SUM(cost),0) FROM positions").fetchone()[0]
        if (invested + total) / 100 > limits["max_invested_capital"]:
            raise BrokerError("Maximum invested capital exceeded.")
