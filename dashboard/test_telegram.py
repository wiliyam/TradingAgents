"""Telegram transport is mocked; tests never contact a real channel."""

# ruff: noqa: F811
import json
from unittest.mock import MagicMock
from urllib.error import URLError

from dashboard import telegram
from dashboard.test_dashboard import app, client, csrf, login  # noqa: F401


def test_settings_token_is_write_only(client, app):
    login(client)
    token = "123456789:" + "a" * 35
    assert (
        client.post(
            "/api/telegram",
            data={
                "csrf": csrf(client),
                "token": token,
                "channel": "@research_channel",
                "enabled": "yes",
            },
        ).status_code
        == 200
    )
    value = client.get("/api/dashboard")
    assert token not in value.text
    assert value.json["telegram"]["connected"]
    assert app.extensions["store"].telegram()["token"] == token
    assert (
        client.post(
            "/api/telegram",
            data={"csrf": csrf(client), "channel": "@research_channel", "clear": "yes"},
        ).status_code
        == 200
    )
    assert not app.extensions["store"].telegram()["token"]


def test_delivery_does_not_leak_token(monkeypatch):
    def fail(*args, **kwargs):
        raise URLError("secret-url-with-token")

    monkeypatch.setattr(telegram, "urlopen", fail)
    status = telegram.send_message(
        {"token": "123456789:" + "a" * 35, "channel": "@research_channel"}, "Test"
    )
    assert "secret-url" not in status
    assert "could not be confirmed" in status


def test_plain_text_message_and_timeout(monkeypatch):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"ok":true}'
    call = MagicMock(return_value=response)
    monkeypatch.setattr(telegram, "urlopen", call)
    assert (
        telegram.send_message(
            {"token": "123456789:" + "a" * 35, "channel": "@research_channel"}, "<test>"
        )
        == "sent"
    )
    req = call.call_args.args[0]
    assert json.loads(req.data)["text"] == "<test>"
    assert "parse_mode" not in json.loads(req.data)
    assert call.call_args.kwargs["timeout"] == 15


def test_notification_failure_preserves_completed_job(app, monkeypatch):
    store = app.extensions["store"]
    store.save_telegram({"enabled": True})
    job = store.enqueue("TCS.NS", "2026-09-08", "snapshot")
    store.finish(job, result={"market_snapshot": {"close": 100}})
    monkeypatch.setattr(telegram, "send_message", lambda *_: "Delivery failed")
    telegram.notify_completed(store, store.job(job))
    assert store.job(job)["status"] == "complete"
    assert store.job(job)["notification"]["status"] == "Delivery failed"


def test_notification_database_failure_does_not_escape(app, monkeypatch):
    store = app.extensions["store"]
    store.save_telegram({"enabled": True})
    job = store.enqueue("TCS.NS", "2026-09-08", "snapshot")
    store.finish(job, result={"market_snapshot": {"close": 100}})

    def fail(*_):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(telegram, "send_message", lambda *_: "sent")
    monkeypatch.setattr(store, "notification", fail)
    telegram.notify_completed(store, store.job(job))
    assert store.job(job)["status"] == "complete"
    assert store.job(job)["result"]["market_snapshot"]["close"] == 100


def test_bot_destination_error_is_actionable_and_redacted(monkeypatch):
    from io import BytesIO
    from urllib.error import HTTPError

    def fail(*args, **kwargs):
        raise HTTPError(
            "secret-token-url",
            403,
            "Forbidden",
            {},
            BytesIO(b'{"description":"Forbidden: bots can\\u0027t send messages to bots"}'),
        )

    monkeypatch.setattr(telegram, "urlopen", fail)
    message = telegram.send_message(
        {"token": "123456789:" + "a" * 35, "channel": "@research_bot"}, "Test"
    )
    assert "channel" in message.lower()
    assert "bot username" in message.lower()
    assert "secret-token" not in message
