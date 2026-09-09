"use client";
import { useEffect, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { number, tone, readable, chartBars } from "../lib/research.mjs";

const icon = {
  Overview: "◈",
  Agents: "◎",
  Signals: "↗",
  History: "◷",
  Settings: "⚙",
};
async function api(path, options) {
  const response = await fetch(path, {
    ...options,
    cache: "no-store",
    headers: { Accept: "application/json", ...options?.headers },
  });
  const value = response.headers
    .get("content-type")
    ?.includes("application/json")
    ? await response.json()
    : {};
  if (value.redirect && !response.ok) {
    window.location.assign(value.redirect);
    throw new Error(value.error || "Redirecting…");
  }
  if (!response.ok)
    throw new Error(value.error || "Request failed. Reload and try again.");
  return value;
}
function Report({ content }) {
  const value = readable(content);
  if (value && typeof value === "object")
    return (
      <dl className="structured">
        {Object.entries(value).map(([key, v]) => (
          <div key={key}>
            <dt>{key.replaceAll("_", " ")}</dt>
            <dd>
              <Report content={v} />
            </dd>
          </div>
        ))}
      </dl>
    );
  return (
    <Markdown
      remarkPlugins={[remarkGfm]}
      skipHtml
      components={{
        img: () => null,
        a: ({ children, href }) => (
          <a href={href} target="_blank" rel="noopener noreferrer">
            {children}
          </a>
        ),
      }}
    >
      {String(value ?? "Not provided")}
    </Markdown>
  );
}
function Badge({ children, kind = "" }) {
  return <span className={"badge " + kind}>{children}</span>;
}
function Metric({ label, value, sub, kind = "" }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong className={kind}>{value}</strong>
      <small>{sub}</small>
    </div>
  );
}
function Chart({ snapshot }) {
  const [limit, setLimit] = useState(60),
    [candles, setCandles] = useState(false),
    [hover, setHover] = useState(null);
  const bars = chartBars(snapshot, limit),
    selected = bars[hover] || bars.at(-1);
  if (!bars.length)
    return (
      <div className="empty">
        Price chart will appear after market data is retrieved.
      </div>
    );
  const hasOHLC = bars.every((b) =>
    [b.open, b.high, b.low].every(Number.isFinite),
  );
  const vals = bars.flatMap((b) =>
    [b.close, b.high, b.low, b.sma20, b.sma50].filter(Number.isFinite),
  );
  const low = Math.min(...vals),
    high = Math.max(...vals),
    span = high - low || 1;
  const x = (i) => 55 + (i * 820) / Math.max(1, bars.length - 1),
    y = (v) => 235 - ((v - low) / span) * 185;
  const points = (key) =>
    bars
      .map((b, i) => (Number.isFinite(b[key]) ? `${x(i)},${y(b[key])}` : null))
      .filter(Boolean)
      .join(" ");
  const volume = Math.max(...bars.map((b) => b.volume || 0), 1);
  return (
    <>
      <div className="panel-head">
        <div>
          <h2>Price & trend</h2>
          <p>Adjusted daily · INR · through {snapshot.latest_bar_date}</p>
        </div>
        <div className="segments">
          {[20, 60, 140].map((n) => (
            <button
              key={n}
              className={limit === n ? "selected" : ""}
              onClick={() => {
                setLimit(n);
                setHover(null);
              }}
            >
              {n === 140 ? "All" : n + " bars"}
            </button>
          ))}
          <button
            disabled={!hasOHLC}
            className={candles ? "selected" : ""}
            onClick={() => setCandles(!candles)}
          >
            {candles ? "Candles" : "Line"}
          </button>
        </div>
      </div>
      <div className="chart-readout">
        <b>{selected?.date}</b>
        <span>Close ₹{number(selected?.close)}</span>
        {hasOHLC && (
          <>
            <span>O {number(selected?.open)}</span>
            <span>H {number(selected?.high)}</span>
            <span>L {number(selected?.low)}</span>
          </>
        )}
        <span>Vol {number(selected?.volume, 0)}</span>
      </div>
      <svg
        className="price-chart"
        viewBox="0 0 940 330"
        role="img"
        aria-label="Adjusted daily price, moving averages, and volume"
        onMouseLeave={() => setHover(null)}
      >
        {[0, 1, 2, 3, 4].map((i) => (
          <g key={i}>
            <line
              x1="55"
              x2="875"
              y1={50 + (i * 185) / 4}
              y2={50 + (i * 185) / 4}
              className="gridline"
            />
            <text x="886" y={55 + (i * 185) / 4}>
              {number(high - (i * span) / 4, 0)}
            </text>
          </g>
        ))}
        {candles && hasOHLC ? (
          bars.map((b, i) => (
            <g
              key={b.date}
              className={b.close >= b.open ? "candle-up" : "candle-down"}
            >
              <line x1={x(i)} x2={x(i)} y1={y(b.high)} y2={y(b.low)} />
              <rect
                x={x(i) - Math.max(1, 240 / bars.length)}
                y={Math.min(y(b.open), y(b.close))}
                width={Math.max(2, 480 / bars.length)}
                height={Math.max(1, Math.abs(y(b.open) - y(b.close)))}
              />
            </g>
          ))
        ) : (
          <polyline points={points("close")} className="close-line" />
        )}
        <polyline points={points("sma20")} className="sma20-line" />
        <polyline points={points("sma50")} className="sma50-line" />
        {bars.map((b, i) => (
          <g key={b.date}>
            <rect
              className="volume"
              x={x(i) - 2}
              y={292 - ((b.volume || 0) / volume) * 35}
              width={Math.max(2, 600 / bars.length)}
              height={((b.volume || 0) / volume) * 35}
            />
            <rect
              fill="transparent"
              x={x(i) - 410 / Math.max(1, bars.length - 1)}
              y="35"
              width={820 / Math.max(1, bars.length - 1)}
              height="260"
              onMouseEnter={() => setHover(i)}
            >
              <title>
                {b.date}: ₹{number(b.close)}
              </title>
            </rect>
          </g>
        ))}
        {hover !== null && bars[hover] && (
          <line
            className="crosshair"
            x1={x(hover)}
            x2={x(hover)}
            y1="35"
            y2="295"
          />
        )}
        <text x="55" y="320">
          {bars[0]?.date}
        </text>
        <text x="795" y="320">
          {bars.at(-1)?.date}
        </text>
      </svg>
      <div className="legend">
        <span className="positive">● Close</span>
        <span className="blue">● SMA 20</span>
        <span className="gold">● SMA 50</span>
        <span>▥ Volume</span>
      </div>
      {!snapshot.bars && (
        <p className="muted">
          This older report saved 20 closing prices only. New analyses include
          OHLC, moving averages and volume history.
        </p>
      )}
      <details>
        <summary>View chart data</summary>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Close (INR)</th>
                <th>SMA20</th>
                <th>SMA50</th>
                <th>Volume</th>
              </tr>
            </thead>
            <tbody>
              {bars.map((b) => (
                <tr key={b.date}>
                  <td>{b.date}</td>
                  <td>{number(b.close)}</td>
                  <td>{number(b.sma20)}</td>
                  <td>{number(b.sma50)}</td>
                  <td>{number(b.volume, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}
function ResearchForm({ data, onRun, busy }) {
  return (
    <form className="research-form" onSubmit={onRun}>
      <label>
        Indian equity
        <input
          name="symbol"
          placeholder="RELIANCE.NS"
          defaultValue="RELIANCE.NS"
          required
          maxLength={33}
        />
      </label>
      <label>
        Research date
        <input
          type="date"
          name="date"
          defaultValue={data.today}
          min="2000-01-01"
          max={data.today}
          required
        />
      </label>
      <label>
        Analysis mode
        <select name="mode" defaultValue={data.ready ? "ai" : "snapshot"}>
          <option value="ai" disabled={!data.ready}>
            Multi-agent AI research
          </option>
          <option value="snapshot">Market snapshot</option>
        </select>
      </label>
      <button
        className="primary"
        disabled={
          busy ||
          data.jobs.some((j) => ["running", "queued"].includes(j.status))
        }
      >
        ↗ Run analysis
      </button>
      <p>NSE: .NS · BSE: .BO · One active analysis · Up to 20 minutes</p>
    </form>
  );
}
function AgentPanel({ view, status }) {
  const [selected, setSelected] = useState("market_report");
  const agent = view.agents.find((a) => a.id === selected) || view.agents[0];
  return (
    <div className="agent-layout">
      <div className="agent-list">
        {view.agents.map((a, i) => (
          <button
            key={a.id}
            onClick={() => setSelected(a.id)}
            className={selected === a.id ? "active" : ""}
          >
            <span className={"agent-dot " + a.status}>
              {a.status === "complete" ? "✓" : String(i + 1).padStart(2, "0")}
            </span>
            <span>
              <b>{a.name}</b>
              <small>
                {a.stage} · {a.status}
              </small>
            </span>
          </button>
        ))}
      </div>
      <article className="agent-report">
        <div className="panel-head">
          <div>
            <span className="eyebrow">{agent.stage}</span>
            <h2>{agent.name}</h2>
          </div>
          <Badge kind={agent.status === "complete" ? "positive" : ""}>
            {agent.status}
          </Badge>
        </div>
        {agent.updated && (
          <p className="muted">
            Output updated {new Date(agent.updated * 1000).toLocaleString()}
          </p>
        )}
        {agent.content ? (
          <div className="prose">
            <Report content={agent.content} />
          </div>
        ) : (
          <div className="empty">
            {status === "running"
              ? "Waiting for this agent’s output. Completed responses appear automatically."
              : "No output was saved for this agent in this analysis."}
          </div>
        )}
      </article>
    </div>
  );
}
function Signals({ view }) {
  return (
    <div className="signal-grid">
      <section className="panel">
        <span className="eyebrow">Portfolio manager assessment</span>
        <h2 className={"signal " + tone(view.signal)}>{view.signal}</h2>
        <p>
          The final research rating uses five tiers: Buy, Overweight, Hold,
          Underweight, Sell.
        </p>
        <div className="rating-scale">
          {["Sell", "Underweight", "Hold", "Overweight", "Buy"].map((s) => (
            <div
              key={s}
              className={view.signal === s ? "rating-active " + tone(s) : ""}
            >
              {s}
            </div>
          ))}
        </div>
        <p className="muted">
          This is a research assessment, not a live order. No brokerage account
          is connected.
        </p>
      </section>
      <section className="panel">
        <span className="eyebrow">Transparent technical score</span>
        <h2 className="signal">
          {view.technical.score ?? "—"}
          <small> / 100</small>
        </h2>
        <ul className="checks">
          {view.technical.checks.map((c) => (
            <li key={c.label}>
              <span className={c.passed === true ? "positive" : ""}>
                {c.passed === null ? "—" : c.passed ? "✓" : "○"}
              </span>
              {c.label}
            </li>
          ))}
        </ul>
        <p className="muted">{view.technical.description}</p>
      </section>
      {["trader_investment_plan", "final_trade_decision"].map((id) => (
        <section className="panel" key={id}>
          <h2>
            {id === "trader_investment_plan"
              ? "Trade proposal & price levels"
              : "Final decision & risk assessment"}
          </h2>
          <div className="prose">
            <Report
              content={
                view.agents.find((a) => a.id === id)?.content ||
                "No proposal available. Run a full AI analysis to produce this report."
              }
            />
          </div>
        </section>
      ))}
    </div>
  );
}
function Settings({ data, submit, busy }) {
  const [provider, setProvider] = useState(data.settings.provider);
  return (
    <div className="settings-grid">
      <section className="panel">
        <h2>Research models</h2>
        <p>Choose the model provider used for new analyses.</p>
        <form onSubmit={(e) => submit(e, "/settings")}>
          <label>
            Provider
            <select
              name="provider"
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
            >
              {Object.entries(data.providers).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          {provider === "codex_cli" ? (
            <p className="callout">
              Codex CLI · GPT-6 Astra
              <br />
              Uses the server’s saved ChatGPT sign-in and available Codex
              allowance.
            </p>
          ) : (
            <>
              <label>
                Quick model
                <input
                  name="quick_model"
                  defaultValue={data.settings.quick_model}
                  required
                />
              </label>
              <label>
                Deep model
                <input
                  name="deep_model"
                  defaultValue={data.settings.deep_model}
                  required
                />
              </label>
              <label>
                API key
                <input
                  name="api_key"
                  type="password"
                  autoComplete="new-password"
                  placeholder="Leave blank to keep saved key"
                />
              </label>
              <label className="checkbox">
                <input type="checkbox" name="clear_key" value="yes" /> Remove
                saved API key
              </label>
            </>
          )}
          <button className="primary" disabled={busy}>
            Save models
          </button>
        </form>
      </section>
      <section className="panel">
        <div className="panel-head">
          <h2>Telegram channel</h2>
          <Badge kind={data.telegram.enabled ? "positive" : ""}>
            {data.telegram.enabled ? "Enabled" : "Disabled"}
          </Badge>
        </div>
        <p>
          Send a signal summary and report link after each completed analysis.
          Add your bot to the channel as an administrator with permission to
          post.
        </p>
        <form onSubmit={(e) => submit(e, "/api/telegram")}>
          <label>
            Bot token
            <input
              name="token"
              type="password"
              autoComplete="new-password"
              placeholder={
                data.telegram.connected
                  ? "Token saved · leave blank to keep"
                  : "Paste your BotFather token"
              }
            />
          </label>
          <label>
            Channel username or chat ID
            <input
              name="channel"
              defaultValue={data.telegram.channel}
              placeholder="@your_channel or -100…"
            />
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              name="enabled"
              value="yes"
              defaultChecked={data.telegram.enabled}
            />{" "}
            Send completed analysis notifications
          </label>
          <label className="checkbox">
            <input type="checkbox" name="clear" value="yes" /> Remove saved bot
            token
          </label>
          <button className="primary" disabled={busy}>
            Save Telegram
          </button>
        </form>
        <form onSubmit={(e) => submit(e, "/api/telegram")}>
          <input type="hidden" name="action" value="test" />
          <button
            className="secondary"
            disabled={busy || !data.telegram.connected}
          >
            Send test message
          </button>
        </form>
        <p className="muted">
          Use your channel’s username, not the bot username. Tokens remain on
          the server. Save changes before sending a test. Delivery status
          appears on each analysis.
        </p>
      </section>
      <section className="panel">
        <h2>Account security</h2>
        <p>Your existing account and research history are preserved.</p>
        <a className="button secondary" href="/password">
          Change password
        </a>
      </section>
    </div>
  );
}
function Account({ path, csrf, setCsrf }) {
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body = new FormData(e.currentTarget);
      body.set("csrf", csrf);
      const response = await api(path, { method: "POST", body });
      window.location.assign(response.redirect || "/");
    } catch (err) {
      setError(err.message);
      const session = await api("/api/session");
      setCsrf(session.csrf);
    } finally {
      setBusy(false);
    }
  }
  const password = path === "/password";
  return (
    <main className="account">
      <div className="brand">
        <span className="brand-mark">A</span> ARKBYTE <small>RESEARCH</small>
      </div>
      <section className="panel">
        <span className="eyebrow">Private research terminal</span>
        <h1>{password ? "Update your password" : "Welcome back."}</h1>
        <p>
          {password
            ? "Use a new password of at least 14 characters."
            : "Sign in to your multi-agent equity workspace."}
        </p>
        {error && (
          <div role="alert" className="error">
            {error}
          </div>
        )}
        <form onSubmit={submit}>
          {password ? (
            <>
              <label>
                Current password
                <input
                  name="current"
                  type="password"
                  autoComplete="current-password"
                  required
                />
              </label>
              <label>
                New password
                <input
                  name="password"
                  type="password"
                  minLength={14}
                  maxLength={256}
                  autoComplete="new-password"
                  required
                />
              </label>
              <label>
                Confirm new password
                <input
                  name="confirm"
                  type="password"
                  minLength={14}
                  autoComplete="new-password"
                  required
                />
              </label>
            </>
          ) : (
            <>
              <label>
                Username
                <input name="username" autoComplete="username" required />
              </label>
              <label>
                Password
                <input
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  required
                />
              </label>
            </>
          )}
          <button className="primary" disabled={busy || !csrf}>
            {busy ? "Please wait…" : password ? "Update password" : "Sign in →"}
          </button>
        </form>
      </section>
      <p className="muted">Private access · Secure session · Research only</p>
    </main>
  );
}
export default function Dashboard() {
  const [data, setData] = useState(null),
    [job, setJob] = useState(null),
    [jobId, setJobId] = useState(""),
    [tab, setTab] = useState("Overview"),
    [path, setPath] = useState(""),
    [csrf, setCsrf] = useState(""),
    [error, setError] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false),
    [search, setSearch] = useState("");
  useEffect(() => {
    setPath(window.location.pathname);
    setJobId(new URLSearchParams(window.location.search).get("job") || "");
    if (window.location.pathname === "/settings") setTab("Settings");
    api("/api/session")
      .then((v) => setCsrf(v.csrf))
      .catch((e) => setError(e.message));
  }, []);
  const account = ["/login", "/password"].includes(path);
  useEffect(() => {
    if (!path || account) return;
    let alive = true;
    async function load() {
      try {
        const v = await api("/api/dashboard");
        if (alive) {
          setData(v);
          setCsrf(v.csrf);
          setJobId((old) => old || v.jobs[0]?.id || "");
        }
      } catch (e) {
        if (alive) setError(e.message);
      }
    }
    load();
    const timer = setInterval(load, 8000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [path, account]);
  useEffect(() => {
    if (!jobId || account) return;
    let alive = true;
    setJob(null);
    async function load() {
      try {
        const v = await api("/api/jobs/" + encodeURIComponent(jobId));
        if (alive) setJob(v);
      } catch (e) {
        if (alive) setError(e.message);
      }
    }
    load();
    const timer = setInterval(load, 5000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [jobId, account]);
  function select(id) {
    setJobId(id);
    setTab("Overview");
    window.history.replaceState(null, "", "/?job=" + encodeURIComponent(id));
  }
  async function submit(e, url) {
    e.preventDefault();
    const form = e.currentTarget;
    setError("");
    setMessage("");
    setBusy(true);
    try {
      const body = new FormData(form);
      body.set("csrf", csrf);
      const v = await api(url, { method: "POST", body });
      if (v.job_id) select(v.job_id);
      setMessage(v.message || "Saved.");
      setData(await api("/api/dashboard"));
      for (const input of form.querySelectorAll("input[type=password]"))
        input.value = "";
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  if (account) return <Account path={path} csrf={csrf} setCsrf={setCsrf} />;
  if (!data)
    return (
      <main className="loading">
        <div className="brand-mark">A</div>
        <h1>Opening research terminal…</h1>
        {error && (
          <p role="alert">
            {error} <a href="/login">Sign in</a>
          </p>
        )}
      </main>
    );
  const view = job?.view,
    snapshot = view?.snapshot || {},
    active = data.jobs.find((j) => ["running", "queued"].includes(j.status));
  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="/">
          <span className="brand-mark">A</span>
          <span>
            ARKBYTE<small>RESEARCH TERMINAL</small>
          </span>
        </a>
        <div className="workspace">
          PRIVATE WORKSPACE<span>Indian equities</span>
        </div>
        <nav>
          {Object.keys(icon).map((name) => (
            <button
              key={name}
              className={tab === name ? "active" : ""}
              onClick={() => setTab(name)}
            >
              <span>{icon[name]}</span>
              {name}
              {name === "Agents" && view && (
                <small>{view.completion.completed}/12</small>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <Badge kind={data.ready ? "positive" : ""}>
            {data.ready ? "● Engine configured" : "○ Setup required"}
          </Badge>
          <p>
            {data.settings.provider === "codex_cli"
              ? "Codex · GPT-6 Astra"
              : data.settings.deep_model}
          </p>
          <span className="muted">Research mode · Orders disabled</span>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              const body = new FormData();
              body.set("csrf", csrf);
              await api("/logout", { method: "POST", body });
              window.location.assign("/login");
            }}
          >
            <button className="logout">Sign out ↗</button>
          </form>
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <span>
            Workspace <span className="muted">/ {tab}</span>
          </span>
          <div>
            <Badge>INR · NSE / BSE</Badge>
            <span className="avatar">W</span>
          </div>
        </header>
        <div className="content">
          <div className="page-heading">
            <div>
              <span className="eyebrow">MULTI-AGENT INTELLIGENCE</span>
              <h1>
                {tab === "Overview"
                  ? "A clearer view of your next move."
                  : tab === "Agents"
                    ? "Inside the research team."
                    : tab === "Signals"
                      ? "From evidence to assessment."
                      : tab === "History"
                        ? "Your research, preserved."
                        : "Your workspace, connected."}
              </h1>
              <p>
                {tab === "Overview"
                  ? "Market context, independent perspectives, one research workspace."
                  : tab === "Agents"
                    ? "Explore each analyst, the opposing arguments, and the final risk review."
                    : tab === "Signals"
                      ? "Inspect the proposal and the evidence behind the final rating."
                      : tab === "History"
                        ? "Reopen previous analyses, compare dates, and download reports."
                        : "Manage models, channel notifications, and account security."}
              </p>
            </div>
            <Badge kind="positive">● Private terminal</Badge>
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
              <button onClick={() => setMessage("")}>Dismiss</button>
            </div>
          )}
          {active && (
            <button
              className="running-banner"
              onClick={() => select(active.id)}
            >
              ◌ {active.symbol} · {active.status} — open live agent progress →
            </button>
          )}
          {tab === "Settings" ? (
            <Settings data={data} submit={submit} busy={busy} />
          ) : tab === "History" ? (
            <section className="panel">
              <div className="panel-head">
                <h2>
                  Analysis history{" "}
                  <span className="muted">({data.jobs.length})</span>
                </h2>
                <input
                  aria-label="Filter history"
                  placeholder="Filter by symbol or date"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Instrument</th>
                      <th>Research date</th>
                      <th>Mode</th>
                      <th>Status</th>
                      <th>Report</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.jobs
                      .filter((j) =>
                        (j.symbol + j.day)
                          .toLowerCase()
                          .includes(search.toLowerCase()),
                      )
                      .map((j) => (
                        <tr key={j.id}>
                          <td>
                            <b>{j.symbol}</b>
                          </td>
                          <td>{j.day}</td>
                          <td>
                            {j.mode === "ai" ? "Multi-agent AI" : "Snapshot"}
                          </td>
                          <td>
                            <Badge
                              kind={
                                j.status === "complete"
                                  ? "positive"
                                  : j.status === "failed"
                                    ? "negative"
                                    : ""
                              }
                            >
                              {j.status}
                            </Badge>
                          </td>
                          <td>
                            <button
                              className="text-button"
                              onClick={() => select(j.id)}
                            >
                              Open →
                            </button>
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
              {!data.jobs.length && (
                <div className="empty">
                  Run your first analysis from Overview.
                </div>
              )}
            </section>
          ) : (
            <>
              {tab === "Overview" && (
                <section className="panel new-analysis">
                  <div className="panel-head">
                    <h2>New research</h2>
                    <Badge>On demand</Badge>
                  </div>
                  <ResearchForm
                    data={data}
                    onRun={(e) => submit(e, "/jobs")}
                    busy={busy}
                  />
                </section>
              )}
              {job && (
                <div className="instrument">
                  <div>
                    <h2>
                      {job.symbol}{" "}
                      <Badge
                        kind={
                          job.status === "complete"
                            ? "positive"
                            : job.status === "failed"
                              ? "negative"
                              : ""
                        }
                      >
                        {job.status}
                      </Badge>
                    </h2>
                    <p>
                      Research date {job.day} ·{" "}
                      {job.mode === "ai"
                        ? "Multi-agent research"
                        : "Market snapshot"}{" "}
                      · Saved {new Date(job.created * 1000).toLocaleString()}
                    </p>
                  </div>
                  <div className="actions">
                    {job.status === "complete" && (
                      <a
                        className="button secondary"
                        href={"/jobs/" + job.id + "/download"}
                      >
                        ↓ Export JSON
                      </a>
                    )}
                    <button
                      className="secondary"
                      onClick={() => window.print()}
                    >
                      Print report
                    </button>
                  </div>
                </div>
              )}
              {job?.error && (
                <div className="error" role="alert">
                  {job.error} Completed outputs below are retained.
                </div>
              )}
              {view ? (
                tab === "Agents" ? (
                  <AgentPanel view={view} status={job.status} />
                ) : tab === "Signals" ? (
                  <Signals view={view} />
                ) : (
                  <>
                    <div className="metrics">
                      <Metric
                        label="Adjusted close"
                        value={"₹" + number(snapshot.close)}
                        sub={
                          snapshot.latest_bar_date
                            ? "Bar date " + snapshot.latest_bar_date
                            : "Awaiting market data"
                        }
                      />
                      <Metric
                        label="Daily change"
                        value={number(snapshot.daily_change_percent) + "%"}
                        kind={
                          snapshot.daily_change_percent >= 0
                            ? "positive"
                            : "negative"
                        }
                        sub="Versus previous trading close"
                      />
                      <Metric
                        label="AI assessment"
                        value={view.signal}
                        kind={tone(view.signal)}
                        sub="Portfolio manager’s final rating"
                      />
                      <Metric
                        label="Agent outputs"
                        value={
                          view.completion.completed +
                          " / " +
                          view.completion.total
                        }
                        sub="Saved responses · not a confidence score"
                      />
                    </div>
                    <div className="overview-grid">
                      <section className="panel chart-panel">
                        <Chart snapshot={snapshot} />
                      </section>
                      <section className="panel indicators">
                        <div className="panel-head">
                          <h2>Market pulse</h2>
                          <Badge>Daily</Badge>
                        </div>
                        <Metric
                          label="RSI · 14 periods"
                          value={number(snapshot.rsi_14)}
                          sub={
                            snapshot.rsi_14 == null
                              ? "Unavailable"
                              : snapshot.rsi_14 > 70
                                ? "Above 70 · overbought range"
                                : snapshot.rsi_14 < 30
                                  ? "Below 30 · oversold range"
                                  : "Between 30–70"
                          }
                        />
                        <progress
                          max="100"
                          value={snapshot.rsi_14 ?? 0}
                          aria-label="RSI value"
                        />
                        <div className="mini-metrics">
                          <Metric
                            label="SMA 20"
                            value={"₹" + number(snapshot.sma_20)}
                          />
                          <Metric
                            label="SMA 50"
                            value={"₹" + number(snapshot.sma_50)}
                          />
                          <Metric
                            label="Daily volume"
                            value={number(snapshot.volume, 0)}
                          />
                          <Metric
                            label="Technical checklist"
                            value={
                              view.technical.score == null
                                ? "—"
                                : view.technical.score + "/100"
                            }
                            sub="Rule-based, not AI confidence"
                          />
                        </div>
                        <button
                          className="text-button"
                          onClick={() => setTab("Signals")}
                        >
                          Inspect score & decision →
                        </button>
                      </section>
                    </div>
                    <section className="panel">
                      <div className="panel-head">
                        <div>
                          <h2>Research workflow</h2>
                          <p>
                            {job.status === "running"
                              ? "Outputs update every 5 seconds as agents finish."
                              : "Select Agents to inspect every saved response."}
                          </p>
                        </div>
                        <button
                          className="text-button"
                          onClick={() => setTab("Agents")}
                        >
                          Explore agents →
                        </button>
                      </div>
                      <div className="workflow">
                        {[
                          "Analysis",
                          "Research debate",
                          "Trade proposal",
                          "Risk debate",
                          "Final decision",
                        ].map((stage, i) => {
                          const agents = view.agents.filter(
                            (a) => a.stage === stage,
                          );
                          const done = agents.filter((a) => a.content).length;
                          return (
                            <button
                              key={stage}
                              onClick={() => setTab("Agents")}
                            >
                              <span
                                className={
                                  done === agents.length
                                    ? "step complete"
                                    : "step"
                                }
                              >
                                {done === agents.length ? "✓" : i + 1}
                              </span>
                              <b>{stage}</b>
                              <small>
                                {done}/{agents.length} outputs
                              </small>
                            </button>
                          );
                        })}
                      </div>
                    </section>
                    {job.notification && (
                      <p className="callout">
                        Telegram delivery: {job.notification.status}
                      </p>
                    )}
                    <section className="panel">
                      <div className="panel-head">
                        <h2>Latest decision</h2>
                        <Badge kind={tone(view.signal)}>{view.signal}</Badge>
                      </div>
                      <div className="prose decision-preview">
                        <Report
                          content={
                            view.agents.find(
                              (a) => a.id === "final_trade_decision",
                            )?.content ||
                            "Run multi-agent AI research to generate analyst reports, a trade proposal, and a final assessment."
                          }
                        />
                      </div>
                    </section>
                  </>
                )
              ) : (
                <div className="empty">
                  {jobId
                    ? "Loading analysis…"
                    : "Your research workspace is ready. Start an analysis above."}
                </div>
              )}
            </>
          )}
          <footer>
            Yahoo Finance · Adjusted daily data may be delayed. Historical
            research is not a validated backtest. AI assessments are not
            guaranteed outcomes.
            <br />
            Automatic trading is disabled. No orders are placed by this
            dashboard.
          </footer>
        </div>
      </main>
    </div>
  );
}
