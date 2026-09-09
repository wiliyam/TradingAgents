"""Local-only browser-test fixture with synthetic data and disposable credentials."""

import json
import os
import tempfile
from pathlib import Path

from werkzeug.security import generate_password_hash

from dashboard.app import create_app
from dashboard.presentation import AGENTS
from dashboard.store import Store


def main():
    root = Path(tempfile.mkdtemp(prefix="tradingagents-ui-"))
    (root / "auth.json").write_text(
        json.dumps(
            {
                "username": "tester",
                "password_hash": generate_password_hash("dashboard-test-password"),
                "secret": "local-test-secret",
                "epoch": "test",
                "must_change": False,
            }
        )
    )
    os.environ["DASHBOARD_WEB_DIR"] = str(Path(__file__).resolve().parents[1] / "frontend/out")
    store = Store(root)
    job = store.enqueue("RELIANCE.NS", "2026-09-08", "ai")
    bars = [
        {
            "date": f"2026-08-{i + 1:02d}",
            "open": 1300 + i * 2,
            "high": 1310 + i * 2,
            "low": 1295 + i * 2,
            "close": 1305 + i * 2,
            "volume": 100000 + i * 5000,
            "sma20": 1300 + i,
            "sma50": 1290 + i,
        }
        for i in range(28)
    ]

    result = {
        key: f"## {name}\n\n**Assessment**: Evidence from the available data.\n\n- Price trend reviewed\n- Risks considered\n\n<script>window.injected=true</script>\n\n[unsafe](javascript:alert(1))"
        for key, name, _ in AGENTS
    }
    result.update(
        decision_signal="HOLD",
        market_snapshot={
            "close": 1359,
            "daily_change_percent": 1.2,
            "rsi_14": 58,
            "sma_20": 1330,
            "sma_50": 1320,
            "volume": 230000,
            "latest_bar_date": "2026-08-28",
            "bars": bars,
        },
    )
    store.finish(job, result=result)
    app = create_app(root, testing=True)
    app.run(host="127.0.0.1", port=8051, use_reloader=False)


if __name__ == "__main__":
    main()
