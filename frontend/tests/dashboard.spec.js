import { test, expect } from "@playwright/test";
test("authenticated dashboard, charts, reports, settings and mobile layout", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  await page.goto("http://127.0.0.1:8051/");
  await page.getByLabel("Username", { exact: true }).fill("tester");
  await page
    .getByLabel("Password", { exact: true })
    .fill("dashboard-test-password");
  await page.getByRole("button", { name: "Sign in →" }).click();
  await expect(
    page.getByRole("heading", { name: "A clearer view of your next move." }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", {
      name: "Adjusted daily price, moving averages, and volume",
    }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Line", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Candles", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "/private/tmp/tradingagents-dashboard-desktop.png",
    fullPage: true,
  });
  await page.locator("nav button").filter({ hasText: "Agents" }).click();
  await expect(
    page.getByRole("heading", { name: "Market analyst", exact: true }).first(),
  ).toBeVisible();
  await page.getByRole("button", { name: /Bull researcher/ }).click();
  await expect(
    page.getByRole("heading", { name: "Bull researcher", exact: true }).first(),
  ).toBeVisible();
  expect(await page.evaluate(() => window.injected)).toBeUndefined();
  expect(await page.locator('a[href^="javascript:"]').count()).toBe(0);
  await page.locator("nav button").filter({ hasText: "Signals" }).click();
  await expect(
    page.getByRole("heading", { name: "Trade proposal & price levels" }),
  ).toBeVisible();
  await page.locator("nav button").filter({ hasText: "Settings" }).click();
  await expect(
    page.getByRole("heading", { name: "Telegram channel", exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("Channel username or chat ID")
    .fill("@research_channel");
  await page
    .getByRole("button", { name: "Save Telegram", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText(
    "Telegram settings saved.",
  );
  await page.locator("nav button").filter({ hasText: "Overview" }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "/private/tmp/tradingagents-dashboard-mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.locator("select[name=mode]").selectOption("snapshot");
  await page
    .getByRole("button", { name: "↗ Run analysis", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("Analysis queued.");
  await expect(page.locator(".running-banner")).toBeVisible();
  expect(errors).toEqual([]);
});
