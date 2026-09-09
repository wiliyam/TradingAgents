"""Single shared Angel One feed; private credentials and read-only broker REST calls."""

import json
import os
import re
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pyotp
import requests
import websocket

from dashboard.broker.core import BrokerError, PaperLedger, parse_tick

API = "https://apiconnect.angelone.in"
MASTER = "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json"
INTERVALS = {
    "1m": ("ONE_MINUTE", 60, 5),
    "5m": ("FIVE_MINUTE", 300, 20),
    "15m": ("FIFTEEN_MINUTE", 900, 30),
    "1h": ("ONE_HOUR", 3600, 60),
    "1d": ("ONE_DAY", 86400, 365),
}


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as f:
        json.dump(value, f)
        name = f.name
    os.chmod(name, 0o600)
    os.replace(name, path)


class MarketEngine:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.credentials_path = self.root / "angel-private.json"
        self.watch_path = self.root / "angel-watchlist.json"
        self.credentials = (
            json.loads(self.credentials_path.read_text()) if self.credentials_path.exists() else {}
        )
        self.watchlist = json.loads(self.watch_path.read_text()) if self.watch_path.exists() else []
        self.session = {}
        self.login_at = 0
        self.ticks = {}
        self.catalog = {}
        self.error = ""
        self.connected = False
        self.lock = threading.RLock()
        self.rest_lock = threading.Lock()
        self.login_lock = threading.Lock()
        self.catalog_lock = threading.Lock()
        self.last_request = 0
        self.socket = None
        self.stop_event = threading.Event()
        self.thread = None
        self.want_connection = bool(self.credentials.get("auto_connect"))
        self.ledger = PaperLedger(root)
        self.cache = {}

    def start(self):
        self.thread = threading.Thread(target=self._feed_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.socket:
            self.socket.close()
        if self.thread:
            self.thread.join(timeout=5)

    def configure(self, fields):
        with self.login_lock:
            value = dict(self.credentials)
            for key in ("api_key", "client_code", "password", "totp_secret"):
                item = str(fields.get(key, "")).strip()
                if item:
                    if len(item) > 512 or any(ord(c) < 33 or ord(c) > 126 for c in item):
                        raise BrokerError("Credential contains invalid characters.")
                    value[key] = item
            if fields.get("clear") == "yes":
                value = {}
            if value.get("totp_secret"):
                try:
                    pyotp.TOTP(value["totp_secret"].replace(" ", "")).now()
                except Exception:
                    raise BrokerError(
                        "Invalid authenticator secret. Enter the setup secret, or leave it empty and use a one-time code."
                    ) from None
            self.want_connection = False
            if self.socket:
                self.socket.close()
            with self.lock:
                self.connected = False
                self.session = {}
                self.ticks = {}
                self.cache = {}
                self.credentials = value
                value["auto_connect"] = False
                atomic_json(self.credentials_path, value)
        return {"message": "Angel One credentials saved privately. Connect to start the feed."}

    def _request(self, path, body=None, authenticated=True):
        # One request per second across all REST endpoints stays below documented limits.
        with self.rest_lock:
            delay = 1.05 - (time.monotonic() - self.last_request)
            if delay > 0:
                time.sleep(delay)
            with self.lock:
                c = dict(self.credentials)
                session = dict(self.session)
            if authenticated and not session.get("jwtToken"):
                raise BrokerError("Connect your Angel One account first.")
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-UserType": "USER",
                "X-SourceID": "WEB",
                "X-ClientLocalIP": "127.0.0.1",
                "X-ClientPublicIP": os.environ.get("ANGEL_PUBLIC_IP", "192.9.166.69"),
                "X-MACAddress": "00:00:00:00:00:00",
                "X-PrivateKey": c.get("api_key", ""),
            }
            if authenticated:
                headers["Authorization"] = "Bearer " + session["jwtToken"]
            self.last_request = time.monotonic()
            try:
                r = requests.request(
                    "GET" if body is None else "POST",
                    API + path,
                    headers=headers,
                    json=body,
                    timeout=(5, 15),
                )
                if r.status_code == 429:
                    raise BrokerError("Angel One is rate-limiting requests. Wait and try again.")
                r.raise_for_status()
                v = r.json()
            except (requests.RequestException, ValueError):
                raise BrokerError(
                    "Angel One request failed. Check API access, connection and the registered server IP."
                ) from None
            if not v.get("status"):
                code = v.get("errorcode", "")
                if code in ("AG8001", "AG8002", "AG8003", "AB1010"):
                    with self.lock:
                        self.session = {}
                        self.connected = False
                    raise BrokerError("Angel One session expired. Reconnect in the account panel.")
                if code in ("AB1050", "AB1007", "AB1012", "AB1006") or not authenticated:
                    raise BrokerError(
                        "Angel One login was rejected. Check client code, PIN/password and current TOTP."
                    )
                raise BrokerError(
                    "Angel One could not fulfil this request. Check instrument availability and account permissions."
                )
            return v.get("data")

    def connect(self, totp=""):
        with self.login_lock:
            c = self.credentials
            if not all(c.get(k) for k in ("api_key", "client_code", "password")):
                raise BrokerError("Save your API key, client code and PIN/password first.")
            code = totp or (pyotp.TOTP(c["totp_secret"]).now() if c.get("totp_secret") else "")
            if not re.fullmatch(r"\d{6}", code):
                raise BrokerError(
                    "Enter the current six-digit TOTP, or save your authenticator setup secret."
                )
            result = self._request(
                "/rest/auth/angelbroking/user/v1/loginByPassword",
                {"clientcode": c["client_code"], "password": c["password"], "totp": code},
                False,
            )
            if not result or not result.get("jwtToken") or not result.get("feedToken"):
                raise BrokerError("Angel One returned an incomplete session.")
            if self.socket:
                self.socket.close()
            with self.lock:
                self.session = {k: result[k] for k in ("jwtToken", "feedToken")}
                self.login_at = time.time()
                self.error = ""
                self.want_connection = True
                self.cache = {}
                self.credentials["auto_connect"] = bool(c.get("totp_secret"))
                atomic_json(self.credentials_path, self.credentials)
        return {"message": "Angel One authenticated. Establishing the market feed."}

    def disconnect(self):
        self.want_connection = False
        if self.socket:
            self.socket.close()
        with self.lock:
            self.session = {}
            self.connected = False
            self.credentials["auto_connect"] = False
            atomic_json(self.credentials_path, self.credentials)
        return {"message": "Feed disconnected. Broker orders were not changed."}

    def _catalog(self):
        with self.catalog_lock:
            if self.catalog:
                return
            path = self.root / "angel-instruments.json"
            if path.exists() and time.time() - path.stat().st_mtime < 86400:
                rows = json.loads(path.read_text())
            else:
                try:
                    response = requests.get(MASTER, timeout=(5, 45))
                    response.raise_for_status()
                    raw = response.json()
                    rows = []
                    for r in raw:
                        if r.get("exch_seg") not in ("NSE", "BSE") or r.get(
                            "instrumenttype"
                        ) not in ("", "AMXIDX"):
                            continue
                        if not str(r.get("token", "")).isdigit():
                            continue
                        if (
                            r["exch_seg"] == "NSE"
                            and r.get("instrumenttype") != "AMXIDX"
                            and not r.get("symbol", "").endswith("-EQ")
                        ):
                            continue
                        rows.append(
                            {
                                "key": r["exch_seg"] + ":" + r["token"],
                                "token": r["token"],
                                "symbol": r["symbol"],
                                "name": r.get("name", ""),
                                "exchange": r["exch_seg"],
                                "kind": "index"
                                if r.get("instrumenttype") == "AMXIDX"
                                else "equity",
                            }
                        )
                    if not rows:
                        raise ValueError("empty catalog")
                    atomic_json(path, rows)
                except (requests.RequestException, ValueError):
                    if not path.exists():
                        raise BrokerError(
                            "Instrument directory is unavailable. Try again shortly."
                        ) from None
                    rows = json.loads(path.read_text())
            self.catalog = {r["key"]: r for r in rows}

    def search(self, query):
        self._catalog()
        q = query.strip().upper()[:40]
        if len(q) < 2:
            return []
        matches = [r for r in self.catalog.values() if q in r["symbol"] or q in r["name"]]
        return sorted(
            matches, key=lambda r: (not r["symbol"].startswith(q), r["exchange"], r["symbol"])
        )[:30]

    def instrument(self, key):
        self._catalog()
        if key not in self.catalog:
            raise BrokerError("Choose an instrument from the search results.")
        return self.catalog[key]

    def watch(self, key, action):
        instrument = self.instrument(key)
        with self.lock:
            keys = {r["key"] for r in self.watchlist}
            if action == "add" and key not in keys:
                if len(keys) >= 50:
                    raise BrokerError("Watchlist limit: 50 instruments.")
                self.watchlist.append(instrument)
            elif action == "remove":
                self.watchlist = [r for r in self.watchlist if r["key"] != key]
            elif action != "add":
                raise BrokerError("Invalid watchlist action.")
            atomic_json(self.watch_path, self.watchlist)
            if self.socket and self.connected:
                try:
                    self._subscription(self.socket, [instrument], 0 if action == "remove" else 1)
                except Exception:
                    self.connected = False
                    self.socket.close()
        return {"message": "Watchlist updated.", "watchlist": self.watchlist}

    def _subscription(self, socket, instruments, action=1):
        tokens = []
        for exchange, kind in (("NSE", 1), ("BSE", 3)):
            items = [r["token"] for r in instruments if r["exchange"] == exchange]
            if items:
                tokens.append({"exchangeType": kind, "tokens": items})
        if tokens:
            socket.send(
                json.dumps(
                    {
                        "correlationID": "arkbyte",
                        "action": action,
                        "params": {"mode": 2, "tokenList": tokens},
                    }
                )
            )

    def _feed_loop(self):
        retry = 3
        while not self.stop_event.is_set():
            if not self.want_connection:
                self.stop_event.wait(1)
                continue
            try:
                if not self.session or time.time() - self.login_at > 18 * 3600:
                    self.connect()
                with self.lock:
                    c = dict(self.credentials)
                    s = dict(self.session)

                def opened(ws):
                    with self.lock:
                        self.connected = True
                        self.error = ""
                        items = list(self.watchlist)
                    self._subscription(ws, items)

                def received(ws, message):
                    tick = parse_tick(message)
                    if tick:
                        with self.lock:
                            if tick["key"] in {i["key"] for i in self.watchlist}:
                                old = self.ticks.get(tick["key"])
                                if not old or tick["timestamp"] >= old["timestamp"]:
                                    self.ticks[tick["key"]] = tick

                def failed(*_):
                    with self.lock:
                        self.connected = False
                        self.error = "Market feed disconnected. Reconnecting…"

                self.socket = websocket.WebSocketApp(
                    "wss://smartapisocket.angelone.in/smart-stream",
                    header={
                        "Authorization": s["jwtToken"],
                        "x-api-key": c["api_key"],
                        "x-client-code": c["client_code"],
                        "x-feed-token": s["feedToken"],
                    },
                    on_open=opened,
                    on_message=received,
                    on_error=failed,
                    on_close=failed,
                )
                # websocket-client validates TLS certificates by default. Never disable this.
                heartbeat_stop = threading.Event()

                def heartbeat():
                    while not heartbeat_stop.wait(10):
                        try:
                            if self.socket and self.connected:
                                self.socket.send("ping")
                        except Exception:
                            return

                threading.Thread(target=heartbeat, daemon=True).start()
                try:
                    self.socket.run_forever(ping_interval=20, ping_timeout=10)
                finally:
                    heartbeat_stop.set()
                retry = min(60, retry * 2)
            except BrokerError as exc:
                self.error = str(exc)
                retry = 60
                if not self.credentials.get("totp_secret"):
                    self.want_connection = False
            except Exception:
                self.error = "Market feed unavailable. Reconnecting…"
                retry = 30
            with self.lock:
                self.connected = False
            self.stop_event.wait(retry)

    def status(self):
        with self.lock:
            return {
                "configured": all(
                    self.credentials.get(k) for k in ("api_key", "client_code", "password")
                ),
                "client_code": (self.credentials.get("client_code", "")[:2] + "••••")
                if self.credentials.get("client_code")
                else "",
                "has_totp_secret": bool(self.credentials.get("totp_secret")),
                "authenticated": bool(self.session),
                "connected": self.connected,
                "error": self.error,
                "watchlist": list(self.watchlist),
                "ticks": dict(self.ticks),
                "server_time": time.time(),
                "real_orders_enabled": False,
                "max_watchlist": 50,
            }

    def candles(self, key, interval):
        instrument = self.instrument(key)
        if interval not in INTERVALS:
            raise BrokerError("Unsupported chart interval.")
        cachekey = ("candles", key, interval)
        if cachekey in self.cache and time.time() - self.cache[cachekey][0] < 30:
            return self.cache[cachekey][1]
        name, seconds, days = INTERVALS[interval]
        now = datetime.now(ZoneInfo("Asia/Kolkata"))
        rows = (
            self._request(
                "/rest/secure/angelbroking/historical/v1/getCandleData",
                {
                    "exchange": instrument["exchange"],
                    "symboltoken": instrument["token"],
                    "interval": name,
                    "fromdate": (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M"),
                    "todate": now.strftime("%Y-%m-%d %H:%M"),
                },
            )
            or []
        )
        unique = {}
        for row in rows:
            try:
                stamp = datetime.fromisoformat(row[0])
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
                ts = int(stamp.timestamp())
                values = [float(v) for v in row[1:6]]
                if (
                    len(values) != 5
                    or not all(__import__("math").isfinite(v) for v in values)
                    or ts > now.timestamp()
                ):
                    continue
                unique[ts] = {
                    "time": ts,
                    "open": values[0],
                    "high": values[1],
                    "low": values[2],
                    "close": values[3],
                    "volume": values[4],
                }
            except (ValueError, TypeError, IndexError):
                continue
        result = {
            "instrument": instrument,
            "interval": interval,
            "seconds": seconds,
            "candles": [unique[k] for k in sorted(unique)],
            "source": "Angel One historical candles",
        }
        self.cache[cachekey] = (time.time(), result)
        return result

    def portfolio(self, kind):
        paths = {
            "funds": "/rest/secure/angelbroking/user/v1/getRMS",
            "holdings": "/rest/secure/angelbroking/portfolio/v1/getAllHolding",
            "positions": "/rest/secure/angelbroking/order/v1/getPosition",
            "orders": "/rest/secure/angelbroking/order/v1/getOrderBook",
        }
        if kind not in paths:
            raise BrokerError("Unsupported account view.")
        cachekey = ("portfolio", kind)
        if cachekey in self.cache and time.time() - self.cache[cachekey][0] < 30:
            return self.cache[cachekey][1]
        result = {
            "data": self._request(paths[kind]),
            "as_of": time.time(),
            "mode": "live",
            "read_only": True,
        }
        self.cache[cachekey] = (time.time(), result)
        return result

    def paper_order(self, order):
        instrument = self.instrument(order.get("key", ""))
        if instrument.get("kind") == "index":
            raise BrokerError("Indices cannot be traded as equity shares.")
        with self.lock:
            if not self.connected:
                raise BrokerError("Connect a live market feed before simulating an order.")
            tick = self.ticks.get(instrument["key"])
        value = self.ledger.fill(order, instrument, tick)
        return {
            "message": "Paper order filled at the latest live LTP. No broker order was sent.",
            "order": value,
        }
