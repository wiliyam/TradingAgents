"""Bounded SMA paper strategies and next-bar historical simulation."""

import hashlib
import json
import math
import re
import threading
import time
import uuid
from contextlib import closing

from dashboard.broker.core import BrokerError
from dashboard.broker.risk import event


def number(value, low, high, label, integer=False):
    try:
        if isinstance(value, bool):
            raise ValueError
        n = float(value)
        if not math.isfinite(n) or not low <= n <= high or (integer and int(n) != n):
            raise ValueError
        return int(n) if integer else n
    except (ValueError, TypeError):
        raise BrokerError(f"Invalid {label}. Expected {low} to {high}.") from None


def validate_strategy(fields):
    if fields.get("mode", "paper") != "paper":
        raise BrokerError("Only paper strategies are supported.")
    name = str(fields.get("name", "SMA trend")).strip()
    key = str(fields.get("key", ""))
    if not 1 <= len(name) <= 80 or not re.fullmatch(r"(NSE|BSE):[0-9]{1,12}", key):
        raise BrokerError("Choose a name and an NSE/BSE equity instrument.")
    fast = number(fields.get("fast", 10), 2, 100, "fast period", True)
    slow = number(fields.get("slow", 30), 3, 200, "slow period", True)
    if fast >= slow:
        raise BrokerError("Fast period must be less than slow period.")
    interval = fields.get("interval", "5m")
    if interval not in ("1m", "5m", "15m", "1h", "1d"):
        raise BrokerError("Invalid strategy interval.")
    return {
        "name": name,
        "key": key,
        "mode": "paper",
        "fast": fast,
        "slow": slow,
        "interval": interval,
        "quantity": number(fields.get("quantity", 1), 1, 100000, "quantity", True),
    }


def signal(closes, cfg):
    if len(closes) < cfg["slow"]:
        return "WAIT"
    fast = sum(closes[-cfg["fast"] :]) / cfg["fast"]
    slow = sum(closes[-cfg["slow"] :]) / cfg["slow"]
    return "BUY" if fast > slow else "SELL" if fast < slow else "WAIT"


def backtest(candles, cfg, capital=1000000, fee_bps=5, slippage_bps=5):
    capital = number(capital, 100, 10000000, "capital")
    fee = number(fee_bps, 0, 500, "fee basis points") / 10000
    slip = number(slippage_bps, 0, 500, "slippage basis points") / 10000
    if not isinstance(candles, list) or not cfg["slow"] + 2 <= len(candles) <= 10000:
        raise BrokerError("Insufficient candles or more than 10000 bars.")
    previous = -1
    for bar in candles:
        if not isinstance(bar, dict):
            raise BrokerError("Invalid candle.")
        try:
            vals = [float(bar[k]) for k in ("time", "open", "high", "low", "close")]
            ts, opening, high, low, close = vals
            if (
                not all(math.isfinite(v) and v > 0 for v in vals)
                or ts <= previous
                or not low <= min(opening, close) <= max(opening, close) <= high
            ):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise BrokerError(
                "Candles must have increasing timestamps and valid OHLC prices."
            ) from None
        previous = ts
    cash = capital
    held = 0
    closes = []
    trades = []
    curve = []
    fees = 0
    peak = capital
    drawdown = 0
    pending = "WAIT"
    for bar in candles:
        side = pending
        price = float(bar["open"]) * (1 + slip if side == "BUY" else 1 - slip)
        qty = cfg["quantity"] if side == "BUY" and held == 0 else held if side == "SELL" else 0
        if qty and (side != "BUY" or qty * price * (1 + fee) <= cash):
            charge = qty * price * fee
            fees += charge
            cash += (-qty * price - charge) if side == "BUY" else qty * price - charge
            held = qty if side == "BUY" else 0
            trades.append(
                {
                    "time": bar["time"],
                    "side": side,
                    "quantity": qty,
                    "price": round(price, 4),
                    "fee": round(charge, 4),
                }
            )
        equity = cash + held * float(bar["close"])
        peak = max(peak, equity)
        drawdown = max(drawdown, (peak - equity) / peak * 100)
        curve.append({"time": bar["time"], "equity": round(equity, 2)})
        closes.append(float(bar["close"]))
        pending = signal(closes, cfg)
    return {
        "ending_equity": round(equity, 2),
        "return_pct": round((equity / capital - 1) * 100, 3),
        "max_drawdown_pct": round(drawdown, 3),
        "fees": round(fees, 2),
        "open_quantity": held,
        "trades": trades,
        "curve": curve,
        "assumptions": {"capital": capital, "fee_bps": fee * 10000, "slippage_bps": slip * 10000},
        "model": "SMA from completed bars; fills at next bar open with per-side costs. Open positions marked at last close. No intrabar fills, liquidity model or guarantee of future results.",
    }


