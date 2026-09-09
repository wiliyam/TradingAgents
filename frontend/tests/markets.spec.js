import { test, expect } from "@playwright/test";
test("market workspace streams prices and separates paper/live actions", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  const now = Math.floor(Date.now() / 1000);
  const item = {
    key: "NSE:2885",
    token: "2885",
    symbol: "RELIANCE-EQ",
    exchange: "NSE",
    kind: "equity",
  };
  const state = {
    configured: true,
    authenticated: true,
    connected: true,
    client_code: "AB••••",
    watchlist: [item],
    server_time: now,
    market_session_open: true,
    ticks: {
      "NSE:2885": {
        price: 1355,
        timestamp: now,
        received: now,
        open: 1340,
        high: 1360,
        low: 1330,
        volume: 50000,
        previous_close: 1340,
        change_percent: 1.12,
      },
    },
    real_orders_enabled: false,
  };
  await page.route("**/api/market/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let data = {};
    if (path.endsWith("/status")) data = state;
    if (path.endsWith("/search")) data = { instruments: [item] };
    if (path.endsWith("/paper"))
      data = {
        cash: 1000000,
        positions: [],
        orders: [],
        equity: 1000000,
        realized: 0,
      };
    if (path.endsWith("/portfolio"))
      data = { data: [], as_of: now, mode: "live", read_only: true };
    if (path.endsWith("/candles"))
      data = {
        seconds: 300,
        interval: "5m",
        candles: Array.from({ length: 40 }, (_, i) => ({
          time: Math.floor(now / 300) * 300 - 12000 + i * 300,
          open: 1300 + i,
          high: 1310 + i,
          low: 1295 + i,
          close: 1305 + i,
          volume: 2000 + i * 10,
        })),
      };
    if (path.endsWith("/paper-order")) {
      expect(route.request().postData()).toContain("paper");
      data = { message: "Paper order filled. No broker order sent." };
    }
    await route.fulfill({ json: data });
  });
  await page.routeWebSocket("**/api/market/stream", (ws) => {
    ws.send(JSON.stringify({ type: "market", data: state }));
  });
  await page.goto("http://127.0.0.1:8051/");
  await page.getByLabel("Username", { exact: true }).fill("tester");
  await page
    .getByLabel("Password", { exact: true })
    .fill("dashboard-test-password");
  await page.getByRole("button", { name: "Sign in →" }).click();
  await page.locator("nav button").filter({ hasText: "Markets" }).click();
  await expect(
    page.getByRole("img", {
      name: "Interactive Angel One 5m candlestick chart",
    }),
  ).toBeVisible();
  await expect(page.getByText("Live quote", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "Place paper order", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("Paper order filled");
  await page
    .getByRole("button", { name: "Live account · read only", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Live execution disabled" }),
  ).toBeDisabled();
  await page.screenshot({
    path: "/private/tmp/tradingagents-markets-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "/private/tmp/tradingagents-markets-mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});
