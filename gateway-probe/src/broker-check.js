import { timingSafeEqual } from "node:crypto";
import WebSocket from "ws";

const BASE = "https://apiconnect.angelone.in";
const errors = {
  AB1050: "The current TOTP was rejected.",
  AB1000: "Client code or PIN was rejected.",
  AB1007: "Angel One rejected the account login.",
  AB1006: "Angel One reports the account is blocked for trading.",
  AG8001: "Angel One rejected the authentication token.",
  AB1010: "Angel One reports an expired session.",
};
const safeCode = (code) => (Object.hasOwn(errors, code) ? code : "UNKNOWN");
function valid(body) {
  if (
    !body ||
    typeof body !== "object" ||
    Array.isArray(body) ||
    Object.keys(body).some(
      (k) => !["api_key", "client_code", "password", "totp"].includes(k),
    )
  )
    return false;
  return (
    typeof body.api_key === "string" &&
    /^[A-Za-z0-9_-]{4,128}$/.test(body.api_key) &&
    typeof body.client_code === "string" &&
    /^[A-Za-z0-9]{3,32}$/.test(body.client_code) &&
    typeof body.password === "string" &&
    body.password.length >= 4 &&
    body.password.length <= 128 &&
    typeof body.totp === "string" &&
    /^\d{6}$/.test(body.totp)
  );
}
export function createBrokerCheck({
  secret = process.env.PROBE_TOKEN,
  run = runBrokerCheck,
} = {}) {
  return async (req, res) => {
    res.setHeader("Cache-Control", "no-store");
    res.setHeader("X-Content-Type-Options", "nosniff");
    if (!secret || secret.length < 32)
      return res.status(503).json({ error: "Probe is not configured." });
    const incoming = Buffer.from(
      typeof req.headers.authorization === "string"
        ? req.headers.authorization
        : "",
    );
    const expected = Buffer.from("Bearer " + secret);
    if (
      incoming.length !== expected.length ||
      !timingSafeEqual(incoming, expected)
    )
      return res.status(401).json({ error: "Unauthorized" });
    if (req.method !== "POST")
      return res.status(405).json({ error: "Use POST." });
    if (!valid(req.body))
      return res
        .status(400)
        .json({
          error:
            "Provide API key, client code, PIN/password and a current six-digit TOTP only.",
        });
    try {
      return res
        .status(200)
        .json({
          region: process.env.VERCEL_REGION || "local",
          ...(await run(req.body)),
          orders_submitted: 0,
        });
    } catch {
      return res
        .status(502)
        .json({
          error:
            "Broker verification could not complete. No orders were submitted.",
        });
    }
  };
}
export function observeStream(
  credentials,
  session,
  { Socket = WebSocket, observeMs = 12000 } = {},
) {
  return new Promise((resolve) => {
    const start = performance.now();
    let done = false,
      heartbeat;
    const result = {
      connected: false,
      pongs: 0,
      quote_frames: 0,
      fresh_quotes: 0,
      closed_early: false,
    };
    const socket = new Socket("wss://smartapisocket.angelone.in/smart-stream", {
      headers: {
        Authorization: session.jwtToken,
        "x-api-key": credentials.api_key,
        "x-client-code": credentials.client_code,
        "x-feed-token": session.feedToken,
      },
      handshakeTimeout: 8000,
      maxPayload: 65536,
      perMessageDeflate: false,
      followRedirects: false,
    });
    const finish = () => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      clearInterval(heartbeat);
      result.observed_ms = Math.round(performance.now() - start);
      socket.terminate();
      resolve(result);
    };
    const timer = setTimeout(finish, observeMs);
    socket.on("error", () => {
      if (!done) {
        result.error = "WebSocket connection failed";
        finish();
      }
    });
    socket.on("unexpected-response", (_, response) => {
      if (done) return;
      result.http_status = response.statusCode;
      response.destroy();
      finish();
    });
    socket.on("close", () => {
      if (!done) {
        result.closed_early = true;
        finish();
      }
    });
    socket.on("open", () => {
      if (done) return;
      result.connected = true;
      result.handshake_ms = Math.round(performance.now() - start);
      socket.send(
        JSON.stringify({
          correlationID: "flowcheck1",
          action: 1,
          params: {
            mode: 2,
            tokenList: [{ exchangeType: 1, tokens: ["2885"] }],
          },
        }),
      );
      socket.send("ping");
      heartbeat = setInterval(() => {
        if (socket.readyState === 1) socket.send("ping");
      }, 10000);
    });
    socket.on("message", (data, isBinary) => {
      if (done) return;
      if (!isBinary) {
        if (data.toString() === "pong") result.pongs++;
        else {
          try {
            const v = JSON.parse(data.toString());
            if (v.errorCode || v.errorcode) result.subscription_error = true;
          } catch {
            /* No raw broker data is logged or returned. */
          }
        }
        return;
      }
      if (
        !Buffer.isBuffer(data) ||
        data.length < 123 ||
        data[0] !== 2 ||
        data[1] !== 1 ||
        data.subarray(2, 27).toString().replace(/\0.*$/s, "") !== "2885"
      )
        return;
      const timestamp = Number(data.readBigInt64LE(35)) / 1000;
      const price = Number(data.readBigInt64LE(43)) / 100;
      if (!Number.isFinite(timestamp) || !Number.isFinite(price) || price <= 0)
        return;
      const age = Date.now() / 1000 - timestamp;
      result.quote_frames++;
      result.last_quote_age_seconds = Math.round(age * 1000) / 1000;
      if (age >= 0 && age <= 15) result.fresh_quotes++;
    });
  });
}
export async function runBrokerCheck(
  credentials,
  { request = fetch, observe = observeStream } = {},
) {
  const ipResponse = await request("https://api.ipify.org?format=json", {
    signal: AbortSignal.timeout(5000),
    redirect: "error",
  });
  if (!ipResponse.ok) throw Error("IP lookup failed");
  const { ip } = await ipResponse.json();
  if (typeof ip !== "string" || !/^\d{1,3}(\.\d{1,3}){3}$/.test(ip))
    throw Error("Invalid egress address");
  const headers = {
    "Content-Type": "application/json",
    Accept: "application/json",
    "X-UserType": "USER",
    "X-SourceID": "WEB",
    "X-ClientLocalIP": "127.0.0.1",
    "X-ClientPublicIP": ip,
    "X-MACAddress": "00:00:00:00:00:00",
    "X-PrivateKey": credentials.api_key,
  };
  const started = performance.now();
  const response = await request(
    BASE + "/rest/auth/angelbroking/user/v1/loginByPassword",
    {
      method: "POST",
      headers,
      body: JSON.stringify({
        clientcode: credentials.client_code,
        password: credentials.password,
        totp: credentials.totp,
      }),
      signal: AbortSignal.timeout(10000),
      redirect: "error",
    },
  );
  const value = await response.json();
  if (!response.ok || value.status !== true) {
    const code = safeCode(value.errorcode);
    return {
      authenticated: false,
      http_status: response.status,
      error_code: code,
      error:
        errors[code] ||
        "Angel One rejected login. Verify the API key and account credentials.",
    };
  }
  const session = value.data;
  if (
    typeof session?.jwtToken !== "string" ||
    !session.jwtToken ||
    typeof session?.feedToken !== "string" ||
    !session.feedToken
  )
    throw Error("Incomplete session");
  const summary = {
    authenticated: true,
    login_ms: Math.round(performance.now() - started),
  };
  const history = async () => {
    const now = new Date(Date.now() + 19800000);
    const from = new Date(now.getTime() - 7 * 86400000)
      .toISOString()
      .slice(0, 10);
    const to = now.toISOString().slice(0, 10);
    try {
      const r = await request(
        BASE + "/rest/secure/angelbroking/historical/v1/getCandleData",
        {
          method: "POST",
          headers: { ...headers, Authorization: "Bearer " + session.jwtToken },
          body: JSON.stringify({
            exchange: "NSE",
            symboltoken: "2885",
            interval: "FIVE_MINUTE",
            fromdate: from + " 00:00",
            todate: to + " 23:59",
          }),
          signal: AbortSignal.timeout(10000),
          redirect: "error",
        },
      );
      const v = await r.json();
      return {
        ok: r.ok && v.status === true,
        candle_count: Array.isArray(v.data) ? v.data.length : 0,
      };
    } catch {
      return { ok: false, error: "Historical data request failed" };
    }
  };
  const streams = async () => {
    const first = await observe(credentials, session);
    if (!first.connected) return { first, reconnect: null };
    const reconnect = await observe(credentials, session);
    return { first, reconnect };
  };
  const [historical, stream] = await Promise.all([history(), streams()]);
  return {
    ...summary,
    historical,
    stream,
    note: "Read-only test. No orders submitted. Sessions are not stored by this probe. Market-closed quotes may be historical; this short test does not establish market-hours reliability.",
  };
}
