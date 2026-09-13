import test from "node:test";
import assert from "node:assert/strict";
import { createBrokerCheck, runBrokerCheck } from "../src/broker-check.js";
function response() {
  return {
    setHeader() {},
    status(n) {
      this.code = n;
      return this;
    },
    json(v) {
      this.body = v;
      return this;
    },
  };
}
const credentials = {
  api_key: "test-key",
  client_code: "TEST123",
  password: "0123",
  totp: "123456",
};
test("authorization and validation block outbound authentication", async () => {
  let calls = 0;
  const h = createBrokerCheck({
    secret: "s".repeat(40),
    run: async () => {
      calls++;
    },
  });
  for (const req of [
    { method: "POST", headers: {}, body: credentials },
    {
      method: "POST",
      headers: { authorization: "Bearer " + "s".repeat(40) },
      body: { ...credentials, totp: "bad" },
    },
  ]) {
    const r = response();
    await h(req, r);
    assert.ok([400, 401].includes(r.code));
  }
  assert.equal(calls, 0);
});
test("approved flow returns only safe summary and accepts current TOTP", async () => {
  const r = response();
  let supplied;
  await createBrokerCheck({
    secret: "s".repeat(40),
    run: async (c) => {
      supplied = c;
      return { authenticated: true };
    },
  })(
    {
      method: "POST",
      headers: { authorization: "Bearer " + "s".repeat(40) },
      body: credentials,
    },
    r,
  );
  assert.equal(r.code, 200);
  assert.equal(supplied.password, "0123");
  assert.ok(!JSON.stringify(r.body).includes("0123"));
});
test("broker rejection does not expose upstream response", async () => {
  const request = async (url) =>
    url.includes("ipify")
      ? { ok: true, json: async () => ({ ip: "192.0.2.1" }) }
      : {
          ok: true,
          status: 200,
          json: async () => ({
            status: false,
            errorcode: "AB1050",
            message: "secret token in upstream message",
          }),
        };
  const value = await runBrokerCheck(credentials, { request });
  assert.equal(value.authenticated, false);
  assert.equal(value.error_code, "AB1050");
  assert.ok(!JSON.stringify(value).includes("secret token"));
});
test("transport failures are redacted", async () => {
  const r = response();
  await createBrokerCheck({
    secret: "s".repeat(40),
    run: async () => {
      throw Error("private-pin");
    },
  })(
    {
      method: "POST",
      headers: { authorization: "Bearer " + "s".repeat(40) },
      body: credentials,
    },
    r,
  );
  assert.equal(r.code, 502);
  assert.ok(!JSON.stringify(r.body).includes("private-pin"));
});

test("successful flow checks history and reconnect without returning tokens", async () => {
  const calls = [];
  let connections = 0;
  const request = async (url, options) => {
    calls.push({ url, options });
    if (url.includes("ipify"))
      return { ok: true, json: async () => ({ ip: "192.0.2.1" }) };
    if (url.includes("loginByPassword"))
      return {
        ok: true,
        status: 200,
        json: async () => ({
          status: true,
          data: { jwtToken: "private-jwt", feedToken: "private-feed" },
        }),
      };
    return { ok: true, json: async () => ({ status: true, data: [[1], [2]] }) };
  };
  const observe = async (_, session) => {
    assert.equal(session.jwtToken, "private-jwt");
    connections++;
    return { connected: true, pongs: 1 };
  };
  const result = await runBrokerCheck(credentials, { request, observe });
  assert.equal(result.authenticated, true);
  assert.equal(result.historical.candle_count, 2);
  assert.equal(connections, 2);
  assert.ok(!JSON.stringify(result).includes("private-"));
  assert.equal(calls.length, 3);
  assert.ok(
    calls.every((c) => !/placeorder|modifyorder|cancelorder/i.test(c.url)),
  );
});

test("WebSocket validates subscription, receives heartbeat and closes at deadline", async () => {
  const { EventEmitter } = await import("node:events");
  const { observeStream } = await import("../src/broker-check.js");
  let instance;
  class Socket extends EventEmitter {
    constructor(url, options) {
      super();
      instance = this;
      this.options = options;
      this.readyState = 1;
      this.sent = [];
      queueMicrotask(() => this.emit("open"));
    }
    send(value) {
      this.sent.push(value);
      if (value === "ping")
        queueMicrotask(() => this.emit("message", Buffer.from("pong"), false));
    }
    terminate() {
      this.terminated = true;
    }
  }
  const result = await observeStream(
    credentials,
    { jwtToken: "jwt", feedToken: "feed" },
    { Socket, observeMs: 20 },
  );
  assert.equal(result.connected, true);
  assert.equal(result.pongs, 1);
  assert.equal(result.fresh_quotes, 0);
  assert.equal(instance.terminated, true);
  assert.equal(instance.options.followRedirects, false);
  assert.equal(
    JSON.parse(instance.sent[0]).params.tokenList[0].tokens[0],
    "2885",
  );
});

test("sensitive environment credentials allow a TOTP-only request without disclosure", async () => {
  let supplied;
  const r = response();
  const handler = createBrokerCheck({
    secret: "s".repeat(40),
    storedCredentials: {
      api_key: "stored-key",
      client_code: "CLIENT12",
      password: "0123",
    },
    run: async (c) => {
      supplied = c;
      return { authenticated: true };
    },
  });
  await handler(
    {
      method: "POST",
      headers: { authorization: "Bearer " + "s".repeat(40) },
      body: { totp: "123456" },
    },
    r,
  );
  assert.equal(r.code, 200);
  assert.equal(supplied.api_key, "stored-key");
  assert.equal(supplied.password, "0123");
  assert.equal(supplied.totp, "123456");
  assert.ok(!JSON.stringify(r.body).includes("stored-key"));
});

test("TOTP setup secrets and missing environment configuration fail closed", async () => {
  let calls = 0;
  const handler = createBrokerCheck({
    secret: "s".repeat(40),
    storedCredentials: {},
    run: async () => {
      calls++;
    },
  });
  for (const body of [{ totp_secret: "DO-NOT-SEND" }, { totp: "123456" }]) {
    const r = response();
    await handler(
      {
        method: "POST",
        headers: { authorization: "Bearer " + "s".repeat(40) },
        body,
      },
      r,
    );
    assert.ok([400, 503].includes(r.code));
  }
  assert.equal(calls, 0);
});