class Automation:
    def __init__(self, engine):
        self.engine = engine
        self.ledger = engine.ledger
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None
        self.heartbeat = 0
        with closing(self.ledger.db()) as db, db:
            db.executescript("""CREATE TABLE IF NOT EXISTS strategies(id TEXT PRIMARY KEY,config TEXT NOT NULL,status TEXT NOT NULL,last_bar REAL NOT NULL DEFAULT 0,message TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS backtests(id TEXT PRIMARY KEY,created REAL NOT NULL,config TEXT NOT NULL,result TEXT NOT NULL,source TEXT NOT NULL);""")
            db.execute(
                "UPDATE strategies SET status='paused',message='Paused after service restart' WHERE status='running'"
            )

    def state(self):
        with closing(self.ledger.db()) as db:
            strategies = [
                {**dict(r), "config": json.loads(r["config"])}
                for r in db.execute("SELECT * FROM strategies ORDER BY rowid DESC")
            ]
            tests = [
                {**dict(r), "config": json.loads(r["config"]), "result": json.loads(r["result"])}
                for r in db.execute("SELECT * FROM backtests ORDER BY created DESC LIMIT 10")
            ]
        return {
            "strategies": strategies,
            "backtests": tests,
            "risk": self.ledger.risk(),
            "audit": self.ledger.audit(),
            "heartbeat": self.heartbeat,
            "real_orders_enabled": False,
        }

    def command(self, action, fields):
        with self.lock:
            if action == "risk":
                return self.ledger.set_risk(fields)
            if action == "halt":
                self.ledger.set_risk({"halted": True})
                with closing(self.ledger.db()) as db, db:
                    db.execute(
                        "UPDATE strategies SET status='paused',message='Kill switch activated'"
                    )
                return {"message": "Paper execution halted. Positions remain open."}
            if action == "strategy-save":
                cfg = validate_strategy(fields)
                if cfg["interval"] == "1d":
                    raise BrokerError(
                        "Daily bars are available for backtests only; automated strategies require an intraday interval."
                    )
                item = self.engine.instrument(cfg["key"])
                if item.get("kind") != "equity":
                    raise BrokerError("Strategies require cash equities.")
                with closing(self.ledger.db()) as db, db:
                    if db.execute("SELECT COUNT(*) FROM strategies").fetchone()[0] >= 20:
                        raise BrokerError("Maximum 20 saved strategies.")
                    sid = uuid.uuid4().hex
                    db.execute(
                        "INSERT INTO strategies(id,config,status) VALUES(?,?,?)",
                        (sid, json.dumps(cfg), "paused"),
                    )
                    event(db, "strategy_saved", {"id": sid, "config": cfg})
                return {"message": "Strategy saved paused.", "id": sid}
            if action in ("strategy-start", "strategy-pause", "strategy-delete"):
                with closing(self.ledger.db()) as db, db:
                    row = db.execute(
                        "SELECT * FROM strategies WHERE id=?", (str(fields.get("id", "")),)
                    ).fetchone()
                    if not row:
                        raise BrokerError("Strategy not found.")
                    cfg = json.loads(row["config"])
                    if action == "strategy-start":
                        if self.ledger.risk()["halted"]:
                            raise BrokerError("Release the kill switch before starting.")
                        state = self.engine.status()
                        if not state["connected"]:
                            raise BrokerError(
                                "A connected market feed is required to start automation."
                            )
                        if cfg["key"] not in {i["key"] for i in state["watchlist"]}:
                            raise BrokerError("Add the instrument to the watchlist first.")
                        for other in db.execute(
                            "SELECT * FROM strategies WHERE status='running' AND id!=?",
                            (row["id"],),
                        ):
                            if json.loads(other["config"])["key"] == cfg["key"]:
                                raise BrokerError("Only one running strategy per instrument.")
                    if action == "strategy-delete":
                        if row["status"] == "running":
                            raise BrokerError("Pause the strategy before deleting.")
                        db.execute("DELETE FROM strategies WHERE id=?", (row["id"],))
                    else:
                        db.execute(
                            "UPDATE strategies SET status=?,message=? WHERE id=?",
                            (
                                "running" if action == "strategy-start" else "paused",
                                "Awaiting evaluation"
                                if action == "strategy-start"
                                else "Paused by owner",
                                row["id"],
                            ),
                        )
                    event(db, action, {"id": row["id"]})
                return {"message": "Strategy updated."}
            raise BrokerError("Unknown automation command.")

    def run_backtest(self, fields):
        cfg = validate_strategy(fields)
        if fields.get("candles"):
            try:
                candles = (
                    json.loads(fields["candles"])
                    if isinstance(fields["candles"], str)
                    else fields["candles"]
                )
            except (ValueError, TypeError):
                raise BrokerError("Invalid imported candle JSON.") from None
            source = "Owner-imported candles; data quality not independently verified"
        else:
            data = self.engine.candles(cfg["key"], cfg["interval"])
            candles = data["candles"]
            source = data["source"]
        result = backtest(
            candles,
            cfg,
            fields.get("capital", 1000000),
            fields.get("fee_bps", 5),
            fields.get("slippage_bps", 5),
        )
        result.update(
            source=source,
            strategy=cfg,
            candle_count=len(candles),
            data_sha256=hashlib.sha256(json.dumps(candles, sort_keys=True).encode()).hexdigest(),
        )
        with closing(self.ledger.db()) as db, db:
            sid = uuid.uuid4().hex
            db.execute(
                "INSERT INTO backtests VALUES(?,?,?,?,?)",
                (sid, time.time(), json.dumps(cfg), json.dumps(result), source),
            )
            db.execute(
                "DELETE FROM backtests WHERE id NOT IN (SELECT id FROM backtests ORDER BY created DESC LIMIT 20)"
            )
            event(db, "backtest_completed", {"id": sid, "source": source})
        return {"message": "Historical simulation completed.", "result": result}

    def evaluate(self):
        self.heartbeat = time.time()
        if not self.engine.status()["connected"] or not self.engine.session_open():
            return
        with closing(self.ledger.db()) as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM strategies WHERE status='running'")]
        for row in rows:
            if self.stop_event.is_set():
                return
            cfg = json.loads(row["config"])
            try:
                data = self.engine.candles(cfg["key"], cfg["interval"])
                completed = [
                    b for b in data["candles"] if b["time"] + data["seconds"] <= time.time()
                ]
                if len(completed) < cfg["slow"]:
                    raise BrokerError("Waiting for sufficient completed candles.")
                bar = completed[-1]["time"]
                if time.time() - (bar + data["seconds"]) > max(120, data["seconds"]):
                    raise BrokerError("Historical candles are stale; waiting for current data.")
                with self.lock:
                    if self.stop_event.is_set():
                        return
                    with closing(self.ledger.db()) as db:
                        current = db.execute(
                            "SELECT * FROM strategies WHERE id=?", (row["id"],)
                        ).fetchone()
                        if (
                            not current
                            or current["status"] != "running"
                            or current["last_bar"] >= bar
                        ):
                            continue
                        position = db.execute(
                            "SELECT quantity FROM positions WHERE key=?", (cfg["key"],)
                        ).fetchone()
                    side = signal([b["close"] for b in completed], cfg)
                    held = position[0] if position else 0
                    qty = (
                        cfg["quantity"]
                        if side == "BUY" and not held
                        else held
                        if side == "SELL"
                        else 0
                    )
                    if qty:
                        rid = hashlib.sha256(f"{row['id']}:{bar}:{side}".encode()).hexdigest()[:32]
                        self.engine.paper_order(
                            {
                                "mode": "paper",
                                "key": cfg["key"],
                                "side": side,
                                "quantity": qty,
                                "request_id": rid,
                            }
                        )
                    with closing(self.ledger.db()) as db, db:
                        db.execute(
                            "UPDATE strategies SET last_bar=?,message=? WHERE id=?",
                            (
                                bar,
                                f"{side}: " + ("paper fill" if qty else "no position change"),
                                row["id"],
                            ),
                        )
                        event(
                            db,
                            "strategy_evaluated",
                            {"id": row["id"], "bar": bar, "signal": side, "quantity": qty},
                        )
            except BrokerError as exc:
                with closing(self.ledger.db()) as db, db:
                    db.execute("UPDATE strategies SET message=? WHERE id=?", (str(exc), row["id"]))

    def start(self):
        def loop():
            while not self.stop_event.is_set():
                try:
                    self.evaluate()
                except Exception:
                    # Fail closed; do not expose SDK details or continue unattended.
                    self.ledger.set_risk({"halted": True})
                self.stop_event.wait(15)

        self.thread = threading.Thread(target=loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
