import { timingSafeEqual } from "node:crypto";
const targets = [
  [
    "angel_login",
    "https://apiconnect.angelone.in/rest/auth/angelbroking/user/v1/loginByPassword",
    "POST",
  ],
  ["angel_feed", "https://smartapisocket.angelone.in/smart-stream", "GET"],
  ["oracle", "https://at.arkbytetech.com/healthz", "GET"],
];
export function createProbe({
  secret = process.env.PROBE_TOKEN,
  region = process.env.VERCEL_REGION || "local",
  request = fetch,
} = {}) {
  return async (req, res) => {
    res.setHeader("Cache-Control", "no-store");
    res.setHeader("X-Content-Type-Options", "nosniff");
    if (!secret || secret.length < 32)
      return res.status(503).json({ error: "Probe is not configured." });
    const supplied = Buffer.from(
      typeof req.headers.authorization === "string"
        ? req.headers.authorization
        : "",
    );
    const expected = Buffer.from("Bearer " + secret);
    if (
      supplied.length !== expected.length ||
      !timingSafeEqual(supplied, expected)
    )
      return res.status(401).json({ error: "Unauthorized" });
    if (req.method !== "GET")
      return res.status(405).json({ error: "Use GET." });
    const results = await Promise.all(
      targets.map(async ([name, url, method]) => {
        const start = performance.now();
        try {
          const response = await request(url, {
            method,
            headers: {
              Accept: "application/json",
              "Content-Type": "application/json",
            },
            ...(method === "POST" ? { body: "{}" } : {}),
            redirect: "manual",
            signal: AbortSignal.timeout(8000),
          });
          await response.body?.cancel();
          return {
            name,
            reachable: true,
            http_status: response.status,
            elapsed_ms: Math.round(performance.now() - start),
          };
        } catch {
          return {
            name,
            reachable: false,
            error: "Network or TLS request failed",
            elapsed_ms: Math.round(performance.now() - start),
          };
        }
      }),
    );
    return res
      .status(200)
      .json({
        region,
        results,
        note: "No broker credentials sent. HTTP reachability does not establish account authentication or WebSocket streaming.",
      });
  };
}
