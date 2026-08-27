import { execFileSync } from "node:child_process";
import { mkdirSync, rmSync } from "node:fs";
import { fileURLToPath } from "node:url";

import playwright from "../../frontend/node_modules/playwright-core/index.js";

const { chromium } = playwright;

const root = fileURLToPath(new URL("../..", import.meta.url));
const output = `${root}/docs/assets`;
const temporary = "/tmp/job-radar-public-captures";

async function settle(page) {
  await page.evaluate(async () => {
    await Promise.all(
      document.getAnimations().map((animation) => animation.finished.catch(() => undefined)),
    );
  });
}

async function capture(page, name) {
  const png = `${temporary}/${name}.png`;
  await settle(page);
  await page.screenshot({ path: png, animations: "disabled" });
  execFileSync("cwebp", ["-quiet", "-q", "82", "-metadata", "none", png, "-o", `${output}/${name}.webp`]);
}

mkdirSync(output, { recursive: true });
rmSync(temporary, { recursive: true, force: true });
mkdirSync(temporary, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ locale: "fr-FR", viewport: { width: 1440, height: 900 } });
try {
  await page.goto("http://127.0.0.1:4173/radar");
  await page.getByRole("heading", { level: 1, name: "Radar" }).waitFor();
  await capture(page, "radar-overview");

  await page.setViewportSize({ width: 1024, height: 768 });
  await page.goto("http://127.0.0.1:4173/radar");
  await page.getByRole("button", { name: /^Ouvrir / }).first().click();
  await page.getByRole("region", { name: "Détail de l'offre" }).waitFor();
  await capture(page, "score-explained");

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("http://127.0.0.1:4173/insights");
  await page.getByRole("heading", { level: 1, name: "Marché local" }).waitFor();
  await capture(page, "insights");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("http://127.0.0.1:4173/radar");
  await page.getByRole("heading", { level: 1, name: "Radar" }).waitFor();
  await capture(page, "mobile");
} finally {
  await browser.close();
  rmSync(temporary, { recursive: true, force: true });
}
