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

test("streamed candles use exchange time and reject old ticks", async () => {
  const { applyTick, candleTime } = await import("../lib/live-chart.mjs");
  const timestamp = Date.parse("2026-09-09T10:20:00+05:30") / 1000;
  assert.equal(
    candleTime(timestamp, 3600),
    Date.parse("2026-09-09T10:15:00+05:30") / 1000,
  );
  const bars = [
    {
      time: candleTime(timestamp, 300),
      open: 100,
      high: 102,
      low: 99,
      close: 101,
      volume: 50,
    },
  ];
  const update = applyTick(
    bars,
    { price: 104, timestamp, volume: 1200 },
    300,
    1100,
  );
  assert.equal(update.bar.high, 104);
  assert.equal(update.bar.volume, 150);
  assert.equal(
    applyTick(
      bars,
      { price: 80, timestamp: timestamp - 600, volume: 1200 },
      300,
      1100,
    ).bar,
    null,
  );
});
