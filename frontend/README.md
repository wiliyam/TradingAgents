# Next.js research dashboard

This is the only dashboard UI. Python provides the authenticated API, SQLite queue,
TradingAgents research engine and Telegram notifications; it no longer renders pages.

## Build and test

Requires Node.js 22 or newer.

```sh
npm ci
npm run build
npm test
npx playwright install chromium
npx playwright test
```

Browser tests start the isolated fixture API on `http://127.0.0.1:8051` (see
`dashboard/ui_fixture.py`). Install `dashboard/requirements.txt` and set
`TEST_PYTHON` if your Python environment is not the default `python3`. Never point fixture tests at production: they save test
settings. `CHROMIUM_PATH` optionally selects an existing browser executable.

Next.js exports to `out/`. Deploy its contents to `dashboard/web/`, then restart
the Python web service. The authenticated API serves the static build from the
same origin and derives CSP hashes for Next.js's inline bootstrap scripts. No
Node.js runtime, public API port, external chart CDN or public report files are
needed on the Oracle VM. `npm run dev` is for UI development only; the full
same-origin login flow requires the exported build served through the API.

## Screens

- Overview: start research; adjusted daily line/candlestick charts, moving
  averages, volume, RSI, final rating, and saved agent output counts.
- Agents: all 12 analyst/research/trader/risk/portfolio outputs, readable Markdown
  and structured records, automatically refreshed while a job runs.
- Signals: five-tier model assessment, trade proposal, risk review and a clearly
  defined technical checklist. Checklist scores are not model confidence.
- History: symbol/date filtering, reopening runs, JSON export and browser print.
- Settings: model provider, write-only API credentials, password changes and
  Telegram channel configuration with an explicit test-message action.

No broker connection, order placement, scheduler or performance backtest is
implemented. Historical data and agent outputs are displayed as saved, with
missing fields marked unavailable. Telegram notifications are opt-in and contain
only a summary and a private report link. Never commit bot tokens or API keys.
