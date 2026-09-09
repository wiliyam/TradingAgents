export const number = (value, digits = 2) =>
  typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString("en-IN", { maximumFractionDigits: digits })
    : "—";
export const tone = (signal) =>
  ["Buy", "Overweight"].includes(signal)
    ? "positive"
    : ["Sell", "Underweight"].includes(signal)
      ? "negative"
      : "neutral";
export function readable(content) {
  if (typeof content !== "string") return content;
  try {
    const value = JSON.parse(content);
    if (value && typeof value === "object") return value;
  } catch {}
  return content;
}
export function chartBars(snapshot, limit) {
  return (snapshot?.bars || snapshot?.recent_closes || [])
    .filter((b) => Number.isFinite(b.close))
    .slice(-limit);
}
