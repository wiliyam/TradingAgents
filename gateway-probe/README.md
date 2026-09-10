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
