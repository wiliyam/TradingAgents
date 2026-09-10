# Next.js dashboard and private Python API

Deployment: **https://at.arkbytetech.com** on the existing Oracle ARM VM.
The Next.js interface in `frontend/` uses this authenticated Python API and the
upstream TradingAgents engine, with a keyless Yahoo Finance snapshot mode.
The previous Jinja dashboard and its assets have been removed.

## Use

1. Open the HTTPS site and sign in with the credentials in the local, Git-ignored
   `.private/access.txt` file. Replace the temporary password when prompted.
2. Run a **market snapshot** using an NSE `.NS` or BSE `.BO` symbol.
3. **Multi-agent AI research** now defaults to **Codex CLI / GPT-6 Astra**, using
   the server's saved ChatGPT sign-in and your Codex allowance. No API key is
   needed for this provider. API-based providers remain available in Settings;
   they require their own key and valid model IDs.
4. Explore Overview, Agents, Signals and History for interactive charts, readable
   reports, per-agent outputs and JSON export. New runs include OHLC, moving
   averages and volume history. Older reports retain their saved closing prices.
5. In Settings, enter a Telegram bot token and @channel username or numeric chat
   ID. Add the bot as a channel administrator with posting permission. Save,
   then use **Send test message**. Enable notifications to post each completed
   analysis summary. Tokens are never returned by the API.

The Markets tab integrates Angel One market data and read-only live account views.
Paper orders use an isolated simulated ledger; live order placement is disabled. There is one
active analysis at a time, a 20-minute job timeout, and a limit of 24 analyses per
rolling day. The AI graph uses one debate round and bounded output/retries.
Historical dates are research dates, not a guarantee of point-in-time data or a
validated backtest. Daily prices may be delayed and fundamentals/news incomplete.

## Frontend build

```sh
cd frontend
npm ci
npm run build
```

Copy `frontend/out/` to `/opt/tradingagents/dashboard/web/` and restart the web
service so CSP hashes match the new build. See `frontend/README.md` for browser
tests. All pages, including login and password changes, are rendered by Next.js.
The Flask service serves the build and authenticated API, not Python templates.

## Server layout

| Item | Location |
| --- | --- |
| Application + Python environment | `/opt/tradingagents` / `.venv` |
| Private state, credentials, API settings, queue | `/var/lib/tradingagents/dashboard` |
| Upstream research cache and memory | `/var/lib/tradingagents/.tradingagents` |
| Web service (loopback port 8050) | `tradingagents-web.service` |
| Serial job worker | `tradingagents-worker.service` |
| HTTPS proxy | `/etc/nginx/sites-available/tradingagents` |
| Certificate | `/etc/letsencrypt/live/at.arkbytetech.com` |
| Automatic renewal | `certbot.timer`, with nginx reload deployment hook |
| Isolated Codex executable | `/opt/codex/bin/codex` (0.153.4) |
| Private Codex sign-in | `/var/lib/tradingagents/.codex/auth.json` |

The unprivileged `tradingagents` account cannot write application code or access
the Ubuntu user's home. State is permissioned 700; the auth file and SQLite DB
are 600. Settings keys remain in the private SQLite database, never returned to
the browser. Back up this directory securely: it contains credentials. The
application uses secure cookies, password hashes, CSRF tokens, login throttling,
strict HTML escaping, host validation and a same-origin content security policy.

The Codex adapter preserves TradingAgents' analyst graph, research-tool calls
and structured decisions. Each model response uses `codex exec` with stdin,
an output schema, a temporary working directory and a sanitized environment.
CLI shell, browser, app, memory, hook and collaboration tools are disabled;
the CLI uses a read-only sandbox. It returns tool requests as JSON, validated
against the registered functions before the existing Python ToolNodes execute
them. Provider/CLI errors shown to the dashboard omit raw process output.
Each CLI call has a three-minute timeout; the full job retains its 20-minute
timeout and 60-call cap. Codex quota and model availability still apply.

