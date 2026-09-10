"""Loopback market service. HTTP is signed by the API; WebSockets use owner sessions."""

import asyncio
import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from flask import Flask
from itsdangerous import BadSignature

from dashboard.broker.core import BrokerError
from dashboard.broker.engine import MarketEngine


def internal_key(secret):
    return hmac.new(secret.encode(), b"arkbyte-market-service-v1", hashlib.sha256).hexdigest()


def create_market_app(root=None, engine=None, testing=False):
    root = Path(root or os.environ.get("DASHBOARD_STATE_DIR", "/var/lib/tradingagents/dashboard"))

    def owner():
        return json.loads((root / "auth.json").read_text())

    signer_app = Flask("market-session")
    signer_app.secret_key = owner()["secret"]
    signer = signer_app.session_interface.get_signing_serializer(signer_app)
    engine = engine or MarketEngine(root)

    @asynccontextmanager
    async def lifespan(app):
        engine.start()
        yield
        engine.stop()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.engine = engine

    @app.middleware("http")
    async def protect(request, call_next):
        if not hmac.compare_digest(
            request.headers.get("x-market-key", ""), internal_key(owner()["secret"])
        ):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        if len(await request.body()) > 16384:
            return JSONResponse({"error": "Request too large"}, status_code=413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(BrokerError)
    async def broker_error(request, exc):
        return JSONResponse({"error": str(exc)}, status_code=400)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({"error": "Invalid request fields."}, status_code=400)

    @app.get("/automation")
    def automation():
        return engine.automation.state()

    @app.get("/status")
    def status():
        return engine.status()

    @app.get("/search")
    def search(q: str = ""):
        return {"instruments": engine.search(q)}

    @app.get("/candles")
    def candles(key: str = "", interval: str = "5m"):
        return engine.candles(key, interval)

    @app.get("/portfolio")
    def portfolio(kind: str = "holdings"):
        return engine.portfolio(kind)

    @app.get("/paper")
    def paper():
        return engine.ledger.summary(engine.status()["ticks"])

    @app.post("/command/{action}")
    def command(action: str, payload: dict):
        if action == "backtest":
            return engine.automation.run_backtest(payload)
        if action in (
            "strategy-save",
            "strategy-start",
            "strategy-pause",
            "strategy-delete",
            "halt",
            "risk",
        ):
            if action == "risk" and "halted" in payload:
                if payload["halted"] not in ("true", "false", True, False):
                    raise BrokerError("Invalid halt state.")
                payload["halted"] = payload["halted"] in ("true", True)
            return engine.automation.command(action, payload)
        if action == "configure":
            return engine.configure(payload)
        if action == "connect":
            return engine.connect(str(payload.get("totp", "")).strip())
        if action == "disconnect":
            return engine.disconnect()
        if action == "watch":
            return engine.watch(str(payload.get("key", "")), str(payload.get("action", "")))
        if action == "paper-order":
            quantity = payload.get("quantity", "")
            if isinstance(quantity, bool) or not str(quantity).isdigit():
                raise BrokerError("Quantity must be a positive whole number.")
            payload["quantity"] = int(quantity)
            return engine.paper_order(payload)
        raise BrokerError("Unsupported action. Real-money orders are disabled.")

    def authenticated(socket):
        try:
            cookie = socket.cookies.get("session" if testing else "__Host-tradingagents", "")
            session = signer.loads(cookie, max_age=28800)
            auth = owner()
            return (
                session.get("owner") is True
                and session.get("epoch") == auth["epoch"]
                and not auth.get("must_change")
            )
        except (BadSignature, ValueError, TypeError):
            return False

    clients = set()

    @app.websocket("/api/market/stream")
    async def stream(socket: WebSocket):
        origin = "http://127.0.0.1:8051" if testing else "https://at.arkbytetech.com"
        if (
            socket.headers.get("origin") != origin
            or not authenticated(socket)
            or len(clients) >= 10
        ):
            await socket.close(code=1008)
            return
        await socket.accept()
        clients.add(socket)
        try:
            while authenticated(socket):
                await socket.send_json({"type": "market", "data": engine.status()})
                await asyncio.sleep(0.5)
            await socket.close(code=1008)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            clients.discard(socket)

    return app
