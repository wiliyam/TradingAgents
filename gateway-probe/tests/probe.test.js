import test from "node:test";
import assert from "node:assert/strict";
import { createProbe } from "../src/probe.js";
function response() {
  return {
    headers: {},
    setHeader(k, v) {
      this.headers[k] = v;
    },
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
test("unauthorized requests cannot trigger outbound calls", async () => {
  let called = false;
  const handle = createProbe({
    secret: "s".repeat(40),
    request: async () => {
      called = true;
    },
  });
  const res = response();
  await handle({ method: "GET", headers: {} }, res);
  assert.equal(res.code, 401);
  assert.equal(called, false);
});
test("authorized probe reports fixed endpoints and response times only", async () => {
  const calls = [];
  const handle = createProbe({
    secret: "s".repeat(40),
    region: "bom1",
    request: async (url, opts) => {
      calls.push([url, opts]);
      return { status: 401, body: { cancel: async () => {} } };
    },
  });
  const res = response();
  await handle(
    { method: "GET", headers: { authorization: "Bearer " + "s".repeat(40) } },
    res,
  );
  assert.equal(res.code, 200);
  assert.equal(res.body.region, "bom1");
  assert.equal(calls.length, 3);
  assert.equal(res.body.results[0].reachable, true);
  assert.equal(calls[0][1].body, "{}");
  assert.ok(calls.every(([, opts]) => !opts.headers.Authorization));
});
test("errors are redacted and missing configuration fails closed", async () => {
  const res = response();
  await createProbe({ secret: "" })({ method: "GET", headers: {} }, res);
  assert.equal(res.code, 503);
  const fail = createProbe({
    secret: "s".repeat(40),
    request: async () => {
      throw Error("sensitive-details");
    },
  });
  const r = response();
  await fail(
    { method: "GET", headers: { authorization: "Bearer " + "s".repeat(40) } },
    r,
  );
  assert.equal(r.body.results[0].reachable, false);
  assert.ok(!JSON.stringify(r.body).includes("sensitive-details"));
});