The Ubuntu user's OpenClaw Codex CLI was also upgraded to 0.153.4. Its sign-in was
seeded privately into the isolated service account for this user-authorized
integration. The dashboard can refresh its own copy in place. If reauthentication
is required, use the official device-auth flow under the service account:

```sh
sudo -u tradingagents env HOME=/var/lib/tradingagents \
  CODEX_HOME=/var/lib/tradingagents/.codex \
  /opt/codex/bin/codex login --device-auth
```

Never put ChatGPT tokens in the dashboard's API-key field or commit the Codex
auth file. No automatic brokerage execution is enabled.

The cloud firewall retains existing SSH rules and adds the current administrator
IP. Only ports 80 and 443 were opened for this deployment. The Oracle image has
an iptables reject rule ahead of UFW; an explicit 80/443 accept rule was therefore
added and persisted in `/etc/iptables/rules.v4`, with its previous file backed up
as `/etc/iptables/rules.v4.pre-tradingagents`. No firewall was flushed.

## Operations

```sh
sudo systemctl status tradingagents-web tradingagents-worker
sudo journalctl -u tradingagents-web -u tradingagents-worker --since '1 hour ago'
sudo nginx -t
sudo certbot renew --dry-run
```

Stop the worker before updating code; a restarted worker marks interrupted jobs
as failed so they can be submitted again. Keep `/var/lib/tradingagents` when
updating source. Use `pip check` after dependency changes. The server's installed
package versions are recorded in `deployed-requirements.txt`.

## Validation

```sh
python -m pytest dashboard -q --cov=dashboard.app --cov=dashboard.store --cov=dashboard.worker
ruff check dashboard
```

Deployment checks include actual HTTPS access, HTTP-to-HTTPS redirect, private
route redirects, login and password rotation, secure cookie attributes, a real
RELIANCE.NS snapshot through the queue, and continued OpenClaw service health.
The tests exercise authorization, CSRF, limits, job lifecycle, escaped reports,
API-key redaction, market-data boundaries, secret-free error handling, process
timeout cleanup and Codex tool-call/structured-output integration. A browser
favicon regression test ensures background requests cannot invalidate the
login form's CSRF token.

On 2026-09-08, the full live RELIANCE.NS analysis completed through the Codex
CLI / GPT-6 Astra integration in approximately nine minutes. It saved all four
analyst reports, the investment/trader plans and the final decision. An earlier
run had stopped at the account's Codex usage limit; the successful retry used
the same selected model after the allowance became available. The integration
and login regression suite passes 39 tests. These checks validate operation,
not financial accuracy or profitability.

## Progress, scoring and notifications

SQLite migrations add progress, integrations and delivery-status tables without
replacing existing jobs, settings or authentication. Each new AI run saves all
12 agent outputs as they complete. Failures retain those partial outputs.
The 0–100 technical checklist awards one of three equal points for price above
SMA20, price above SMA50, and RSI14 between 50 and 70. Missing inputs produce no
score. This is not AI confidence, a success probability or a trading strategy.

Telegram uses a bounded HTTPS request after successful research. Delivery failure
never invalidates the research result. Delivery is not automatically retried, as
a transport timeout may mean the message was already delivered. Test messages
are limited to three per 15 minutes. Telegram is disabled until configured.

`python -m dashboard.backfill --state /var/lib/tradingagents/dashboard --logs
/var/lib/tradingagents/.tradingagents/logs` can restore missing historical debate
outputs only when the stored symbol, date and all analyst/final reports match.
Back up SQLite before running migrations or backfills.

## Next.js deployment verification (2026-09-09)

The exported Next.js dashboard is live. The legacy Python templates and assets
were removed after browser verification. The API suite passes 51 tests; frontend
utility tests and the desktop/mobile Playwright flow pass. A live market snapshot
saved 137 bars. A full RELIANCE.NS AI run saved all 12 agent responses, 137 bars
and 13 distinct progress timestamps. Existing matching debate history was recovered
for one older report. Source and SQLite were backed up privately before migration.

