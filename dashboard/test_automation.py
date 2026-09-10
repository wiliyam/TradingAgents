import time

import pytest

from dashboard.broker.automation import backtest, validate_strategy
from dashboard.broker.core import BrokerError, PaperLedger


def bars(prices):
    return [
        {"time": 1000 + i * 300, "open": p, "high": p + 1, "low": p - 1, "close": p, "volume": 100}
        for i, p in enumerate(prices)
    ]


def test_strategy_rejects_invalid_and_live():
    for fields in (
        {"mode": "live"},
        {"fast": "5", "slow": "3"},
        {"fast": "nan"},
        {"quantity": True},
    ):
        with pytest.raises(BrokerError):
            validate_strategy(fields)


def test_backtest_next_open_and_costs():
    cfg = validate_strategy(
        {"name": "Trend", "key": "NSE:2885", "fast": 2, "slow": 3, "quantity": 1}
    )
    data = bars([100, 101, 103, 110, 111, 90, 89, 88])
    result = backtest(data, cfg, capital=1000, fee_bps=10, slippage_bps=10)
    assert result["trades"][0]["time"] == data[3]["time"]
    assert result["trades"][0]["price"] > data[3]["open"]
    assert result["fees"] > 0
    assert result["ending_equity"] < 1000
    assert result["max_drawdown_pct"] > 0


def test_backtest_rejects_duplicate_or_bad_candles():
    cfg = validate_strategy({"name": "Trend", "key": "NSE:2885", "fast": 2, "slow": 3})
    for data in (bars([100] * 5)[::-1], bars([100] * 5) + bars([100]), bars([float("nan")] * 5)):
        with pytest.raises(BrokerError):
            backtest(data, cfg)


def test_risk_and_halt_enforced_in_ledger(tmp_path):
    ledger = PaperLedger(tmp_path)
    item = {"key": "NSE:2885", "symbol": "RELIANCE-EQ", "exchange": "NSE", "token": "2885"}
    tick = {"price": 100, "timestamp": time.time(), "received": time.time()}
    order = {"mode": "paper", "request_id": "a" * 32, "side": "BUY", "quantity": 1}
    ledger.set_risk({"max_order_value": 50})
    with pytest.raises(BrokerError, match="order value"):
        ledger.fill(order, item, tick)
    ledger.set_risk({"max_order_value": 1000})
    ledger.fill(order, item, tick)
    ledger.set_risk({"halted": True})
    assert ledger.fill(order, item, tick)["id"] == "a" * 32
    with pytest.raises(BrokerError, match="halted"):
        ledger.fill({**order, "request_id": "b" * 32}, item, tick)
    assert len(ledger.audit()) >= 3


