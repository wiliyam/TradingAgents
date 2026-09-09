"""Snapshot data correctness and isolated worker lifecycle tests."""

import subprocess
import sys
import types
from unittest.mock import Mock

import pandas as pd
import pytest

from dashboard import worker
from dashboard.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path)


@pytest.fixture
def bars():
    return pd.DataFrame(
        {"Close": range(100, 160), "Volume": [1200] * 60},
        index=pd.date_range(end="2026-09-07", periods=60, tz="Asia/Kolkata"),
    )


def test_snapshot_uses_requested_date_and_actual_data(monkeypatch, bars):
    ticker = Mock()
    ticker.history.return_value = bars
    monkeypatch.setattr("yfinance.Ticker", Mock(return_value=ticker))
    result = worker.market_snapshot("RELIANCE.NS", "2026-09-07")
    assert result["close"] == 159
    assert result["rsi_14"] == 100
    assert result["sma_20"] == 149.5
    assert result["latest_bar_date"] == "2026-09-07"
    assert ticker.history.call_args.kwargs["end"] == "2026-09-08"


@pytest.mark.parametrize("kind", ["empty", "stale", "nan", "future"])
def test_snapshot_rejects_missing_stale_and_future_data(monkeypatch, bars, kind):
    if kind == "empty":
        bars = bars.iloc[:0]
    elif kind == "stale":
        bars = bars.iloc[:10]
    elif kind == "nan":
        bars["Close"] = float("nan")
    else:
        bars.index = pd.date_range(start="2027-01-01", periods=60)
    ticker = Mock()
    ticker.history.return_value = bars
    monkeypatch.setattr("yfinance.Ticker", Mock(return_value=ticker))
    with pytest.raises(ValueError):
        worker.market_snapshot("TCS.NS", "2026-09-07")


def test_ai_uses_bounded_config_and_extracts_reports(monkeypatch):
    monkeypatch.setattr(worker, "market_snapshot", lambda *_: {"close": 123})
    monkeypatch.setitem(
        sys.modules, "tradingagents.default_config", types.SimpleNamespace(DEFAULT_CONFIG={})
    )
    graph = Mock()
    graph.propagate.return_value = (
        {"market_report": "evidence", "final_trade_decision": "hold"},
        "HOLD",
    )
    factory = Mock(return_value=graph)
    monkeypatch.setitem(
        sys.modules,
        "tradingagents.graph.trading_graph",
        types.SimpleNamespace(TradingAgentsGraph=factory),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "temporary")
    result = worker.run_analysis(
        {"symbol": "TCS.NS", "day": "2026-09-07", "mode": "ai"},
        {
            "provider": "openai",
            "api_key": "test-only",
            "quick_model": "model",
            "deep_model": "model",
        },
    )
    assert result["decision_signal"] == "HOLD"
    assert result["market_report"] == "evidence"
    assert factory.call_args.kwargs["config"]["max_debate_rounds"] == 1


def test_snapshot_run_does_not_need_credentials(monkeypatch):
    monkeypatch.setattr(worker, "market_snapshot", lambda *_: {"close": 123})
    assert worker.run_analysis(
        {"symbol": "TCS.NS", "day": "2026-09-07", "mode": "snapshot"}, {}
    ) == {"market_snapshot": {"close": 123}}


@pytest.mark.parametrize(
    "mode,exception",
    [
        ("snapshot", "ValueError"),
        ("ai", "AuthenticationError"),
        ("ai", "RateLimitError"),
        ("ai", "RuntimeError"),
    ],
)
def test_worker_errors_do_not_expose_secrets(store, monkeypatch, mode, exception):
    job_id = store.enqueue("TCS.NS", "2026-09-07", mode)
    store.claim()

    def fail(*_):
        raise type(exception, (Exception,), {})("secret-provider-key-DO-NOT-LEAK")

    monkeypatch.setattr(worker, "run_analysis", fail)
    worker.child(store.root, job_id)
    job = store.job(job_id)
    assert job["status"] == "failed"
    assert "secret-provider-key" not in job["error"]


def test_child_finishes_result_and_rejects_unclaimed(store, monkeypatch):
    job_id = store.enqueue("TCS.NS", "2026-09-07", "snapshot")
    with pytest.raises(SystemExit):
        worker.child(store.root, job_id)
    store.claim()
    monkeypatch.setattr(worker, "run_analysis", lambda *_: {"market_snapshot": {"close": 123}})
    worker.child(store.root, job_id)
    assert store.job(job_id)["status"] == "complete"


def test_timeout_kills_process_group_and_marks_failed(store, monkeypatch):
    job_id = store.enqueue("TCS.NS", "2026-09-07", "snapshot")
    job = store.claim()
    process = Mock(pid=123)
    process.wait.side_effect = [subprocess.TimeoutExpired("worker", 1), 0]
    monkeypatch.setattr(worker.subprocess, "Popen", Mock(return_value=process))
    kill = Mock()
    monkeypatch.setattr(worker.os, "killpg", kill)
    worker.execute(store, job, timeout=1)
    kill.assert_called_once_with(123, worker.signal.SIGKILL)
    assert store.job(job_id)["status"] == "failed"


def test_unexpected_child_exit_is_marked_failed(store, monkeypatch):
    job_id = store.enqueue("TCS.NS", "2026-09-07", "snapshot")
    job = store.claim()
    process = Mock()
    process.wait.return_value = 1
    monkeypatch.setattr(worker.subprocess, "Popen", Mock(return_value=process))
    worker.execute(store, job)
    assert store.job(job_id)["status"] == "failed"
