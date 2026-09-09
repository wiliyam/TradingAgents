// SmartAPI intraday candles align to the Indian cash-market session at 09:15 IST.
export function candleTime(timestamp, seconds) {
  const d = new Date((timestamp + 19800) * 1000);
  const start =
    Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), 3, 45) / 1000;
  return seconds === 86400
    ? start
    : start + Math.floor((timestamp - start) / seconds) * seconds;
}
export function applyTick(bars, tick, seconds, previousVolume) {
  if (
    !tick ||
    !Number.isFinite(tick.price) ||
    tick.price <= 0 ||
    !Number.isFinite(tick.timestamp)
  )
    return { bar: null, volume: previousVolume };
  let time = candleTime(tick.timestamp, seconds);
  const last = bars.at(-1);
  if (
    seconds === 86400 &&
    last &&
    Math.floor((last.time + 19800) / 86400) ===
      Math.floor((time + 19800) / 86400)
  )
    time = last.time;
  if (last && time < last.time) return { bar: null, volume: previousVolume };
  const added =
    Number.isFinite(previousVolume) && Number.isFinite(tick.volume)
      ? Math.max(0, tick.volume - previousVolume)
      : 0;
  const bar =
    last?.time === time
      ? {
          ...last,
          high: Math.max(last.high, tick.price),
          low: Math.min(last.low, tick.price),
          close: tick.price,
          volume: (last.volume || 0) + added,
        }
      : {
          time,
          open: tick.price,
          high: tick.price,
          low: tick.price,
          close: tick.price,
          volume: added,
        };
  return { bar, volume: tick.volume };
}
