"""One bounded analysis subprocess at a time; never places brokerage orders."""

import contextlib
import copy
import math
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from dashboard.store import Store

KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}


def market_snapshot(symbol, day):
    import yfinance as yf

    end = datetime.strptime(day, "%Y-%m-%d")
    ticker = yf.Ticker(symbol)
    bars = ticker.history(
        start=(end - timedelta(days=200)).strftime("%Y-%m-%d"),
        end=(end + timedelta(days=1)).strftime("%Y-%m-%d"),
        interval="1d",
        auto_adjust=True,
        timeout=25,
    )
    if bars.empty:
        raise ValueError("No market data returned")
    bars = bars.dropna(subset=["Close"])
    bars = bars[[stamp.date() <= end.date() for stamp in bars.index]]
    if bars.empty or (end.date() - bars.index[-1].date()).days > 10:
        raise ValueError("Market data was missing or stale")
    close = bars["Close"]
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean().iloc[-1]
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean().iloc[-1]
    rsi = 100 - 100 / (1 + gain / loss) if loss else (100 if gain else 50)

    def number(value):
        return round(float(value), 2) if math.isfinite(float(value)) else None

    return {
        "source": "Yahoo Finance · adjusted daily prices · may be delayed",
        "symbol": symbol,
        "currency": "INR",
        "requested_date": day,
        "latest_bar_date": bars.index[-1].date().isoformat(),
        "close": number(close.iloc[-1]),
        "previous_close": number(close.iloc[-2]) if len(close) > 1 else None,
        "daily_change_percent": number((close.iloc[-1] / close.iloc[-2] - 1) * 100)
        if len(close) > 1
        else None,
        "sma_20": number(close.tail(20).mean()) if len(close) >= 20 else None,
        "sma_50": number(close.tail(50).mean()) if len(close) >= 50 else None,
        "rsi_14": number(rsi),
        "volume": number(bars["Volume"].iloc[-1]),
        "bars": [
            {
                "date": stamp.date().isoformat(),
                **{
                    key.lower(): number(row[key]) if key in row else None
                    for key in ("Open", "High", "Low", "Close", "Volume")
                },
                "sma20": number(close.rolling(20).mean().loc[stamp]),
                "sma50": number(close.rolling(50).mean().loc[stamp]),
            }
            for stamp, row in bars.iterrows()
        ],
        "recent_closes": [
            {"date": stamp.date().isoformat(), "close": number(value)}
            for stamp, value in close.tail(20).items()
        ],
    }


def run_analysis(job, settings):
    snapshot = market_snapshot(job["symbol"], job["day"])
    progress_store = (
        Store(os.environ["DASHBOARD_STATE_DIR"])
        if job.get("id") and os.environ.get("DASHBOARD_STATE_DIR")
        else None
    )
    if progress_store:
        progress_store.progress(job["id"], {"market_snapshot": snapshot})
    if job["mode"] == "snapshot":
        return {"market_snapshot": snapshot}
    provider = settings["provider"]
    # Set only the selected provider's key, inside this short-lived subprocess.
    if provider != "codex_cli":
        os.environ[KEY_ENV[provider]] = settings["api_key"]
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    config = copy.deepcopy(DEFAULT_CONFIG)
    config.update(
        llm_provider=provider,
        quick_think_llm=settings["quick_model"],
        deep_think_llm=settings["deep_model"],
        max_debate_rounds=1,
        max_risk_discuss_rounds=1,
        llm_max_retries=1,
        max_tokens=4096,
        checkpoint_enabled=False,
        backend_url=None,
    )
    graph = TradingAgentsGraph(config=config, debug=False)
    if progress_store:
        from dashboard.presentation import visible_state

        graph.progress_callback = lambda state: progress_store.progress(
            job["id"], visible_state(state)
        )
    state, decision = graph.propagate(job["symbol"], job["day"])
    result = {"market_snapshot": snapshot, "decision_signal": str(decision)}
    if provider == "codex_cli":
        result["research_engine"] = "TradingAgents multi-agent workflow · Codex CLI · GPT-6 Astra"
    for key in (
        "market_report",
        "fundamentals_report",
        "news_report",
        "sentiment_report",
        "investment_plan",
        "trader_investment_plan",
        "final_trade_decision",
    ):
        if state.get(key):
            result[key] = str(state[key])[:100000]
    from dashboard.presentation import visible_state

    result.update(visible_state(state))
    return result


def child(root, job_id):
    store = Store(root)
    job = store.job(job_id)
    if not job or job["status"] != "running":
        raise SystemExit(1)
    try:
        # Provider libraries sometimes log request details. Do not retain raw output
        # in public reports or service logs; errors below deliberately omit secrets.
        with (
            open(os.devnull, "w") as sink,
            contextlib.redirect_stdout(sink),
            contextlib.redirect_stderr(sink),
        ):
            result = run_analysis(job, store.settings())
        store.finish(job_id, result=result)
    except Exception as exc:
        from tradingagents.llm_clients.codex_client import CodexError

        name = type(exc).__name__
        if isinstance(exc, CodexError):
            error = str(exc)
        elif job["mode"] == "snapshot":
            error = "Market data could not be retrieved. Check the ticker/date and try again; the data provider may be unavailable or rate-limiting this server."
        elif "Authentication" in name or "Permission" in name:
            error = "The model provider rejected authentication. Check your API key, account access and selected models in Settings."
        elif "RateLimit" in name:
            error = "The model provider's rate or credit limit was reached. Check your provider account and retry later."
        else:
            error = "AI research could not complete. Verify the ticker, model IDs, API key and provider credit, then retry. A market snapshot can help check data availability."
        store.finish(job_id, error=error)
    else:
        from dashboard.telegram import notify_completed

        notify_completed(store, store.job(job_id))


def execute(store, job, timeout=1200):
    process = subprocess.Popen(
        [sys.executable, "-m", "dashboard.worker", "--job", job["id"]],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        store.finish(
            job["id"],
            error="Analysis exceeded the 20-minute limit. Try a faster model or a market snapshot.",
        )
    finally:
        current = store.job(job["id"])
        if current["status"] == "running":
            store.finish(job["id"], error="Analysis stopped unexpectedly. Please try again.")


def main():
    os.umask(0o077)
    root = Path(os.environ.get("DASHBOARD_STATE_DIR", "/var/lib/tradingagents/dashboard"))
    if len(sys.argv) == 3 and sys.argv[1] == "--job":
        child(root, sys.argv[2])
        return
    store = Store(root)
    store.recover()
    while True:
        job = store.claim()
        if job:
            execute(store, job)
        else:
            time.sleep(2)


if __name__ == "__main__":
    main()
