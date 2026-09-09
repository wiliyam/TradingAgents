"""Security and job lifecycle checks without external API calls."""

import json
from datetime import date, timedelta

import pytest
from werkzeug.security import generate_password_hash

from dashboard.app import create_app
from dashboard.store import Store


@pytest.fixture
def app(tmp_path, monkeypatch):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html><html><body>Next.js test shell</body></html>")
    monkeypatch.setenv("DASHBOARD_WEB_DIR", str(web))
    (tmp_path / "auth.json").write_text(
        json.dumps(
            {
                "username": "wiliyam",
                "password_hash": generate_password_hash("correct-test-password"),
                "secret": "test-secret-only",
                "epoch": "test",
                "must_change": False,
            }
        )
    )
    return create_app(tmp_path, testing=True)


@pytest.fixture
def client(app):
    return app.test_client()


def csrf(client, path="/login"):
    return client.get("/api/session").json["csrf"]


def login(client):
    token = csrf(client)
    return client.post(
        "/login", data={"csrf": token, "username": "wiliyam", "password": "correct-test-password"}
    )


def test_private_routes_and_headers(client):
    for path in ("/", "/settings", "/jobs/unknown", "/jobs/unknown/download", "/password"):
        assert client.get(path).status_code == 302
    response = client.get("/login")
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["Cache-Control"] == "no-store"
    assert "HttpOnly" in response.headers["Set-Cookie"]
    assert client.get("/healthz").json == {"status": "ok"}


def test_csrf_required_even_for_login(client):
    assert client.post("/login", data={"csrf": "é"}).status_code == 400
    assert (
        client.post(
            "/login", data={"username": "wiliyam", "password": "correct-test-password"}
        ).status_code
        == 400
    )
    login(client)
    assert client.post("/jobs", data={"symbol": "RELIANCE.NS"}).status_code == 400


def test_browser_background_requests_preserve_login_form(client):
    token = csrf(client)
    client.get("/favicon.ico")
    client.get("/missing-resource")
    client.get("/")
    response = client.post(
        "/login", data={"csrf": token, "username": "wiliyam", "password": "correct-test-password"}
    )
    assert response.status_code == 302
    assert client.get("/").status_code == 200


def test_login_logout_and_rate_limit(client):
    assert login(client).status_code == 302
    assert client.get("/").status_code == 200
    token = csrf(client, "/")
    assert client.post("/logout", data={"csrf": token}).status_code == 302
    for _ in range(8):
        token = csrf(client)
        assert (
            client.post(
                "/login", data={"csrf": token, "username": "wiliyam", "password": "wrong"}
            ).status_code
            == 401
        )
    token = csrf(client)
    assert (
        client.post(
            "/login", data={"csrf": token, "username": "wiliyam", "password": "wrong"}
        ).status_code
        == 429
    )


@pytest.mark.parametrize(
    "symbol,day",
    [
        ("../../secret", "2026-01-01"),
        ("AAPL", "2026-01-01"),
        ("RELIANCE.NS;id", "2026-01-01"),
        ("RELIANCE.NS", "bad"),
        ("RELIANCE.NS", (date.today() + timedelta(days=3)).isoformat()),
    ],
)
def test_job_validation(client, symbol, day):
    login(client)
    response = client.post(
        "/jobs", data={"csrf": csrf(client, "/"), "symbol": symbol, "date": day, "mode": "snapshot"}
    )
    assert response.status_code == 400


def test_snapshot_queue_and_duplicate_limit(client, app):
    login(client)
    data = {
        "csrf": csrf(client, "/"),
        "symbol": "reliance.ns",
        "date": date.today().isoformat(),
        "mode": "snapshot",
    }
    response = client.post("/jobs", data=data)
    assert response.status_code == 302
    assert client.get(response.location).status_code == 302
    assert client.post("/jobs", data=data).status_code == 409
    store = app.extensions["store"]
    job = store.claim()
    assert job["symbol"] == "RELIANCE.NS"
    assert store.claim() is None
    store.finish(job["id"], result={"summary": "<script>alert(1)</script>"})
    response = client.get(f"/api/jobs/{job['id']}")
    assert response.mimetype == "application/json"
    assert response.json["result"]["summary"] == "<script>alert(1)</script>"
    downloaded = client.get(f"/jobs/{job['id']}/download")
    assert "attachment" in downloaded.headers["Content-Disposition"]


def test_ai_needs_key_and_settings_never_return_secret(client, app):
    login(client)
    response = client.post(
        "/jobs",
        data={
            "csrf": csrf(client, "/"),
            "symbol": "TCS.NS",
            "date": date.today().isoformat(),
            "mode": "ai",
        },
    )
    assert response.status_code == 400
    data = {
        "csrf": csrf(client, "/settings"),
        "provider": "openai",
        "api_key": "private-test-api-key",
        "quick_model": "gpt-5.6-luna",
        "deep_model": "gpt-5.6-luna",
    }
    assert client.post("/settings", data=data).status_code == 302
    assert "private-test-api-key" not in client.get("/settings").text
    assert app.extensions["store"].settings()["api_key"] == "private-test-api-key"
    data["provider"] = "http://localhost:18789"
    assert client.post("/settings", data=data).status_code == 400


def test_password_change_revokes_old_sessions(client, app):
    login(client)
    other = app.test_client()
    login(other)
    token = csrf(client, "/password")
    assert (
        client.post(
            "/password",
            data={
                "csrf": token,
                "current": "wrong",
                "password": "new-very-long-password",
                "confirm": "new-very-long-password",
            },
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/password",
            data={
                "csrf": token,
                "current": "correct-test-password",
                "password": "new-very-long-password",
                "confirm": "new-very-long-password",
            },
        ).status_code
        == 302
    )
    assert other.get("/").status_code == 302
    assert client.get("/").status_code == 200


def test_restart_marks_interrupted_jobs_failed(app):
    store = app.extensions["store"]
    job_id = store.enqueue("TCS.NS", "2026-01-01", "snapshot")
    store.claim()
    store.recover()
    assert store.job(job_id)["status"] == "failed"
    assert Store(store.root).job(job_id)["error"]


def test_codex_settings_enable_ai_without_api_key(client, app, monkeypatch):
    monkeypatch.setattr("dashboard.app.codex_ready", lambda: True)
    login(client)
    response = client.post(
        "/settings", data={"csrf": csrf(client, "/settings"), "provider": "codex_cli"}
    )
    assert response.status_code == 302
    config = app.extensions["store"].settings()
    assert config["api_key"] == ""
    assert config["quick_model"] == config["deep_model"] == "gpt-6-astra"
    response = client.post(
        "/jobs",
        data={
            "csrf": csrf(client, "/"),
            "symbol": "TCS.NS",
            "date": date.today().isoformat(),
            "mode": "ai",
        },
    )
    assert response.status_code == 302


def test_disconnected_codex_does_not_queue_ai(client, app, monkeypatch):
    monkeypatch.setattr("dashboard.app.codex_ready", lambda: False)
    app.extensions["store"].save_settings(
        {
            "provider": "codex_cli",
            "quick_model": "gpt-6-astra",
            "deep_model": "gpt-6-astra",
            "api_key": "",
        }
    )
    login(client)
    response = client.post(
        "/jobs",
        data={
            "csrf": csrf(client, "/"),
            "symbol": "TCS.NS",
            "date": date.today().isoformat(),
            "mode": "ai",
        },
    )
    assert response.status_code == 400
