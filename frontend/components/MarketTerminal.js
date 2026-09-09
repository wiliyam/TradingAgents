"use client";
import { useEffect, useRef, useState } from "react";
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  ColorType,
} from "lightweight-charts";
import { number } from "../lib/research.mjs";
import { applyTick } from "../lib/live-chart.mjs";

function LiveChart({ history, tick, interval }) {
  const container = useRef(null),
    chartRef = useRef(null),
    barsRef = useRef([]),
    volumeRef = useRef(null),
    lastTick = useRef(0);
  useEffect(() => {
    if (!container.current) return;
    const chart = createChart(container.current, {
      autoSize: true,
      height: 430,
      layout: {
        background: { type: ColorType.Solid, color: "#11191f" },
        textColor: "#9babb5",
        attributionLogo: true,
      },
      grid: {
        vertLines: { color: "#1c2a31" },
        horzLines: { color: "#1c2a31" },
      },
      rightPriceScale: { borderColor: "#30414b" },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderColor: "#30414b",
      },
      localization: {
        locale: "en-IN",
        timeFormatter: (t) =>
          new Date(Number(t) * 1000).toLocaleString("en-IN", {
            timeZone: "Asia/Kolkata",
            day: "2-digit",
            month: "short",
            hour: "2-digit",
            minute: "2-digit",
          }),
      },
    });
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: "#b6ed79",
      downColor: "#f08d91",
      wickUpColor: "#b6ed79",
      wickDownColor: "#f08d91",
      borderVisible: false,
    });
    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    volume
      .priceScale()
      .applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });
    candles
      .priceScale()
      .applyOptions({ scaleMargins: { top: 0.08, bottom: 0.2 } });
    const average = chart.addSeries(LineSeries, {
      color: "#87b8f2",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    chartRef.current = { chart, candles, volume, average };
    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, []);
  useEffect(() => {
    const c = chartRef.current;
    if (!c) return;
    barsRef.current = (history?.candles || []).map((b) => ({ ...b }));
    volumeRef.current = null;
    lastTick.current = 0;
    c.candles.setData(barsRef.current);
    c.volume.setData(
      barsRef.current.map((b) => ({
        time: b.time,
        value: b.volume,
        color: b.close >= b.open ? "#334b35" : "#56373c",
      })),
    );
    c.average.setData(
      barsRef.current.flatMap((b, i) =>
        i < 19
          ? []
          : [
              {
                time: b.time,
                value:
                  barsRef.current
                    .slice(i - 19, i + 1)
                    .reduce((sum, x) => sum + x.close, 0) / 20,
              },
            ],
      ),
    );
    c.chart.timeScale().fitContent();
  }, [history]);
  useEffect(() => {
    const c = chartRef.current;
    if (!c || !history || !tick || tick.timestamp <= lastTick.current) return;
    const { bar, volume } = applyTick(
      barsRef.current,
      tick,
      history.seconds,
      volumeRef.current,
    );
    if (!bar) return;
    volumeRef.current = volume;
    lastTick.current = tick.timestamp;
    if (barsRef.current.at(-1)?.time === bar.time)
      barsRef.current[barsRef.current.length - 1] = bar;
    else barsRef.current.push(bar);
    c.candles.update(bar);
    c.volume.update({
      time: bar.time,
      value: bar.volume,
      color: bar.close >= bar.open ? "#334b35" : "#56373c",
    });
    if (barsRef.current.length >= 20)
      c.average.update({
        time: bar.time,
        value:
          barsRef.current.slice(-20).reduce((sum, b) => sum + b.close, 0) / 20,
      });
  }, [tick, history]);
  return (
    <>
      <div
        ref={container}
        className="live-chart"
        role="img"
        aria-label={`Interactive Angel One ${interval} candlestick chart`}
      />
      <p className="chart-help">
        Scroll to zoom · Drag to pan · Crosshair for price/time · SMA 20 in blue
        · Display times: IST
      </p>
      <p className="muted chart-help">
        Live candle volume counts changes observed after connection;
        reconnecting can leave partial volume. Charts by{" "}
        <a
          href="https://www.tradingview.com/lightweight-charts/"
          target="_blank"
          rel="noreferrer"
        >
          TradingView Lightweight Charts™
        </a>
        .
      </p>
    </>
  );
}
function Grid({ rows, columns, empty }) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            {columns.map(([key, label]) => (
              <th key={key}>{label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.id || r.orderid || i}>
              {columns.map(([key, label]) => (
                <td key={key}>
                  {typeof r[key] === "number"
                    ? number(r[key])
                    : String(r[key] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {!rows.length && (
        <div className="empty">{empty || "No records returned."}</div>
      )}
    </div>
  );
}
export default function MarketTerminal({ api, csrf }) {
  const [state, setState] = useState(null),
    [transport, setTransport] = useState("Connecting"),
    [selected, setSelected] = useState(""),
    [query, setQuery] = useState(""),
    [results, setResults] = useState([]),
    [interval, setInterval] = useState("5m"),
    [history, setHistory] = useState(null),
    [mode, setMode] = useState("paper"),
    [accountTab, setAccountTab] = useState("positions"),
    [paper, setPaper] = useState(null),
    [account, setAccount] = useState(null),
    [configuration, setConfiguration] = useState(false),
    [error, setError] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false),
    [chartError, setChartError] = useState("");
  const latest = useRef(null),
    selectedRef = useRef("");
  useEffect(() => {
    selectedRef.current = selected;
  }, [selected]);
  useEffect(() => {
    let alive = true,
      socket,
      retry;
    const update = (v) => {
      if (!alive) return;
      setState(v);
      latest.current = v;
      setSelected((old) =>
        v.watchlist.some((i) => i.key === old)
          ? old
          : v.watchlist[0]?.key || "",
      );
    };
    api("/api/market/status")
      .then(update)
      .catch((e) => setError(e.message));
    const connect = () => {
      if (!alive) return;
      socket = new WebSocket(
        `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/market/stream`,
      );
      socket.onopen = () => setTransport("Connected");
      socket.onmessage = (e) => {
        try {
          const v = JSON.parse(e.data);
          if (v.type === "market") update(v.data);
        } catch {
          setTransport("Invalid feed response");
        }
      };
      socket.onerror = () => setTransport("Reconnecting");
      socket.onclose = () => {
        if (alive) {
          setTransport("Reconnecting");
          retry = setTimeout(connect, 5000);
        }
      };
    };
    connect();
    // Fallback keeps connection status visible if the browser stream drops.
    const poll = setInterval(
      () =>
        api("/api/market/status")
          .then(update)
          .catch(() => {}),
      15000,
    );
    return () => {
      alive = false;
      clearInterval(poll);
      clearTimeout(retry);
      socket?.close();
    };
  }, [api]);
  useEffect(() => {
    if (query.trim().length < 2) {
      setResults([]);
      return;
    }
    let alive = true;
    const timer = setTimeout(
      () =>
        api("/api/market/search?q=" + encodeURIComponent(query))
          .then((v) => {
            if (alive) setResults(v.instruments);
          })
          .catch((e) => {
            if (alive) setError(e.message);
          }),
      400,
    );
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [query, api]);
  useEffect(() => {
    if (!selected || !state?.authenticated) {
      setHistory(null);
      return;
    }
    let alive = true;
    setChartError("");
    setHistory(null);
    api(
      `/api/market/candles?key=${encodeURIComponent(selected)}&interval=${interval}`,
    )
      .then((v) => {
        if (alive) setHistory(v);
      })
      .catch((e) => {
        if (alive) setChartError(e.message);
      });
    return () => {
      alive = false;
    };
  }, [selected, interval, state?.authenticated, api]);
  useEffect(() => {
    let alive = true;
    setAccount(null);
    const load = () => {
      if (mode === "paper")
        api("/api/market/paper")
          .then((v) => {
            if (alive) setPaper(v);
          })
          .catch((e) => {
            if (alive) setError(e.message);
          });
      else if (state?.authenticated)
        api("/api/market/portfolio?kind=" + accountTab)
          .then((v) => {
            if (alive) setAccount(v);
          })
          .catch((e) => {
            if (alive) setError(e.message);
          });
    };
    load();
    const timer = setInterval(load, mode === "paper" ? 5000 : 30000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [mode, accountTab, state?.authenticated, api]);
  async function command(operation, fields) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const body = new FormData();
      body.set("csrf", csrf);
      Object.entries(fields).forEach(([k, v]) => body.set(k, String(v)));
      const result = await api("/api/market/" + operation, {
        method: "POST",
        body,
      });
      setMessage(result.message || "Saved.");
      const v = await api("/api/market/status");
      setState(v);
      latest.current = v;
      if (operation === "paper-order") setPaper(await api("/api/market/paper"));
      return true;
    } catch (e) {
      setError(e.message);
      return false;
    } finally {
      setBusy(false);
    }
  }
  async function add(item) {
    if (await command("watch", { key: item.key, action: "add" })) {
      setSelected(item.key);
      setQuery("");
      setResults([]);
    }
  }
  const instrument = state?.watchlist.find((i) => i.key === selected),
    tick = state?.ticks[selected],
    fresh =
      state?.connected &&
      tick &&
      state.server_time - tick.timestamp <= 15 &&
      state.server_time - tick.timestamp >= 0;
  const liveRows = Array.isArray(account?.data)
    ? account.data
    : Array.isArray(account?.data?.holdings)
      ? account.data.holdings
      : [];
  const positions = paper?.positions || [],
    orders = paper?.orders || [];
  return (
    <div className="market-terminal">
      <div className="market-toolbar">
        <div className="segments">
          <button
            className={mode === "paper" ? "selected" : ""}
            onClick={() => setMode("paper")}
          >
            Paper trading
          </button>
          <button
            className={mode === "live" ? "selected" : ""}
            onClick={() => setMode("live")}
          >
            Live account · read only
          </button>
        </div>
        <div className="actions">
          <span className={"badge " + (state?.connected ? "positive" : "")}>
            {state?.connected ? "● Angel One connected" : "○ Angel One offline"}
          </span>
          <button
            className="secondary"
            onClick={() => setConfiguration(!configuration)}
          >
            Connect / settings
          </button>
        </div>
      </div>
      {error && (
        <div className="error" role="alert">
          {error}
          <button onClick={() => setError("")}>Dismiss</button>
        </div>
      )}
      {message && (
        <div className="notice" role="status">
          {message}
        </div>
      )}
      {configuration && (
        <section className="panel broker-config">
          <div>
            <h2>Angel One SmartAPI</h2>
            <p>
              Broker credentials stay on the server. Both environments use the
              same real market feed. The paper ledger is separate from your
              actual account.
            </p>
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                const form = e.currentTarget;
                const fields = Object.fromEntries(new FormData(form));
                if (await command("configure", fields)) form.reset();
              }}
            >
              <div className="broker-fields">
                <label>
                  API key
                  <input
                    name="api_key"
                    type="password"
                    autoComplete="new-password"
                    placeholder="Leave blank to keep saved value"
                  />
                </label>
                <label>
                  Client code
                  <input
                    name="client_code"
                    autoComplete="off"
                    placeholder={state?.client_code || "Angel One client code"}
                  />
                </label>
                <label>
                  PIN / password
                  <input
                    name="password"
                    type="password"
                    autoComplete="new-password"
                  />
                </label>
                <label>
                  TOTP setup secret (optional)
                  <input
                    name="totp_secret"
                    type="password"
                    autoComplete="new-password"
                    placeholder={
                      state?.has_totp_secret
                        ? "Saved · leave blank to keep"
                        : "Authenticator setup secret"
                    }
                  />
                </label>
              </div>
              <label className="checkbox">
                <input name="clear" value="yes" type="checkbox" /> Remove saved
                Angel One credentials
              </label>
              <button className="primary" disabled={busy}>
                Save credentials
              </button>
            </form>
          </div>
          <div>
            <h2>Session & feed</h2>
            <p>
              {state?.authenticated
                ? "Authenticated with Angel One."
                : "Save credentials, then connect."}
            </p>
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                const form = e.currentTarget;
                if (
                  await command(
                    "connect",
                    Object.fromEntries(new FormData(form)),
                  )
                )
                  form.reset();
              }}
            >
              <label>
                Current TOTP code
                <input
                  name="totp"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={6}
                  placeholder={
                    state?.has_totp_secret
                      ? "Generated from saved setup secret"
                      : "6-digit authenticator code"
                  }
                />
              </label>
              <button className="primary" disabled={busy || !state?.configured}>
                Connect Angel One
              </button>
            </form>
            <button
              className="secondary"
              disabled={busy}
              onClick={() => command("disconnect", {})}
            >
              Disconnect feed
            </button>
            <p className="muted">
              Browser stream: {transport}
              <br />
              Broker session renewal needs a saved TOTP secret or a new one-time
              code. Oracle public IP: 192.9.166.69.
            </p>
          </div>
        </section>
      )}
      {state?.error && <p className="callout">{state.error}</p>}
      <div className="market-workspace">
        <section className="panel watch-panel">
          <div className="panel-head">
            <h2>Watchlist</h2>
            <span className="badge">{state?.watchlist.length || 0}/50</span>
          </div>
          <label>
            Find NSE / BSE instruments
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search RELIANCE, TCS…"
              aria-label="Search instruments"
            />
          </label>
          {results.length > 0 && (
            <div className="instrument-results">
              {results.map((item) => (
                <button
                  key={item.key}
                  onClick={() => add(item)}
                  disabled={busy}
                >
                  <b>{item.symbol}</b>
                  <small>
                    {item.exchange} · {item.name}
                  </small>
                  <span>+</span>
                </button>
              ))}
            </div>
          )}
          <div className="watch-items">
            {state?.watchlist.map((item) => {
              const t = state.ticks[item.key];
              return (
                <div
                  key={item.key}
                  className={
                    selected === item.key ? "watch-item active" : "watch-item"
                  }
                >
                  <button onClick={() => setSelected(item.key)}>
                    <b>{item.symbol}</b>
                    <small>
                      {item.exchange} ·{" "}
                      {t
                        ? new Date(t.timestamp * 1000).toLocaleTimeString(
                            "en-IN",
                            { timeZone: "Asia/Kolkata" },
                          )
                        : "Awaiting quote"}
                    </small>
                  </button>
                  <button onClick={() => setSelected(item.key)}>
                    <b>{number(t?.price)}</b>
                    <small
                      className={
                        (t?.change_percent ?? 0) >= 0 ? "positive" : "negative"
                      }
                    >
                      {number(t?.change_percent)}%
                    </small>
                  </button>
                  <button
                    className="remove-instrument"
                    aria-label={"Remove " + item.symbol}
                    onClick={() =>
                      command("watch", { key: item.key, action: "remove" })
                    }
                  >
                    ×
                  </button>
                </div>
              );
            })}
          </div>
          {!state?.watchlist.length && (
            <div className="empty">
              Search and add instruments to start your watchlist.
            </div>
          )}
          <p className="chart-help">
            One shared broker WebSocket · Up to 50 selected instruments · Quotes
            retain their exchange timestamps.
          </p>
        </section>
        <section className="panel trading-chart-panel">
          <div className="panel-head">
            <div>
              <span className="eyebrow">
                ANGEL ONE · {instrument?.exchange || "INDIAN EQUITIES"}
              </span>
              <h2>{instrument?.symbol || "Select an instrument"}</h2>
            </div>
            <div className="segments">
              {["1m", "5m", "15m", "1h", "1d"].map((i) => (
                <button
                  key={i}
                  className={interval === i ? "selected" : ""}
                  onClick={() => setInterval(i)}
                >
                  {i}
                </button>
              ))}
            </div>
          </div>
          <div className="live-price">
            <strong>
              ₹{number(tick?.price ?? history?.candles.at(-1)?.close)}
            </strong>
            <span className={"badge " + (fresh ? "positive" : "")}>
              {fresh
                ? "Live quote"
                : tick
                  ? "Last received · stale / market closed"
                  : history
                    ? "Historical close"
                    : "Awaiting data"}
            </span>
            <span
              className={
                (tick?.change_percent ?? 0) >= 0 ? "positive" : "negative"
              }
            >
              {number(tick?.change_percent)}%
            </span>
          </div>
          <div className="chart-readout">
            <span>Open {number(tick?.open)}</span>
            <span>High {number(tick?.high)}</span>
            <span>Low {number(tick?.low)}</span>
            <span>Prev close {number(tick?.previous_close)}</span>
            <span>Volume {number(tick?.volume, 0)}</span>
          </div>
          {chartError && <p className="error">{chartError}</p>}
          <LiveChart history={history} tick={tick} interval={interval} />
          {!state?.authenticated && (
            <p className="callout">
              Connect Angel One to load historical candles and stream market
              prices.
            </p>
          )}
        </section>
        <section className="panel order-ticket">
          <span className="eyebrow">
            {mode === "paper" ? "SIMULATED EXECUTION" : "BROKER ACCOUNT"}
          </span>
          <h2>{mode === "paper" ? "Paper order" : "Live account connected"}</h2>
          {mode === "paper" ? (
            <>
              <p>
                Starting capital ₹10,00,000. Fills use fresh live LTP; no fees
                or slippage.
              </p>
              <div className="metric">
                <span>Paper cash</span>
                <strong>₹{number(paper?.cash)}</strong>
              </div>
              <form
                onSubmit={async (e) => {
                  e.preventDefault();
                  const fields = Object.fromEntries(
                    new FormData(e.currentTarget),
                  );
                  await command("paper-order", {
                    ...fields,
                    key: selected,
                    mode: "paper",
                    request_id: crypto.randomUUID().replaceAll("-", ""),
                  });
                }}
              >
                <label>
                  Instrument
                  <input value={instrument?.symbol || ""} readOnly />
                </label>
                <label>
                  Action
                  <select name="side">
                    <option value="BUY">Buy</option>
                    <option value="SELL">Sell held shares</option>
                  </select>
                </label>
                <label>
                  Quantity
                  <input
                    name="quantity"
                    type="number"
                    min={1}
                    max={100000}
                    step={1}
                    defaultValue={1}
                    required
                  />
                </label>
                <button
                  className="primary"
                  disabled={busy || !fresh || instrument?.kind === "index"}
                >
                  Place paper order
                </button>
              </form>
              {!fresh && (
                <p className="muted">
                  Fresh exchange data is required. Paper fills pause when the
                  market closes or the feed becomes stale.
                </p>
              )}
            </>
          ) : (
            <>
              <p>
                Your actual holdings, positions, funds and orders are shown
                below.
              </p>
              <div className="callout">
                Real-money order placement is disabled. Switching environments
                cannot send a live order.
              </div>
              <button className="secondary" disabled>
                Live execution disabled
              </button>
            </>
          )}
        </section>
      </div>
      <section className="panel account-panel">
        <div className="panel-head">
          <div>
            <h2>
              {mode === "paper" ? "Paper portfolio" : "Angel One account"}
            </h2>
            <p>
              {mode === "paper"
                ? "Isolated simulated ledger · INR"
                : "Read-only broker data · refreshed every 30 seconds"}
            </p>
          </div>
          <div className="segments">
            {(mode === "paper"
              ? ["positions", "orders"]
              : ["positions", "holdings", "orders", "funds"]
            ).map((t) => (
              <button
                key={t}
                className={accountTab === t ? "selected" : ""}
                onClick={() => setAccountTab(t)}
              >
                {t}
              </button>
            ))}
          </div>
        </div>
        {mode === "paper" ? (
          <>
            <div className="paper-stats">
              <span>
                Cash <b>₹{number(paper?.cash)}</b>
              </span>
              <span>
                Marked equity <b>₹{number(paper?.equity)}</b>
              </span>
              <span>
                Realized P&L <b>₹{number(paper?.realized)}</b>
              </span>
            </div>
            {accountTab === "orders" ? (
              <Grid
                rows={orders}
                columns={[
                  ["symbol", "Instrument"],
                  ["side", "Side"],
                  ["quantity", "Qty"],
                  ["price", "Fill price"],
                  ["realized", "Realized P&L"],
                  ["status", "Status"],
                ]}
                empty="No simulated orders yet."
              />
            ) : (
              <Grid
                rows={positions}
                columns={[
                  ["symbol", "Instrument"],
                  ["quantity", "Qty"],
                  ["average_price", "Avg price"],
                  ["price", "Last received"],
                  ["unrealized", "Unrealized P&L"],
                ]}
                empty="Your paper portfolio is empty."
              />
            )}
            <p className="chart-help">
              Valuations use last received prices and can be stale. This is a
              simulation, not a backtest or a broker balance.
            </p>
          </>
        ) : !state?.authenticated ? (
          <div className="empty">
            Connect your account to view real broker records.
          </div>
        ) : accountTab === "funds" ? (
          <div className="funds-grid">
            {Object.entries(account?.data || {}).map(([k, v]) => (
              <div className="metric" key={k}>
                <span>{k.replaceAll("_", " ")}</span>
                <strong>{number(Number(v))}</strong>
              </div>
            ))}
          </div>
        ) : (
          <Grid
            rows={liveRows}
            columns={
              accountTab === "orders"
                ? [
                    ["tradingsymbol", "Instrument"],
                    ["transactiontype", "Side"],
                    ["quantity", "Qty"],
                    ["averageprice", "Fill price"],
                    ["orderstatus", "Status"],
                  ]
                : [
                    ["tradingsymbol", "Instrument"],
                    [accountTab === "positions" ? "netqty" : "quantity", "Qty"],
                    ["averageprice", "Avg price"],
                    ["ltp", "LTP"],
                    ["pnl", "P&L"],
                  ]
            }
            empty="No broker records returned for this view."
          />
        )}
        {account?.as_of && mode === "live" && (
          <p className="chart-help">
            Retrieved {new Date(account.as_of * 1000).toLocaleString()}
          </p>
        )}
      </section>
    </div>
  );
}
