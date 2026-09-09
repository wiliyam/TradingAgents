"""HTTPS-only, CSRF-protected single-owner research dashboard."""

import fcntl
import hmac
import json
import os
import re
import secrets
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from dashboard.store import Store

PROVIDERS = {
    "codex_cli": "Codex CLI · ChatGPT sign-in",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google Gemini",
    "deepseek": "DeepSeek",
}
SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9&_-]{0,29}\.(NS|BO)\Z")
MODEL = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,119}\Z")


def india_today():
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


def codex_ready():
    binary = Path(os.environ.get("TRADINGAGENTS_CODEX_BIN", "/opt/codex/bin/codex"))
    home = Path(os.environ.get("CODEX_HOME", "/var/lib/tradingagents/.codex"))
    return binary.is_file() and os.access(binary, os.X_OK) and (home / "auth.json").is_file()


def provider_ready(config):
    return codex_ready() if config["provider"] == "codex_cli" else bool(config.get("api_key"))


def create_app(root=None, testing=False):
    root = Path(root or os.environ.get("DASHBOARD_STATE_DIR", "/var/lib/tradingagents/dashboard"))
    auth_path = root / "auth.json"

    def auth():
        return json.loads(auth_path.read_text())

    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=auth()["secret"],
        TESTING=testing,
        SESSION_COOKIE_NAME="__Host-tradingagents" if not testing else "session",
        SESSION_COOKIE_SECURE=not testing,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        MAX_CONTENT_LENGTH=16384,
        MAX_FORM_MEMORY_SIZE=16384,
        MAX_FORM_PARTS=20,
        TRUSTED_HOSTS=["at.arkbytetech.com", "localhost", "127.0.0.1"]
        if testing
        else ["at.arkbytetech.com"],
    )
    # Nginx is the only caller: gunicorn binds to 127.0.0.1, and nginx overwrites these headers.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    store = Store(root)
    app.extensions["store"] = store

    @app.before_request
    def protect():
        if request.endpoint is None:
            return Response("Not found", status=404, mimetype="text/plain")
        public = request.endpoint in {"login", "static", "health"}
        if not public:
            owner = auth()
            if not session.get("owner"):
                return redirect(url_for("login"))
            if session.get("epoch") != owner["epoch"]:
                session.clear()
                return redirect(url_for("login"))
            if owner.get("must_change") and request.endpoint not in {"password", "logout"}:
                return redirect(url_for("password"))
        if request.method == "POST":
            token = request.form.get("csrf", "")
            if not token or not hmac.compare_digest(
                token.encode(), session.get("csrf", "").encode()
            ):
                abort(400, "The form expired. Reload the page and try again.")

    @app.after_request
    def headers(response):
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
                "Strict-Transport-Security": "max-age=31536000",
            }
        )
        return response

    @app.context_processor
    def context():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return {
            "csrf_token": session["csrf"],
            "signed_in": session.get("owner"),
            "today": india_today().isoformat(),
        }

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            ip = request.remote_addr or "unknown"
            if store.login_attempt(ip) >= 8:
                return render_template(
                    "login.html", error="Too many attempts. Try again in 15 minutes."
                ), 429
            owner = auth()
            valid_password = check_password_hash(
                owner["password_hash"], request.form.get("password", "")
            )
            if not valid_password or not hmac.compare_digest(
                request.form.get("username", "").encode(), owner["username"].encode()
            ):
                store.login_attempt(ip, record=True)
                return render_template("login.html", error="Incorrect username or password."), 401
            store.login_attempt(ip, clear=True)
            session.clear()
            session.update(owner=True, epoch=owner["epoch"])
            session.permanent = True
            return redirect(url_for("index"))
        return render_template("login.html")

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            jobs=store.jobs(),
            ready=provider_ready(store.settings()),
            codex=store.settings()["provider"] == "codex_cli",
        )

    @app.post("/jobs")
    def start():
        symbol = request.form.get("symbol", "").strip().upper()
        day = request.form.get("date", "")
        mode = request.form.get("mode", "")
        if not SYMBOL.fullmatch(symbol) or mode not in {"snapshot", "ai"}:
            abort(400, "Choose an NSE (.NS) or BSE (.BO) symbol and a valid analysis mode.")
        try:
            parsed = datetime.strptime(day, "%Y-%m-%d").date()
        except ValueError:
            abort(400, "Choose a valid analysis date.")
        if parsed > india_today() or parsed.year < 2000:
            abort(400, "Choose a date between 2000 and today in India.")
        if mode == "ai" and not provider_ready(store.settings()):
            abort(
                400,
                "Connect Codex on the server or add your provider API key in Settings before starting AI research.",
            )
        try:
            job_id = store.enqueue(symbol, parsed.isoformat(), mode)
        except ValueError as exc:
            abort(409, str(exc))
        return redirect(url_for("job", job_id=job_id))

    @app.get("/jobs/<job_id>")
    def job(job_id):
        value = store.job(job_id)
        if value is None:
            abort(404)
        return render_template("job.html", job=value)

    @app.get("/jobs/<job_id>/download")
    def download(job_id):
        value = store.job(job_id)
        if value is None or value["status"] != "complete":
            abort(404)
        return Response(
            json.dumps(value, indent=2),
            mimetype="application/json",
            headers={"Content-Disposition": f'attachment; filename="analysis-{value["id"]}.json"'},
        )

    @app.route("/settings", methods=["GET", "POST"])
    def settings():
        config = store.settings()
        if request.method == "POST":
            provider = request.form.get("provider", "")
            quick, deep = (
                request.form.get(key, "").strip() for key in ("quick_model", "deep_model")
            )
            key = request.form.get("api_key", "").strip()
            if provider == "codex_cli":
                quick = deep = "gpt-6-astra"
                key = ""
            if provider not in PROVIDERS or not MODEL.fullmatch(quick) or not MODEL.fullmatch(deep):
                abort(400, "Choose a supported provider and valid model names.")
            if len(key) > 4096 or any(ord(char) < 33 or ord(char) > 126 for char in key):
                abort(400, "The API key contains invalid characters.")
            if not key and provider == config["provider"] and provider != "codex_cli":
                key = config.get("api_key", "")
            if request.form.get("clear_key") == "yes":
                key = ""
            store.save_settings(
                {"provider": provider, "quick_model": quick, "deep_model": deep, "api_key": key}
            )
            flash("Model settings saved. API credentials stay on this server.")
            return redirect(url_for("settings"))
        public_config = {key: value for key, value in config.items() if key != "api_key"}
        return render_template(
            "settings.html",
            config=public_config,
            ready=bool(config.get("api_key")),
            codex_connected=codex_ready(),
            providers=PROVIDERS,
        )

    @app.route("/password", methods=["GET", "POST"])
    def password():
        owner = auth()
        if request.method == "POST":
            ip = "password:" + (request.remote_addr or "unknown")
            if store.login_attempt(ip) >= 8:
                abort(429, "Too many attempts. Try again in 15 minutes.")
            current, new = request.form.get("current", ""), request.form.get("password", "")
            if not check_password_hash(owner["password_hash"], current):
                store.login_attempt(ip, record=True)
                abort(400, "Current password is incorrect.")
            if (
                len(new) < 14
                or len(new) > 256
                or new != request.form.get("confirm")
                or new == current
            ):
                abort(400, "Use a new password of 14–256 characters, with matching confirmation.")
            with auth_path.with_suffix(".lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                owner = auth()
                if not check_password_hash(owner["password_hash"], current):
                    abort(409, "The password was changed by another request. Sign in again.")
                owner.update(
                    password_hash=generate_password_hash(new),
                    epoch=secrets.token_hex(16),
                    must_change=False,
                )
                with tempfile.NamedTemporaryFile(mode="w", dir=root, delete=False) as handle:
                    json.dump(owner, handle)
                    temporary = Path(handle.name)
                temporary.replace(auth_path)
            session.clear()
            session.update(owner=True, epoch=owner["epoch"])
            session.permanent = True
            store.login_attempt(ip, clear=True)
            flash("Password updated. Other sessions have been signed out.")
            return redirect(url_for("index"))
        return render_template("password.html", must_change=owner.get("must_change", False))

    @app.errorhandler(400)
    @app.errorhandler(404)
    @app.errorhandler(409)
    @app.errorhandler(429)
    def error(exc):
        return render_template("error.html", error=exc.description, code=exc.code), exc.code

    return app
