import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  testMatch: "**/*.spec.js",
  use: {
    headless: true,
    viewport: { width: 1440, height: 1000 },
    launchOptions: process.env.CHROMIUM_PATH
      ? { executablePath: process.env.CHROMIUM_PATH }
      : {},
  },
  reporter: "list",
  workers: 1,
  webServer: {
    command: `${process.env.TEST_PYTHON || "python3"} -m dashboard.ui_fixture`,
    cwd: "..",
    url: "http://127.0.0.1:8051/login",
    reuseExistingServer: false,
    timeout: 30000,
  },
});