class FakeEngine:
    def __init__(self, root):
        self.ledger = PaperLedger(root)
        self.connected = True
        self.item = {
            "key": "NSE:2885",
            "symbol": "RELIANCE-EQ",
            "exchange": "NSE",
            "token": "2885",
            "kind": "equity",
        }
        end = int(time.time() // 300) * 300 - 300
        self.data = [
            {**b, "time": end - (7 - i) * 300}
            for i, b in enumerate(bars([100, 101, 102, 103, 104, 105, 106, 107]))
        ]

    def instrument(self, key):
        return self.item

    def status(self):
        return {"connected": self.connected, "watchlist": [self.item]}

    def session_open(self):
        return True

    def candles(self, key, interval):
        return {"candles": self.data, "seconds": 300, "source": "Test fixture"}

    def paper_order(self, order):
        return self.ledger.fill(
            order, self.item, {"price": 110, "timestamp": time.time(), "received": time.time()}
        )


def test_strategy_lifecycle_no_duplicate_and_restart_pauses(tmp_path):
    from dashboard.broker.automation import Automation

    engine = FakeEngine(tmp_path)
    runner = Automation(engine)
    sid = runner.command(
        "strategy-save", {"name": "Test", "key": "NSE:2885", "fast": 2, "slow": 3}
    )["id"]
    assert runner.state()["strategies"][0]["status"] == "paused"
    runner.command("strategy-start", {"id": sid})
    runner.evaluate()
    runner.evaluate()
    assert len(engine.ledger.summary({})["orders"]) == 1
    assert runner.state()["strategies"][0]["last_bar"] > 0
    with pytest.raises(BrokerError):
        runner.command("strategy-delete", {"id": sid})
    restarted = Automation(engine)
    assert restarted.state()["strategies"][0]["status"] == "paused"
    restarted.command("strategy-start", {"id": sid})
    restarted.command("halt", {})
    assert engine.ledger.risk()["halted"]
    with pytest.raises(BrokerError):
        restarted.command("strategy-start", {"id": sid})
    restarted.command("strategy-delete", {"id": sid})
    assert restarted.state()["strategies"] == []


def test_strategy_offline_and_stale_fail_closed(tmp_path):
    from dashboard.broker.automation import Automation

    engine = FakeEngine(tmp_path)
    runner = Automation(engine)
    sid = runner.command(
        "strategy-save", {"name": "Test", "key": "NSE:2885", "fast": 2, "slow": 3}
    )["id"]
    engine.connected = False
    with pytest.raises(BrokerError, match="connected"):
        runner.command("strategy-start", {"id": sid})
    runner.evaluate()
    assert not engine.ledger.summary({})["orders"]
    engine.connected = True
    runner.command("strategy-start", {"id": sid})
    for bar in engine.data:
        bar["time"] -= 86400
    runner.evaluate()
    assert "stale" in runner.state()["strategies"][0]["message"]
    assert not engine.ledger.summary({})["orders"]


def test_backtest_saved_and_imported_source(tmp_path):
    import json

    from dashboard.broker.automation import Automation

    runner = Automation(FakeEngine(tmp_path))
    fields = {
        "name": "Test",
        "key": "NSE:2885",
        "fast": 2,
        "slow": 3,
        "candles": json.dumps(bars([100, 101, 102, 103, 104, 100, 99])),
    }
    result = runner.run_backtest(fields)
    assert result["result"]["trades"]
    assert "Owner-imported" in runner.state()["backtests"][0]["source"]
    with pytest.raises(BrokerError):
        runner.run_backtest({**fields, "candles": "invalid"})


@pytest.mark.parametrize(
    "field,value",
    [
        ("fast", 1),
        ("slow", 201),
        ("quantity", 0),
        ("quantity", True),
        ("interval", "3m"),
        ("mode", "live"),
    ],
)
def test_strategy_field_validation(field, value):
    cfg = {"name": "Test", "key": "NSE:2885", "fast": 2, "slow": 3}
    with pytest.raises(BrokerError):
        validate_strategy({**cfg, field: value})


@pytest.mark.parametrize(
    "setting,value",
    [
        ("max_order_value", float("nan")),
        ("max_daily_orders", 1.5),
        ("halted", "false"),
        ("unknown", 1),
    ],
)
def test_invalid_risk_settings(tmp_path, setting, value):
    with pytest.raises(BrokerError):
        PaperLedger(tmp_path).set_risk({setting: value})


def test_position_exposure_daily_order_limits(tmp_path):
    engine = FakeEngine(tmp_path)
    ledger = engine.ledger
    ledger.set_risk({"max_position_cost": 100})
    order = {"mode": "paper", "request_id": "c" * 32, "side": "BUY", "quantity": 1}
    with pytest.raises(BrokerError, match="position"):
        engine.paper_order(order)
    ledger.set_risk({"max_position_cost": 1000, "max_invested_capital": 100})
    with pytest.raises(BrokerError, match="invested"):
        engine.paper_order(order)
    ledger.set_risk({"max_invested_capital": 1000, "max_daily_orders": 1})
    engine.paper_order(order)
    with pytest.raises(BrokerError, match="Daily paper order"):
        engine.paper_order({**order, "request_id": "d" * 32})


def test_daily_realized_loss_blocks_buys_but_allows_exits(tmp_path):
    engine = FakeEngine(tmp_path)
    ledger = engine.ledger
    ledger.set_risk({"max_daily_realized_loss": 1})
    order = {"mode": "paper", "request_id": "1" * 32, "side": "BUY", "quantity": 2}
    engine.paper_order(order)
    ledger.fill(
        {**order, "request_id": "2" * 32, "side": "SELL", "quantity": 1},
        engine.item,
        {"price": 100, "timestamp": time.time(), "received": time.time()},
    )
    with pytest.raises(BrokerError, match="realized loss"):
        engine.paper_order({**order, "request_id": "3" * 32})
    engine.paper_order({**order, "request_id": "4" * 32, "side": "SELL", "quantity": 1})


def test_automation_api_auth_and_commands(tmp_path):
    import json
    from unittest.mock import Mock

    from fastapi.testclient import TestClient

    from dashboard.broker.automation import Automation
    from dashboard.broker.service import create_market_app, internal_key

    (tmp_path / "auth.json").write_text(
        json.dumps({"secret": "fixture-secret", "epoch": "one", "must_change": False})
    )
    engine = FakeEngine(tmp_path)
    engine.start = Mock()
    engine.stop = Mock()
    engine.automation = Automation(engine)
    headers = {"x-market-key": internal_key("fixture-secret")}
    with TestClient(create_market_app(tmp_path, engine=engine, testing=True)) as client:
        assert client.get("/automation").status_code == 401
        assert client.get("/automation", headers=headers).status_code == 200
        assert (
            client.post("/command/risk", headers=headers, json={"halted": "garbage"}).status_code
            == 400
        )
        assert client.post("/command/halt", headers=headers, json={}).status_code == 200
        assert client.get("/automation", headers=headers).json()["risk"]["halted"] is True
        assert (
            client.post("/command/risk", headers=headers, json={"halted": "false"}).status_code
            == 200
        )
        fields = {"name": "Test", "key": "NSE:2885", "fast": 2, "slow": 3}
        response = client.post("/command/strategy-save", headers=headers, json=fields)
        sid = response.json()["id"]
        assert (
            client.post("/command/strategy-start", headers=headers, json={"id": sid}).status_code
            == 200
        )
        assert (
            client.post("/command/strategy-pause", headers=headers, json={"id": sid}).status_code
            == 200
        )
        assert (
            client.post(
                "/command/backtest",
                headers=headers,
                json={**fields, "candles": bars([100, 101, 102, 103, 104, 100, 99])},
            ).status_code
            == 200
        )


def test_daily_automation_rejected_and_export_has_provenance(tmp_path):
    from dashboard.broker.automation import Automation

    runner = Automation(FakeEngine(tmp_path))
    fields = {"name": "Daily", "key": "NSE:2885", "fast": 2, "slow": 3, "interval": "1d"}
    with pytest.raises(BrokerError, match="backtests only"):
        runner.command("strategy-save", fields)
    value = runner.run_backtest({**fields, "candles": bars([100, 101, 102, 103, 104, 100])})[
        "result"
    ]
    assert value["strategy"]["interval"] == "1d"
    assert "Owner-imported" in value["source"]
    assert len(value["data_sha256"]) == 64
