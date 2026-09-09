import { test } from "node:test";
import assert from "node:assert/strict";
import { chartBars, readable, tone, number } from "../lib/research.mjs";
test("historical fallback never fabricates OHLC or volume", () => {
  const bars = chartBars(
    { recent_closes: [{ date: "2026-09-08", close: 10 }] },
    20,
  );
  assert.equal(bars[0].open, undefined);
  assert.equal(bars.length, 1);
});
test("unknown values stay unavailable", () => {
  assert.equal(number(null), "—");
  assert.equal(tone("Not available"), "neutral");
});
test("structured agent JSON becomes an object for readable rendering", () =>
  assert.deepEqual(readable('{"action":"Hold"}'), { action: "Hold" }));
