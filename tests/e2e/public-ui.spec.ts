import {
  expect,
  test,
  type Page,
} from "../../frontend/node_modules/@playwright/test/index.js";
import AxeBuilder from "../../frontend/node_modules/@axe-core/playwright/dist/index.mjs";

const routes = [
  { path: "/radar", heading: "Radar" },
  { path: "/insights", heading: "Marché local" },
  { path: "/sources", heading: "Sources" },
  { path: "/configuration", heading: "Configuration" },
] as const;

function watchPageFailures(page: Page) {
  const failures: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") failures.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => failures.push(`page: ${error.message}`));
  page.on("requestfailed", (request) => {
    failures.push(
      `request failed: ${request.url()}: ${request.failure()?.errorText ?? "unknown failure"}`,
    );
  });
  page.on("response", (response) => {
    if (response.status() >= 400) failures.push(`http ${response.status()}: ${response.url()}`);
  });
  return failures;
}

async function expectNoOverlap(page: Page, selector: string, label: string) {
  const overlaps = await page.locator(selector).evaluateAll((elements) => {
    const visible = elements
      .map((element, index) => ({ element, index, box: element.getBoundingClientRect() }))
      .filter(({ box }) => box.width > 0 && box.height > 0);
    const failures: string[] = [];
    for (let left = 0; left < visible.length; left += 1) {
      for (let right = left + 1; right < visible.length; right += 1) {
        const a = visible[left];
        const b = visible[right];
        if (a.element.contains(b.element) || b.element.contains(a.element)) continue;
        const width = Math.min(a.box.right, b.box.right) - Math.max(a.box.left, b.box.left);
        const height = Math.min(a.box.bottom, b.box.bottom) - Math.max(a.box.top, b.box.top);
        if (width > 2 && height > 2) failures.push(`${a.index}:${b.index}:${width}x${height}`);
      }
    }
    return failures;
  });
  expect(overlaps, label).toEqual([]);
}

async function expectSeparated(page: Page, first: string, second: string, label: string) {
  const overlap = await page.evaluate(
    ({ firstSelector, secondSelector }) => {
      const firstElement = document.querySelector(firstSelector);
      const secondElement = document.querySelector(secondSelector);
      if (!firstElement || !secondElement) return null;
      const a = firstElement.getBoundingClientRect();
      const b = secondElement.getBoundingClientRect();
      return {
        width: Math.min(a.right, b.right) - Math.max(a.left, b.left),
        height: Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top),
      };
    },
    { firstSelector: first, secondSelector: second },
  );
  if (overlap !== null) {
    expect(overlap.width > 2 && overlap.height > 2, label).toBeFalsy();
  }
}

async function expectStableLayout(page: Page) {
  await waitForMotionToSettle(page);
  const layout = await page.evaluate(() => {
    const rect = (selector: string) => {
      const element = document.querySelector(selector);
      const box = element?.getBoundingClientRect();
      return box ? { top: box.top, right: box.right, bottom: box.bottom, left: box.left } : null;
    };
    return {
      viewportWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
      scrollY: window.scrollY,
      brand: rect(".brand-bar"),
      navigation: rect(".primary-nav"),
      main: rect(".app-main"),
      heading: rect("h1"),
    };
  });

  expect(layout.scrollWidth, "horizontal document overflow").toBeLessThanOrEqual(
    layout.viewportWidth,
  );
  expect(layout.brand).not.toBeNull();
  expect(layout.navigation).not.toBeNull();
  expect(layout.main).not.toBeNull();
  expect(layout.heading).not.toBeNull();

  if (layout.viewportWidth <= 760) {
    if (layout.scrollY <= 1 && layout.heading!.bottom > 0) {
      expect(layout.heading!.top, "visible heading overlaps the sticky brand bar").toBeGreaterThanOrEqual(
        layout.brand!.bottom - 1,
      );
    }
    expect(layout.navigation!.top, "bottom navigation is outside the viewport").toBeGreaterThanOrEqual(0);
  } else {
    expect(layout.main!.left, "main content overlaps desktop navigation").toBeGreaterThanOrEqual(
      layout.navigation!.right - 1,
    );
  }
  await expectNoOverlap(
    page,
    ".filters input, .filters select, .filters button",
    "filter controls overlap",
  );
  await expectNoOverlap(page, ".offer-list > .offer-row", "offer rows overlap");
  await expectSeparated(page, ".filters", ".results-panel", "filters overlap results list");
  await expectSeparated(page, ".results-panel", ".detail-panel", "list overlaps detail panel");
  await expectSeparated(
    page,
    ".mobile-detail-content",
    ".primary-nav",
    "mobile detail overlaps bottom navigation",
  );
  if (layout.viewportWidth <= 760) {
    await expectSeparated(
      page,
      ".compare-dialog",
      ".primary-nav",
      "comparison dialog overlaps mobile navigation",
    );
  }
  await expectNoOverlap(page, ".compare-grid > article", "comparison columns overlap");
  await expectSeparated(
    page,
    ".yaml-preview",
    ".wizard-actions",
    "YAML preview overlaps wizard controls",
  );
}

