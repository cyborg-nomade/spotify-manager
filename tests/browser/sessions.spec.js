import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";

test.use({ reducedMotion: "reduce" });

async function unlockSessions(page, suffix = "") {
  await page.goto(`/lastfm?tab=sessions&preset=all&tz=UTC${suffix}`);
  await page
    .getByLabel("App password", { exact: true })
    .fill("browser-test-password");
  await page.getByRole("button", { name: "Unlock explorer" }).click();
  await expect(page.locator("#tab-sessions")).toBeVisible();
  await expect(page.locator("#workspace")).toHaveAttribute(
    "aria-busy",
    "false",
  );
  await expect(page.locator("#session-metrics")).toContainText("781");
}

async function apply(page, gap, minimum = "1") {
  await page.locator("#session-gap").fill(gap);
  await page.locator("#session-minimum").fill(minimum);
  await page
    .locator("#session-filters")
    .getByRole("button", { name: "Apply", exact: true })
    .click();
  await expect(page.locator("#workspace")).toHaveAttribute(
    "aria-busy",
    "false",
  );
}

async function download(page, selector, name) {
  const waiting = page.waitForEvent("download");
  await page.locator(selector).click();
  const result = await waiting;
  const path = test.info().outputPath(name);
  await result.saveAs(path);
  return path;
}

test("real gap and size controls change groups, restore context and open exact records", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await unlockSessions(page);
  await expect(page.locator("#tab-sessions canvas")).toHaveCount(2);
  await apply(page, "60");
  await expect(page.locator("#session-metrics strong").first()).toHaveText(
    "780",
  );
  await apply(page, "60", "2");
  await expect(page.locator("#session-metrics strong").first()).toHaveText("1");
  await expect(page.locator("#session-coverage")).toContainText(
    "779 plays are below",
  );
  await expect(page.locator("#sessions-table tbody tr")).toHaveCount(1);
  await page.locator("#sessions-table [data-session]").click();
  await expect(page.locator("#session-records-table tbody tr")).toHaveCount(2);
  await expect(page.locator("#session-records-table")).toContainText(
    "=formula",
  );
  await expect(page.locator("#session-records-table img")).toHaveCount(0);
  expect(await page.evaluate(() => window.musicNameExecuted)).toBeUndefined();
  await expect(page).toHaveURL(/session_gap=60/);
  await expect(page).toHaveURL(/session_min=2/);
  await expect(page).toHaveURL(/session=1733054400000/);
  await page.reload();
  await expect(page.locator("#session-gap")).toHaveValue("60");
  await expect(page.locator("#session-minimum")).toHaveValue("2");
  await expect(page.locator("#session-records-table tbody tr")).toHaveCount(2);
  expect(errors).toEqual([]);
  await page.screenshot({
    path: test.info().outputPath("sessions-desktop.png"),
    fullPage: true,
  });
});

test("all-scope charts, current-page CSV and PNG retain definitions and source versions", async ({
  page,
}) => {
  await unlockSessions(page);
  await apply(page, "60", "2");
  await page.locator("#sessions-table [data-session]").click();
  await expect(page.locator("#session-records-table tbody tr")).toHaveCount(2);
  const groups = await readFile(
    await download(page, "#session-csv", "session-groups.csv"),
    "utf8",
  );
  expect(groups).toContain('"Gap threshold (minutes)","60"');
  expect(groups).toContain('"Minimum recorded plays","2"');
  expect(groups).toContain("Current group page 1");
  expect(groups).toContain("v1-");
  expect(groups).toContain("Observed span ms (not listening duration)");
  const records = await readFile(
    await download(
      page,
      '[data-session-export="records"]',
      "session-records.csv",
    ),
    "utf8",
  );
  expect(records).toContain("'=formula");
  expect(records).toContain("Chronological record page 1");
  expect(records).toContain("1733054400000 / 1733058000000");
  await page.getByText("Session start data", { exact: true }).click();
  const buckets = await readFile(
    await download(
      page,
      '[data-session-export="buckets"]',
      "session-starts.csv",
    ),
    "utf8",
  );
  expect(buckets).toContain("All matching groups");
  await page.getByText("Session size data", { exact: true }).click();
  const sizes = await readFile(
    await download(
      page,
      '[data-session-export="sizes-csv"]',
      "session-sizes.csv",
    ),
    "utf8",
  );
  expect(sizes).toContain('"2–5","1","2"');
  await download(page, '[data-session-export="starts"]', "session-starts.png");
  await download(page, '[data-session-export="sizes"]', "session-sizes.png");
});

