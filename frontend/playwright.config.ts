import { defineConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";

const repositoryRoot = fileURLToPath(new URL("..", import.meta.url));
const e2eData = `/tmp/job-radar-community-e2e-${process.pid}`;

export default defineConfig({
  testDir: "../tests/e2e",
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  outputDir: "../test-results/e2e",
  use: {
    baseURL: "http://127.0.0.1:4173",
    locale: "fr-FR",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [
    { name: "mobile-320", use: { viewport: { width: 320, height: 720 } } },
    { name: "mobile-390", use: { viewport: { width: 390, height: 844 } } },
    { name: "tablet-768", use: { viewport: { width: 768, height: 1024 } } },
    { name: "laptop-1024", use: { viewport: { width: 1024, height: 768 } } },
    { name: "desktop-1440", use: { viewport: { width: 1440, height: 900 } } },
  ],
  webServer: [
    {
      command: `uv run --locked --group dev job-radar demo --data-dir ${e2eData} && uv run --locked --group dev job-radar serve --data-dir ${e2eData}`,
      cwd: repositoryRoot,
      url: "http://127.0.0.1:8000/health",
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: "npm --prefix frontend run dev -- --port 4173 --strictPort",
      cwd: repositoryRoot,
      url: "http://127.0.0.1:4173/health",
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