async function waitForMotionToSettle(page: Page) {
  await page.evaluate(async () => {
    const animations = document.getAnimations();
    await Promise.all(animations.map((animation) => animation.finished.catch(() => undefined)));
  });
}

async function expectNoAxeViolations(page: Page) {
  await waitForMotionToSettle(page);
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations, "Axe violations").toEqual([]);
}

for (const route of routes) {
  test(`${route.path} is accessible and stable`, async ({ page }) => {
    const failures = watchPageFailures(page);
    await page.goto(route.path);
    await expect(page.getByRole("heading", { level: 1, name: route.heading })).toBeVisible();
    await waitForMotionToSettle(page);
    await expectStableLayout(page);
    await expectNoAxeViolations(page);
    expect(failures, "console, page or HTTP failures").toEqual([]);
  });
}

test("radar filters, detail and comparison remain usable", async ({ page }) => {
  const failures = watchPageFailures(page);
  await page.goto("/radar");
  await expect(page.getByLabel(/offres trouvées/i)).toHaveText("42offres actives");
  const rows = page.locator(".offer-row");
  const initialIds = await rows.evaluateAll((elements) =>
    elements.map((element) => element.getAttribute("data-offer-id")),
  );
  expect(initialIds.length).toBeGreaterThan(1);
  expect(initialIds.every(Boolean), "every offer exposes a stable ID").toBeTruthy();

  await page.getByPlaceholder("Métier, entreprise, lieu").fill("automation");
  await expect(page).toHaveURL(/q=automation/);
  await expect(page.getByLabel(/offres trouvées/i)).not.toHaveAttribute(
    "aria-label",
    "42 offres trouvées",
  );
  await expect(page.getByRole("button", { name: /^Ouvrir / }).first()).toBeVisible();
  const filteredIds = await rows.evaluateAll((elements) =>
    elements.map((element) => element.getAttribute("data-offer-id")),
  );
  expect(filteredIds.length).toBeLessThan(initialIds.length);
  expect(filteredIds).not.toEqual(initialIds);
  expect(filteredIds.every(Boolean), "filtered offers expose stable IDs").toBeTruthy();
  await page.getByRole("button", { name: "Effacer les filtres" }).click();
  await expect(page).not.toHaveURL(/q=/);
  await expect(page.getByLabel(/offres trouvées/i)).toHaveAttribute(
    "aria-label",
    "42 offres trouvées",
  );

  await page.getByRole("button", { name: /^Ouvrir / }).first().click();
  await expect(page.getByRole("region", { name: "Détail de l'offre" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Axes de score" })).toBeVisible();
  await expectStableLayout(page);
  await expectNoAxeViolations(page);
  await page.getByRole("button", { name: "Fermer le détail" }).click();

  const compare = page.getByRole("checkbox", { name: /^Comparer / });
  await compare.nth(0).check();
  await compare.nth(1).check();
  await page.getByRole("button", { name: /Comparer 2 offres/ }).click();
  const dialog = page.getByRole("dialog", { name: "Comparaison" });
  await expect(dialog).toBeVisible();
  await expect(dialog.locator("article")).toHaveCount(2);
  await expectStableLayout(page);
  await expectNoAxeViolations(page);
  await page.getByRole("button", { name: "Fermer la comparaison" }).click();

  await expectStableLayout(page);
  expect(failures, "console, page or HTTP failures").toEqual([]);
});

test("demo rescore remains compatible with Radar filters and Insights", async ({ page, request }) => {
  const failures = watchPageFailures(page);
  const sessionResponse = await request.get("/api/session");
  expect(sessionResponse.ok()).toBeTruthy();
  const session = (await sessionResponse.json()) as { token: string };
  const rescoreResponse = await request.post("/api/rescore", {
    headers: { "X-Job-Radar-Token": session.token },
  });
  expect(rescoreResponse.ok()).toBeTruthy();
  expect(await rescoreResponse.json()).toMatchObject({ offers_scored: 42 });

  await page.goto("/radar");
  await expect(page.getByLabel(/offres trouvées/i)).toHaveAttribute(
    "aria-label",
    "42 offres trouvées",
  );
  await page.getByLabel("Décision").selectOption("prioritize");
  await expect(page).toHaveURL(/decision=prioritize/);
  const prioritized = page.locator('.offer-row[data-decision="prioritize"]');
  await expect(prioritized.first()).toBeVisible();
  expect(await prioritized.count()).toBeGreaterThan(0);

  await page.getByRole("link", { name: "Insights" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Marché local" })).toBeVisible();
  const decisionMetrics = page.locator(".metric-strip [data-decision]");
  await expect(decisionMetrics).toHaveCount(4);
  const decisions = await decisionMetrics.evaluateAll((elements) =>
    elements.map((element) => element.getAttribute("data-decision")),
  );
  expect(new Set(decisions)).toEqual(new Set(["reject", "monitor", "review", "prioritize"]));
  await expectNoAxeViolations(page);
  expect(failures, "console, page or HTTP failures").toEqual([]);
});

test("configuration validates all four local steps without writing", async ({ page }) => {
  const failures = watchPageFailures(page);
  await page.goto("/configuration");
  await expect(page.getByRole("heading", { level: 2, name: "Profil" })).toBeVisible();

  for (const step of ["Recherche", "Poids", "Sources"]) {
    await page.getByRole("button", { name: new RegExp(`${step}$`) }).click();
    await expect(page.getByRole("heading", { level: 2, name: step })).toBeVisible();
  }
  await page.getByRole("button", { name: "Valider et afficher l’aperçu" }).click();
  await expect(page.getByRole("region", { name: "Aperçu YAML" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Enregistrer localement/ })).toBeEnabled();

  await expectStableLayout(page);
  await expectNoAxeViolations(page);
  expect(failures, "console, page or HTTP failures").toEqual([]);
});

test("reduced motion removes meaningful transitions", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile-390", "single representative reduced-motion run");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/radar");
  await expect(page.getByRole("button", { name: /^Ouvrir / }).first()).toBeVisible();

  const timings = await page.locator(".offer-row").first().evaluate((element) => {
    const style = getComputedStyle(element);
    const milliseconds = (value: string) =>
      value.endsWith("ms") ? Number.parseFloat(value) : Number.parseFloat(value) * 1000;
    return {
      animation: milliseconds(style.animationDuration),
      transition: milliseconds(style.transitionDuration),
    };
  });
  expect(timings.animation).toBeLessThanOrEqual(0.02);
  expect(timings.transition).toBeLessThanOrEqual(0.02);
});

test("the public favicon is served as an image", async ({ request }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1440", "one asset contract is sufficient");
  const response = await request.get("/favicon.svg");
  expect(response.ok()).toBeTruthy();
  expect(response.headers()["content-type"]).toContain("image/svg+xml");
});