Telegram token verification succeeded. Initial delivery failed because the saved
destination was the bot's own username; configure the actual channel and its
posting permissions in Settings. The UI now provides actionable error messages.


## Angel One Markets

Markets → Connect / settings accepts a SmartAPI key, client code, PIN/password,
and either a current TOTP at connection time or a saved TOTP setup secret for
reconnection. Credentials stay in owner-only `angel-private.json` on the server;
API responses do not disclose them. Never commit credentials.

The isolated `.broker-venv` runs `tradingagents-market.service` on loopback 8060.
Install `dashboard/broker/requirements.txt` into that environment. Nginx routes
only the authenticated `/api/market/stream` WebSocket to it. HTTP commands pass
through the existing CSRF-protected API with an internal HMAC key. One broker
WebSocket serves up to 50 selected NSE/BSE instruments; search uses the public
instrument catalog. Charts include historical candles, volume and SMA 20.

Paper trading starts with INR 1,000,000 in `paper.sqlite3`, separate from real
funds. Fills require recent exchange quotes during regular market hours and
support long-only buys/sells; fees and slippage are not simulated. Live funds,
holdings, positions and orders are read-only. No broker order endpoint exists.

A network connection timeout occurs before credentials can be validated. On
2026-09-09, the Oracle deployment could serve the dashboard and its browser
WebSocket, but connections from the VM to Angel One's REST endpoint timed out.
Broker authentication and live ticks therefore remain unverified on that host.

## Paper automation release

Open Markets → Strategy lab & controls. Save an intraday SMA strategy using a
watchlist instrument, fast/slow periods and quantity. Saved strategies are paused;
start explicitly after connecting the broker feed. The runner checks every 15
seconds, evaluates completed candles, and uses fresh LTP for simulated fills.
A strategy enters only when flat and fast SMA exceeds slow SMA; it exits held
shares when fast SMA is lower. One running strategy per instrument is allowed.
Strategies manage that instrument's shared paper position, including manual buys.
Restarting the service pauses all strategies. Daily bars are backtest-only until
an exchange session/holiday calendar is integrated.

Risk settings apply inside the same SQLite transaction as each manual or
strategy fill: order value, position cost, total invested cost, daily order count,
and daily realized-loss limit. The loss limit blocks buys, not exits, and does not
measure unrealized losses. Limits use IST calendar days. The kill switch blocks
all new fills and pauses strategies; it does not liquidate positions. Releasing
it does not restart strategies. Deterministic strategy/bar order references make
retries idempotent. Audit events record fills, evaluations, strategy controls and
risk changes. The dashboard exports the latest 200 audit entries; the database
retains the full append-only application history (not tamper-proof storage).

Historical simulation uses a signal from completed bars and fills on the next
bar's open with configurable per-side fee/slippage basis points. Open positions
are marked at the final close. Equity, drawdown, fees and fills are charted and
exported with strategy configuration, source and candle-data SHA-256. Import up
to 12 KB of OHLC JSON for offline simulations; broker history requires a working
connection. The database retains 20 simulations and the UI shows the latest 10.
Imported data is not independently verified; simulations do not model liquidity,
corporate actions, detailed Indian charges, or live execution. Paper LTP fills
currently exclude fees and slippage, unlike configurable backtests.

### Release checks and operating limits

The system remains a single-owner paper platform, not a certified production
broker execution system. Real-order endpoints do not exist. Live feed operation
from the Oracle server remains blocked by the Angel One network timeout.
Before enabling real trading, separate work is required for broker reconciliation,
exchange calendars, order lifecycle/partial fills, position-based stops, detailed
transaction costs, resilient execution hosting, disaster recovery drills and
applicable broker/exchange approvals. AI research never submits trades.

Before upgrades, take SQLite online backups (`sqlite3.Connection.backup`) of both
`dashboard.sqlite3` and `paper.sqlite3`, and keep private authentication/config
files in a restricted backup directory. Restore only with web, worker and market
services stopped; restore both state databases and matching private configuration,
then start services and check balances, positions, audit history and paused
strategies. Do not copy active database files without their WAL or an online backup.