test("group and original-record pages work independently and artist history remains available", async ({
  page,
}) => {
  await unlockSessions(page);
  const first = await page
    .locator("#sessions-table [data-session]")
    .first()
    .textContent();
  await page.locator("#session-next").click();
  await expect(page.locator("#session-page")).toContainText("Page 2");
  expect(
    await page.locator("#sessions-table [data-session]").first().textContent(),
  ).not.toBe(first);
  await page.locator("#session-order").selectOption("plays");
  await expect(page.locator("#session-page")).toContainText("Page 1");
  await apply(page, "60", "2");
  // A one-row server page exercises the real record endpoint and UI navigation.
  await page.route("**/sessions/*/records?**", (route) => {
    const url = new URL(route.request().url());
    url.searchParams.set("limit", "1");
    return route.continue({ url: url.href });
  });
  await page.locator("#sessions-table [data-session]").click();
  await expect(page.locator("#session-record-page")).toContainText(
    "Page 1 of 2",
  );
  await page.locator("#session-record-next").click();
  await expect(page.locator("#session-record-page")).toContainText(
    "Page 2 of 2",
  );
  await expect(page.locator("#session-records-table")).toContainText(
    "=formula",
  );
  await page.locator("#session-close").click();
  await expect(page.locator("#session-detail")).toBeHidden();
  await expect(page).not.toHaveURL(/session=\d/);
  await page.locator("#sessions-table [data-entity-key]").click();
  await expect(page.locator("#detail")).toBeVisible();
});

test("mobile empty results, invalid linked options and record failures stay recoverable", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await unlockSessions(
    page,
    "&session_gap=0&session_min=NaN&session_order=bad",
  );
  await expect(page.locator("#session-gap")).toHaveValue("30");
  await expect(page.locator("#session-minimum")).toHaveValue("1");
  await apply(page, "60", "3");
  await expect(page.locator("#sessions-table")).toContainText(
    "No recorded results",
  );
  await expect(page.locator("#session-metrics strong").first()).toHaveText("0");
  await expect(page.locator("#session-metrics strong").last()).toHaveText("—");
  await expect(page.locator("#session-coverage")).toContainText(
    "781 plays are below",
  );
  await apply(page, "60", "2");
  await page.route("**/sessions/*/records?**", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "temporarily unavailable" }),
    }),
  );
  await page.locator("#sessions-table [data-session]").click();
  await expect(page.locator("#session-record-status")).toContainText(
    "unavailable",
  );
  await expect(page.locator('[data-session-export="records"]')).toBeDisabled();
  await page.unroute("**/sessions/*/records?**");
  await page.locator("#sessions-table [data-session]").click();
  await expect(page.locator("#session-records-table tbody tr")).toHaveCount(2);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: test.info().outputPath("sessions-mobile.png"),
    fullPage: true,
  });
});

test("locking during a delayed record read clears session rows and discards its response", async ({
  page,
}) => {
  await unlockSessions(page);
  await apply(page, "60", "2");
  await page.route("**/sessions/*/records?**", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 500));
    await route.continue();
  });
  await page.locator("#sessions-table [data-session]").click();
  await page.getByRole("button", { name: "Lock", exact: true }).click();
  await expect(page.locator("#workspace")).toBeHidden();
  await page.waitForTimeout(700);
  await expect(page.locator("#session-records-table")).toBeEmpty();
  await expect(page.locator("#sessions-table")).toBeEmpty();
  expect(await page.evaluate(() => localStorage.getItem("sm_pw"))).toBeNull();
});

test("immediate and settled PNGs agree even when motion is allowed", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await unlockSessions(page);
  await apply(page, "60", "2");
  const first = await download(
    page,
    '[data-session-export="sizes"]',
    "immediate.png",
  );
  // A later export must not reveal a different bar height after animation settles.
  await page.waitForTimeout(600);
  const later = await download(
    page,
    '[data-session-export="sizes"]',
    "settled.png",
  );
  expect(await readFile(first)).toEqual(await readFile(later));
});
