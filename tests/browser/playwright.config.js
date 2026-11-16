import { defineConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";

export default defineConfig({
  testDir: ".",
  testMatch: "*.spec.js",
  fullyParallel: false,
  workers: 1,
  timeout: 30000,
  reporter: "list",
  outputDir: "test-results",
  use: {
    baseURL: process.env.LISTENING_BROWSER_URL || "http://127.0.0.1:8018",
    viewport: { width: 1440, height: 1000 },
    launchOptions: process.env.LISTENING_CHROME_PATH
      ? { executablePath: process.env.LISTENING_CHROME_PATH }
      : {},
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: process.env.LISTENING_BROWSER_URL
    ? undefined
    : {
        command: ".venv/bin/python -m tests.browser.serve",
        cwd: fileURLToPath(new URL("../..", import.meta.url)),
        url: "http://127.0.0.1:8018/health",
        reuseExistingServer: false,
        timeout: 20000,
      },
});
