# Mumbai broker connectivity probe

Isolated Vercel project for testing the route from Mumbai to Angel One and the
Oracle platform. It does not receive broker credentials, authenticate an account,
place orders, or change Oracle state. `GET /api/probe` requires a random secret of
at least 32 characters in the `PROBE_TOKEN` environment variable and an
`Authorization: Bearer <token>` header. Never put the token in URLs or source.

The fixed targets are Angel One's login endpoint (empty login payload), its feed
endpoint (HTTPS without upgrade/authentication), and the Oracle health endpoint.
All responses, including HTTP errors, demonstrate HTTP reachability only. Measure
authentication, actual stream delivery, disconnects and tick age separately before
using Vercel as a broker relay. Requests time out after 8 seconds; redirects are
not followed and response bodies are discarded. No arbitrary proxy URL is accepted.

Deploy from this directory to a separate project with Fluid compute enabled.
Run `npm test` to check authentication, fixed destinations and error redaction.

## Read-only authenticated flow check

`POST /api/broker-check` uses the same probe bearer token. Its JSON body accepts
only `api_key`, `client_code`, `password` and the current six-digit `totp`.
Do not send a TOTP setup secret. The test sends supplied credentials over HTTPS to the Vercel function and then
to Angel One; it never logs them or returns session tokens. With explicit owner
authorization, `ANGELONE_API_KEY`, `ANGELONE_CLIENT_CODE`, and `ANGELONE_PIN` can
be saved as sensitive production environment variables. In that mode, send only
`{"totp":"<current-code>"}` in the request body. The TOTP setup secret stays local.
Session tokens remain in memory only; environment credentials persist until removed. Keep request/body logging
and tracing disabled when operating this credential-bearing endpoint.

The test resolves the current egress IP, logs in, fetches a week of RELIANCE NSE
five-minute candles, then subscribes to that instrument for two bounded 12-second
WebSocket observations with a deliberate reconnect. Results include handshake,
heartbeat and quote-freshness measurements only. This is a short diagnostic,
not proof of uninterrupted market-hours streaming or an execution gateway.
It has no order, cancellation, fund-transfer or account-modification endpoints.

## Verified diagnostic result — 2026-09-13

The deployed function reported region `bom1`. Account authentication succeeded
in 42 ms, the historical request returned 365 candles, and two successive
12-second WebSocket observations connected successfully (27 ms and 19 ms
handshakes). Each received two heartbeat responses and one quote frame; neither
connection closed unexpectedly during observation. Both quotes were stale
(approximately 26 hours old), so fresh market-hours delivery and sustained
stream reliability remain unverified. No orders were submitted. These short
samples are observations, not latency guarantees or execution benchmarks.
