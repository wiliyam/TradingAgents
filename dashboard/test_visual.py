"""Authenticated dashboard API, progress persistence and honest scoring."""

# ruff: noqa: F811
from dashboard.presentation import present
from dashboard.store import Store
from dashboard.test_dashboard import app, client, login  # noqa: F401


def test_api_requires_login(client):
    assert client.get("/api/dashboard").status_code == 401


def test_api_redacts_secrets_and_exposes_csrf(client, app):
    login(client)
    app.extensions["store"].save_settings(
        {
            "provider": "openai",
            "api_key": "never-return-this",
            "quick_model": "x",
            "deep_model": "x",
        }
    )
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    assert response.json["csrf"]
    assert "never-return-this" not in response.text
    assert client.post("/api/telegram", data={}).status_code == 400


def test_progress_survives_failure(tmp_path):
    store = Store(tmp_path)
    job = store.enqueue("TCS.NS", "2026-09-08", "ai")
    store.claim()
    store.progress(job, {"market_report": "Observed evidence"})
    store.finish(job, error="Safe failure")
    value = store.job(job)
    assert value["progress"]["market_report"]["content"] == "Observed evidence"
    assert present(value)["agents"][0]["status"] == "complete"


def test_scores_do_not_invent_confidence():
    value = present(
        {
            "mode": "ai",
            "status": "complete",
            "result": {
                "market_snapshot": {"close": 100, "sma_20": 90, "sma_50": 110, "rsi_14": 55},
                "decision_signal": "HOLD",
                "market_report": "evidence",
            },
        }
    )
    assert value["technical"]["score"] == 67
    assert value["completion"]["completed"] == 1
    assert value["signal"] == "Hold"
    assert (
        present({"mode": "snapshot", "status": "complete", "result": {}})["technical"]["score"]
        is None
    )


def test_unknown_signal_is_not_guessed_from_prose():
    assert (
        present({"result": {"decision_signal": "maybe BUY or SELL"}})["signal"] == "Not available"
    )


def test_backfill_rejects_different_run(tmp_path):
    import json

    from dashboard.backfill import recover_reports

    store = Store(tmp_path / "state")
    job = store.enqueue("TCS.NS", "2026-09-08", "ai")
    fields = dict.fromkeys(
        (
            "market_report",
            "fundamentals_report",
            "news_report",
            "sentiment_report",
            "final_trade_decision",
        ),
        "original",
    )
    store.finish(job, result=fields)
    logs = tmp_path / "logs"
    path = logs / "TCS.NS" / "TradingAgentsStrategy_logs" / "full_states_log_2026-09-08.json"
    path.parent.mkdir(parents=True)
    state = {
        **fields,
        "company_of_interest": "TCS.NS",
        "trade_date": "2026-09-08",
        "investment_debate_state": {"bull_history": "Saved bull argument"},
    }
    path.write_text(json.dumps({**state, "final_trade_decision": "different run"}))
    assert recover_reports(store, logs) == 0
    path.write_text(json.dumps(state))
    assert recover_reports(store, logs) == 1
    assert store.job(job)["result"]["bull_history"] == "Saved bull argument"
