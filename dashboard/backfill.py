"""Recover historical debate outputs only when saved reports identify the same run."""

import argparse
import json
from pathlib import Path

from dashboard.presentation import visible_state
from dashboard.store import Store


def recover_reports(store, logs):
    count = 0
    for summary in store.jobs():
        if summary["status"] != "complete" or summary["mode"] != "ai":
            continue
        job = store.job(summary["id"])
        result = job["result"] or {}
        path = (
            Path(logs)
            / summary["symbol"]
            / "TradingAgentsStrategy_logs"
            / f"full_states_log_{summary['day']}.json"
        )
        if not path.is_file():
            continue
        state = json.loads(path.read_text())
        keys = (
            "market_report",
            "fundamentals_report",
            "news_report",
            "sentiment_report",
            "final_trade_decision",
        )
        if (
            state.get("company_of_interest") != summary["symbol"]
            or state.get("trade_date") != summary["day"]
        ):
            continue
        if not all(result.get(k) and result[k] == state.get(k) for k in keys):
            continue
        extra = {k: v for k, v in visible_state(state).items() if k not in result}
        if extra:
            store.finish(job["id"], result={**result, **extra})
            count += 1
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--logs", required=True)
    args = parser.parse_args()
    print(
        "Recovered debate history for",
        recover_reports(Store(args.state), args.logs),
        "matching reports.",
    )
