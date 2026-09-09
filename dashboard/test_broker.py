"""Broker protocol parsing and paper accounting never call trading endpoints."""

import struct
import time
import uuid

import pytest

from dashboard.broker.core import BrokerError, PaperLedger, parse_tick


def packet():
    data = bytearray(123)
    struct.pack_into("<BB", data, 0, 2, 1)
    data[2:6] = b"2885"
    for offset, value in {
        27: 1,
        35: int(time.time() * 1000),
        43: 123456,
        67: 1000,
        91: 120000,
        99: 125000,
        107: 119000,
        115: 121000,
    }.items():
        struct.pack_into("<q", data, offset, value)
    return bytes(data)


def test_quote_packet_price_units_and_exchange_timestamp():
    tick = parse_tick(packet())
    assert tick["price"] == 1234.56
    assert tick["key"] == "NSE:2885"
    assert tick["volume"] == 1000
    assert tick["previous_close"] == 1210


def test_bad_frames_fail_closed():
    for data in (b"", b"pong", packet()[:60]):
        assert parse_tick(data) is None


def test_paper_ledger_is_idempotent_and_separate(tmp_path):
    ledger = PaperLedger(tmp_path)
    instrument = {"key": "NSE:2885", "symbol": "RELIANCE-EQ", "exchange": "NSE", "token": "2885"}
    order = {"request_id": uuid.uuid4().hex, "side": "BUY", "quantity": 10, "mode": "paper"}
    tick = {"price": 100, "timestamp": time.time(), "received": time.time()}
    first = ledger.fill(order, instrument, tick)
    second = ledger.fill(order, instrument, tick)
    assert first == second
    assert ledger.summary({})["cash"] == 999000
    with pytest.raises(BrokerError):
        ledger.fill({**order, "request_id": uuid.uuid4().hex, "mode": "live"}, instrument, tick)
    with pytest.raises(BrokerError):
        ledger.fill(
            {**order, "request_id": uuid.uuid4().hex},
            instrument,
            {**tick, "timestamp": time.time() - 60},
        )
    with pytest.raises(BrokerError):
        ledger.fill(
            {**order, "request_id": uuid.uuid4().hex, "side": "SELL", "quantity": 11},
            instrument,
            tick,
        )
    assert ledger.summary({})["cash"] == 999000


def test_market_service_requires_internal_key_and_session(tmp_path):
    import json
    from unittest.mock import Mock

    from fastapi.testclient import TestClient
    from flask import Flask
    from starlette.websockets import WebSocketDisconnect

    from dashboard.broker.service import create_market_app, internal_key

    (tmp_path / "auth.json").write_text(
        json.dumps({"secret": "fixture-secret", "epoch": "one", "must_change": False})
    )
    engine = Mock()
    engine.status.return_value = {"connected": False, "watchlist": [], "ticks": {}}
    service = create_market_app(tmp_path, engine=engine, testing=True)
    with TestClient(service) as client:
        assert client.get("/status").status_code == 401
        assert (
            client.get(
                "/status", headers={"x-market-key": internal_key("fixture-secret")}
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/command/live-order",
                json={},
                headers={"x-market-key": internal_key("fixture-secret")},
            ).status_code
            == 400
        )
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect(
                "/api/market/stream", headers={"origin": "http://127.0.0.1:8051"}
            ),
        ):
            pass
        app = Flask("fixture")
        app.secret_key = "fixture-secret"
        token = app.session_interface.get_signing_serializer(app).dumps(
            {"owner": True, "epoch": "one"}
        )
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect(
                "/api/market/stream",
                headers={"origin": "https://evil.example", "cookie": "session=" + token},
            ),
        ):
            pass
        with client.websocket_connect(
            "/api/market/stream",
            headers={"origin": "http://127.0.0.1:8051", "cookie": "session=" + token},
        ) as ws:
            assert ws.receive_json()["data"]["connected"] is False


