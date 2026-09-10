import { test, expect } from "@playwright/test";
test("paper strategy controls, kill switch, and historical chart", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const state = {
    strategies: [],
    backtests: [],
    audit: [],
    heartbeat: Date.now() / 1000,
    risk: {
      halted: false,
      max_order_value: 250000,
      max_position_cost: 500000,
      max_invested_capital: 1000000,
      max_daily_realized_loss: 10000,
      max_daily_orders: 100,
    },
  };
  await page.route("**/api/market/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let data = {};
    if (path.endsWith("/status"))
      data = {
        watchlist: [],
        ticks: {},
        connected: false,
        authenticated: false,
      };
    if (path.endsWith("/paper"))
      data = {
        cash: 1000000,
        positions: [],
        orders: [],
        equity: 1000000,
        realized: 0,
      };
    if (path.endsWith("/automation")) data = state;
    if (path.endsWith("/strategy-save")) {
      state.strategies = [
        {
          id: "a".repeat(32),
          config: {
            name: "SMA trend",
            key: "NSE:2885",
            fast: 10,
            slow: 30,
            interval: "5m",
          },
          status: "paused",
          message: "Not started",
        },
      ];
      data = { message: "Strategy saved paused." };
    }
    if (path.endsWith("/strategy-start")) {
      state.strategies[0].status = "running";
      data = { message: "Strategy updated." };
    }
    if (path.endsWith("/halt")) {
      state.risk.halted = true;
      state.strategies[0].status = "paused";
      data = { message: "Paper execution halted. Positions remain open." };
    }
    if (path.endsWith("/backtest"))
      data = {
        message: "Historical simulation completed.",
        result: {
          ending_equity: 1000100,
          return_pct: 0.01,
          max_drawdown_pct: 0.1,
          fees: 10,
          trades: [],
          model: "Next bar open",
          curve: [
            { time: 1700000000, equity: 1000000 },
            { time: 1700000300, equity: 1000100 },
          ],
        },
      };
    await route.fulfill({ json: data });
  });
  await page.routeWebSocket("**/api/market/stream", () => {});
  await page.goto("http://127.0.0.1:8051/");
  await page.getByLabel("Username", { exact: true }).fill("tester");
  await page
    .getByLabel("Password", { exact: true })
    .fill("dashboard-test-password");
  await page.getByRole("button", { name: "Sign in →" }).click();
  await page.locator("nav button").filter({ hasText: "Markets" }).click();
  await page.getByLabel("Instrument token", { exact: true }).fill("NSE:2885");
  await page.getByRole("button", { name: "Save paused strategy" }).click();
  await expect(
    page.getByText("Strategy saved paused.", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Start paper", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Pause", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Halt all paper execution" }).click();
  await expect(
    page.getByRole("button", { name: "Start paper", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Run backtest" }).click();
  await expect(
    page.getByRole("img", { name: "Backtest equity curve" }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});
