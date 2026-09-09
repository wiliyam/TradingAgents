"""Turn stored research into explicit display fields, without inferred AI confidence."""

import math

AGENTS = [
    ("market_report", "Market analyst", "Analysis"),
    ("fundamentals_report", "Fundamentals analyst", "Analysis"),
    ("news_report", "News analyst", "Analysis"),
    ("sentiment_report", "Sentiment analyst", "Analysis"),
    ("bull_history", "Bull researcher", "Research debate"),
    ("bear_history", "Bear researcher", "Research debate"),
    ("investment_plan", "Research manager", "Research debate"),
    ("trader_investment_plan", "Trader", "Trade proposal"),
    ("aggressive_history", "Aggressive risk analyst", "Risk debate"),
    ("conservative_history", "Conservative risk analyst", "Risk debate"),
    ("neutral_history", "Neutral risk analyst", "Risk debate"),
    ("final_trade_decision", "Portfolio manager", "Final decision"),
]


def visible_state(state):
    result = {key: str(state[key])[:100000] for key, _, _ in AGENTS if state.get(key)}
    for name in ("investment_debate_state", "risk_debate_state"):
        debate = state.get(name) or {}
        if isinstance(debate, dict):
            for key, _, _ in AGENTS:
                if debate.get(key):
                    result[key] = str(debate[key])[:100000]
    return result


def present(job):
    result = job.get("result") or {}
    progress = job.get("progress") or {}
    reports = visible_state(result)
    reports.update({key: value["content"] for key, value in progress.items() if key not in reports})
    snapshot = (
        result.get("market_snapshot") or progress.get("market_snapshot", {}).get("content") or {}
    )
    if not isinstance(snapshot, dict):
        snapshot = {}
    agents = [
        {
            "id": key,
            "name": name,
            "stage": stage,
            "content": reports.get(key, ""),
            "status": "complete"
            if reports.get(key)
            else ("unavailable" if job.get("status") in ("complete", "failed") else "pending"),
            "updated": progress.get(key, {}).get("updated"),
        }
        for key, name, stage in AGENTS
    ]
    checks = []
    for key, label in [
        ("sma_20", "Price above 20-day average"),
        ("sma_50", "Price above 50-day average"),
        ("rsi_14", "RSI between 50 and 70"),
    ]:
        val, close = snapshot.get(key), snapshot.get("close")
        valid = (
            isinstance(val, (int, float))
            and math.isfinite(val)
            and isinstance(close, (int, float))
            and math.isfinite(close)
        )
        passed = ((50 <= val <= 70) if key == "rsi_14" else close > val) if valid else None
        checks.append({"label": label, "passed": passed})
    available = [check for check in checks if check["passed"] is not None]
    score = (
        round(100 * sum(check["passed"] for check in available) / len(available))
        if len(available) == 3
        else None
    )
    signal = str(result.get("decision_signal", "")).strip().title()
    if signal not in ("Buy", "Overweight", "Hold", "Underweight", "Sell"):
        signal = "Not available"
    return {
        "snapshot": snapshot,
        "agents": agents,
        "signal": signal,
        "completion": {"completed": sum(bool(a["content"]) for a in agents), "total": len(agents)},
        "technical": {
            "score": score,
            "checks": checks,
            "description": "Bullish technical checklist: one point each for price above SMA20, price above SMA50, and RSI14 between 50 and 70. Not AI confidence or a probability of profit.",
        },
    }
