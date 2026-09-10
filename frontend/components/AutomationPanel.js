"use client";
import { useEffect, useState } from "react";

const money = (v) =>
  Number(v).toLocaleString("en-IN", { maximumFractionDigits: 2 });
function download(value, name) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function EquityCurve({ result }) {
  const rows = result.curve || [];
  if (!rows.length) return null;
  const low = Math.min(...rows.map((r) => r.equity)),
    high = Math.max(...rows.map((r) => r.equity));
  const points = rows
    .map(
      (r, i) =>
        `${30 + (i / Math.max(1, rows.length - 1)) * 740},${190 - ((r.equity - low) / Math.max(1, high - low)) * 160}`,
    )
    .join(" ");
  return (
    <>
      <svg
        viewBox="0 0 800 220"
        role="img"
        aria-label="Backtest equity curve"
        className="equity-curve"
      >
        <polyline
          points={points}
          fill="none"
          stroke="#63dbc0"
          strokeWidth="2"
        />
        <text x="30" y="15" fill="currentColor">
          ₹{money(high)}
        </text>
        <text x="30" y="214" fill="currentColor">
          ₹{money(low)}
        </text>
      </svg>
      <p className="chart-help">
        {new Date(rows[0].time * 1000).toLocaleDateString()} —{" "}
        {new Date(rows.at(-1).time * 1000).toLocaleDateString()} · Equity
        includes open positions at closing prices.
      </p>
    </>
  );
}
export default function AutomationPanel({ api, csrf, instrumentKey }) {
  const [state, setState] = useState(null),
    [error, setError] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false),
    [result, setResult] = useState(null);
  async function refresh() {
    setState(await api("/api/market/automation"));
  }
  useEffect(() => {
    let alive = true;
    const load = () =>
      api("/api/market/automation")
        .then((v) => {
          if (alive) setState(v);
        })
        .catch((e) => {
          if (alive) setError(e.message);
        });
    load();
    const timer = setInterval(load, 15000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [api]);
  async function command(action, values = {}) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const body = new FormData();
      body.set("csrf", csrf);
      Object.entries(values).forEach(([k, v]) => body.set(k, String(v)));
      const value = await api("/api/market/" + action, {
        method: "POST",
        body,
      });
      setMessage(value.message || "Risk settings saved.");
      if (value.result) setResult(value.result);
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  const shown = result || state?.backtests?.[0]?.result;
  return (
    <section className="automation-panel panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">PAPER AUTOMATION</p>
          <h2>Strategy lab & controls</h2>
        </div>
        <button
          className="danger-button"
          disabled={busy}
          onClick={() => command("halt")}
        >
          Halt all paper execution
        </button>
      </div>
      <p>
        Cash equities · Long only · One running strategy per instrument · Real
        execution disabled
      </p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {message && <p role="status">{message}</p>}
      <p>
        Execution:{" "}
        <strong>
          {state?.risk?.halted
            ? "HALTED"
            : state
              ? "Paper controls active"
              : "Loading"}
        </strong>{" "}
        · Scheduler:{" "}
        {state?.heartbeat
          ? new Date(state.heartbeat * 1000).toLocaleTimeString()
          : "Awaiting heartbeat"}
      </p>
      <p className="chart-help">
        The kill switch blocks new paper fills; it does not close positions.
        Strategies pause after service restarts. Feed availability and fresh
        quotes are required to execute.
      </p>
      <details open>
        <summary>Create strategy / run historical simulation</summary>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const values = Object.fromEntries(new FormData(e.currentTarget));
            command(e.nativeEvent.submitter?.value || "strategy-save", values);
          }}
        >
          <div className="automation-fields">
            <label>
              Name
              <input
                name="name"
                defaultValue="SMA trend"
                required
                maxLength={80}
              />
            </label>
            <label>
              Instrument token
              <input
                key={instrumentKey}
                name="key"
                defaultValue={instrumentKey}
                placeholder="NSE:2885"
                required
                pattern="(NSE|BSE):[0-9]{1,12}"
              />
            </label>
            <label>
              Interval
              <select name="interval" defaultValue="5m">
                {["1m", "5m", "15m", "1h", "1d"].map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </label>
            <label>
              Fast SMA
              <input
                name="fast"
                type="number"
                min="2"
                max="100"
                defaultValue="10"
                required
              />
            </label>
            <label>
              Slow SMA
              <input
                name="slow"
                type="number"
                min="3"
                max="200"
                defaultValue="30"
                required
              />
            </label>
            <label>
              Shares per entry
              <input
                name="quantity"
                type="number"
                min="1"
                max="100000"
                defaultValue="1"
                required
              />
            </label>
            <label>
              Backtest capital ₹
              <input
                name="capital"
                type="number"
                min="100"
                max="10000000"
                defaultValue="1000000"
                required
              />
            </label>
            <label>
              Fees per side (bps)
              <input
                name="fee_bps"
                type="number"
                min="0"
                max="500"
                step="0.1"
                defaultValue="5"
                required
              />
            </label>
            <label>
              Slippage per side (bps)
              <input
                name="slippage_bps"
                type="number"
                min="0"
                max="500"
                step="0.1"
                defaultValue="5"
                required
              />
            </label>
          </div>
          <details>
            <summary>Import candles for offline backtesting</summary>
            <p>
              Optional JSON array with numeric time (Unix seconds), open, high,
              low, close, volume. Increasing timestamps, up to 12 KB. Imported
              data is labelled separately from broker data.
            </p>
            <textarea
              name="candles"
              aria-label="Imported candle JSON"
              maxLength={12000}
              rows={5}
              placeholder='[{"time":1700000000,"open":100,"high":102,"low":99,"close":101,"volume":500}]'
            />
          </details>
          <p className="chart-help">
            Enter when fast SMA is above slow SMA and the instrument is flat;
            exit held shares when below. Automation uses completed bars and
            fresh LTP. It manages the instrument’s shared paper position,
            including manually bought shares. Backtests use next-bar open and
            configurable costs; paper fills currently exclude fees/slippage.
          </p>
          <div className="button-row">
            <button disabled={busy} value="strategy-save" type="submit">
              Save paused strategy
            </button>
            <button disabled={busy} value="backtest" type="submit">
              Run backtest
            </button>
          </div>
        </form>
      </details>
      <h3>Saved strategies</h3>
      {!state?.strategies?.length && <p>No strategies saved.</p>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Strategy</th>
              <th>Instrument / rule</th>
              <th>Status</th>
              <th>Last evaluation</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {state?.strategies?.map((s) => (
              <tr key={s.id}>
                <td>{s.config.name}</td>
                <td>
                  {s.config.key} · SMA {s.config.fast}/{s.config.slow} ·{" "}
                  {s.config.interval}
                </td>
                <td>{s.status}</td>
                <td>{s.message || "Not started"}</td>
                <td>
                  <button
                    disabled={
                      busy || (s.status !== "running" && state.risk.halted)
                    }
                    onClick={() =>
                      command(
                        s.status === "running"
                          ? "strategy-pause"
                          : "strategy-start",
                        { id: s.id },
                      )
                    }
                  >
                    {s.status === "running" ? "Pause" : "Start paper"}
                  </button>
                  <button
                    disabled={busy || s.status === "running"}
                    onClick={() => command("strategy-delete", { id: s.id })}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {shown && (
        <div>
          <h3>Historical simulation</h3>
          <div className="automation-metrics">
            <span>Ending equity ₹{money(shown.ending_equity)}</span>
            <span>Return {shown.return_pct}%</span>
            <span>Max drawdown {shown.max_drawdown_pct}%</span>
            <span>Fees ₹{money(shown.fees)}</span>
            <span>{shown.trades.length} fills</span>
          </div>
          <EquityCurve result={shown} />
          <p className="chart-help">
            Source: {shown.source || "Not provided"}. {shown.model}
          </p>
          <button onClick={() => download(shown, "backtest.json")}>
            Export backtest
          </button>
        </div>
      )}
      <details>
        <summary>Risk limits</summary>
        {state && (
          <form
            key={JSON.stringify(state.risk)}
            onSubmit={(e) => {
              e.preventDefault();
              command(
                "risk",
                Object.fromEntries(new FormData(e.currentTarget)),
              );
            }}
          >
            <div className="automation-fields">
              {Object.entries({
                max_order_value: "Maximum order value ₹",
                max_position_cost: "Maximum position cost ₹",
                max_invested_capital: "Maximum invested capital ₹",
                max_daily_realized_loss: "Daily realized loss limit ₹",
                max_daily_orders: "Daily order limit",
              }).map(([key, label]) => (
                <label key={key}>
                  {label}
                  <input
                    name={key}
                    type="number"
                    min="1"
                    max={key === "max_daily_orders" ? "10000" : "10000000"}
                    defaultValue={state.risk[key]}
                    required
                  />
                </label>
              ))}
              <label>
                Kill switch
                <select name="halted" defaultValue={String(state.risk.halted)}>
                  <option value="false">Released</option>
                  <option value="true">Halted</option>
                </select>
              </label>
            </div>
            <p className="chart-help">
              Limits apply atomically to manual and automated paper fills. Daily
              limits reset at midnight IST. Loss limit uses realized P&L and
              blocks new buys; it is not an unrealized-loss stop. Exposure
              limits use invested cost.
            </p>
            <button disabled={busy}>Save risk limits</button>
          </form>
        )}
      </details>
      <details>
        <summary>
          Audit trail ({state?.audit?.length || 0} latest events)
        </summary>
        <button
          onClick={() => download(state?.audit || [], "paper-audit.json")}
        >
          Export audit
        </button>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Event</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {state?.audit?.map((e) => (
                <tr key={e.id}>
                  <td>{new Date(e.created * 1000).toLocaleString()}</td>
                  <td>{e.kind}</td>
                  <td>{JSON.stringify(e.detail)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}