def test_broker_errors_never_expose_credentials(tmp_path, monkeypatch):
    import requests

    from dashboard.broker.engine import MarketEngine

    engine = MarketEngine(tmp_path)
    engine.credentials = {
        "api_key": "secret-api-key",
        "client_code": "private-client",
        "password": "private-pin",
    }

    def fail(*args, **kwargs):
        raise requests.ConnectionError("secret-api-key private-pin")

    monkeypatch.setattr(requests, "request", fail)
    with pytest.raises(BrokerError) as error:
        engine.connect("123456")
    assert "secret-api-key" not in str(error.value)
    assert "private-pin" not in str(error.value)
    status = engine.status()
    assert "private-pin" not in str(status)
    assert "secret-api-key" not in str(status)


def test_watchlist_and_live_orders_are_bounded(tmp_path):
    from dashboard.broker.engine import MarketEngine

    engine = MarketEngine(tmp_path)
    engine.catalog = {
        f"NSE:{i}": {
            "key": f"NSE:{i}",
            "token": str(i),
            "exchange": "NSE",
            "symbol": f"S{i}-EQ",
            "kind": "equity",
        }
        for i in range(51)
    }
    for i in range(50):
        engine.watch(f"NSE:{i}", "add")
    with pytest.raises(BrokerError):
        engine.watch("NSE:50", "add")
    with pytest.raises(BrokerError):
        engine.paper_order({"key": "NSE:0", "mode": "live"})


def test_obsolete_socket_cannot_resume_after_disconnect(tmp_path):
    from unittest.mock import Mock

    from dashboard.broker.engine import MarketEngine

    engine = MarketEngine(tmp_path)
    engine.credentials = {"api_key": "fixture", "client_code": "fixture"}
    engine.session = {"jwtToken": "fixture", "feedToken": "fixture"}
    engine.want_connection = True
    socket = engine._make_socket(engine.generation, dict(engine.credentials), dict(engine.session))
    socket.close = Mock()
    engine.socket = socket
    engine.watchlist = [{"key": "NSE:2885", "exchange": "NSE", "token": "2885"}]
    engine.disconnect()
    socket.on_open(socket)
    socket.on_message(socket, packet())
    assert engine.connected is False
    assert engine.ticks == {}
    assert engine.want_connection is False
    assert socket.close.call_count == 2


def test_disconnect_wins_over_inflight_login(tmp_path, monkeypatch):
    import threading

    from dashboard.broker.engine import MarketEngine

    engine = MarketEngine(tmp_path)
    engine.credentials = {"api_key": "fixture", "client_code": "fixture", "password": "fixture"}
    started = threading.Event()
    release = threading.Event()

    def request(*args, **kwargs):
        started.set()
        assert release.wait(3)
        return {"jwtToken": "fixture", "feedToken": "fixture"}

    monkeypatch.setattr(engine, "_request", request)
    login = threading.Thread(target=engine.connect, args=("123456",))
    login.start()
    assert started.wait(3)
    disconnect = threading.Thread(target=engine.disconnect)
    disconnect.start()
    release.set()
    login.join(3)
    disconnect.join(3)
    assert not login.is_alive() and not disconnect.is_alive()
    assert engine.want_connection is False
    assert engine.session == {}
    assert engine.connected is False


def test_connection_timeout_is_not_reported_as_bad_credentials(tmp_path, monkeypatch):
    import requests

    from dashboard.broker.engine import MarketEngine
    engine = MarketEngine(tmp_path)
    engine.credentials = {"api_key": "private-key", "client_code": "client", "password": "private-pin"}
    def fail(*args, **kwargs):
        raise requests.ConnectTimeout("private-key private-pin")
    monkeypatch.setattr(requests, "request", fail)
    with pytest.raises(BrokerError, match="credentials have not been validated") as error:
        engine.connect("123456")
    assert "private-key" not in str(error.value)
    assert "private-pin" not in str(error.value)
