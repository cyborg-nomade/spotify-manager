import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";

test.use({ reducedMotion: "reduce" });

async function openQuilt(page) {
  await page.goto("/lastfm");
  await page
    .getByLabel("App password", { exact: true })
    .fill("browser-test-password");
  await page.getByRole("button", { name: "Unlock explorer" }).click();
  await expect(page.locator("#metric-plays")).not.toHaveText("—");
  await page.getByRole("button", { name: "All time", exact: true }).click();
  await expect(page.locator("#metric-plays")).toHaveText("781");
  await page.getByRole("button", { name: "Album quilt", exact: true }).click();
  await expect(page.locator("#workspace")).toHaveAttribute(
    "aria-busy",
    "false",
  );
  await expect(page.locator("#quilt-grid .quilt-tile")).toHaveCount(16);
  await expect(page.locator("#quilt-images")).toContainText("placeholders");
}

async function png(page) {
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download album quilt PNG" }).click();
  const file = await download;
  await file.saveAs(test.info().outputPath("quilt-export.png"));
  const bytes = await readFile(await file.path());
  expect(bytes.subarray(0, 8).toString("hex")).toBe("89504e470d0a1a0a");
  expect(bytes.readUInt32BE(16)).toBeGreaterThan(700);
  expect(bytes.length).toBeGreaterThan(2000);
}

test("quilt ranks, captions, album history, explicit fetch and exports work", async ({
  page,
}) => {
  const errors = [];
  const providers = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    if (
      /musicbrainz\.org|coverartarchive\.org|archive\.org/.test(request.url())
    )
      providers.push(request.url());
  });
  await openQuilt(page);
  await expect(page.locator("#quilt-grid img")).not.toHaveCount(0);
  await expect(page.locator("#quilt-coverage")).toContainText("781 plays");
  await page.locator("#quilt-size").selectOption("49");
  await expect(page.locator("#quilt-grid .quilt-tile")).toHaveCount(42);
  await expect(page).toHaveURL(/quilt_size=49/);
  await page.locator("#quilt-grid .quilt-open").first().click();
  await expect(page.locator("#detail")).toBeVisible();
  await expect(page.locator("#detail-title")).toContainText("Record");
  await page.locator("#close-detail").click();
  await page.locator("#quilt-search").fill("Alpha");
  await page.getByRole("button", { name: "Apply quilt filters" }).click();
  await expect(page.locator("#quilt-grid .quilt-tile")).toHaveCount(7);
  await page.locator("#quilt-force").check();
  await page.locator("#quilt-batch-size").selectOption("5");
  await page.route(
    "**/lastfm/analytics/quilt/status",
    (route) => route.fulfill({ status: 503, json: { detail: "Busy" } }),
    { times: 1 },
  );
  await page.getByRole("button", { name: "Fetch public album covers" }).click();
  await expect(page.locator("#quilt-progress")).toContainText("Checking again");
  await expect(page.locator("#quilt-progress")).toContainText(
    "complete · 5/5",
    {
      timeout: 10000,
    },
  );
  await expect(page.locator("#quilt-grid .quilt-tile")).toHaveCount(7);
  await page.locator("#quilt-size").selectOption("9");
  await page.locator("#quilt-labels").uncheck();
  await expect(page.locator("#quilt-grid")).toHaveClass(/hide-captions/);
  await page.reload();
  await expect(page.locator("#quilt-grid")).toHaveClass(/hide-captions/);
  await expect(page.locator("#quilt-size")).toHaveValue("9");
  await expect(page.locator("#quilt-images")).toContainText("placeholders");
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export quilt CSV" }).click();
  const csv = await readFile(await (await download).path(), "utf8");
  expect(csv).toContain('"Metadata snapshot","c1-');
  expect(csv).toContain("Representative release");
  expect(csv).toContain('"Album/artist search","Alpha"');
  expect(csv).toContain("edition heard");
  await png(page);
  await page.locator("#quilt-labels").check();
  await page.screenshot({
    path: test.info().outputPath("quilt-desktop.png"),
    fullPage: true,
  });
  expect(providers).toEqual([]);
  expect(errors).toEqual([]);
  await page.getByRole("button", { name: "Lock", exact: true }).click();
  await expect(page.locator("#workspace")).toBeHidden();
  await expect(page.locator("#quilt-grid img")).toHaveCount(0);
});

test("mobile placeholders export safely after independent metadata expiry", async ({
  page,
}) => {
  let expired = false;
  let history = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/lastfm/analytics/status")
      history++;
  });
  await page.route("**/lastfm/analytics/quilt?*", async (route) => {
    if (!expired) {
      expired = true;
      await route.fulfill({
        status: 409,
        headers: { "X-Listening-Conflict": "covers" },
        json: { detail: "Cover fixture expired." },
      });
      return;
    }
    const response = await route.fetch();
    const body = await response.json();
    body.data.items[0].album.name =
      '<img src=x onerror="window.coverNameExecuted=true">';
    body.data.items[0].album.artist = "=untrusted";
    await route.fulfill({ response, json: body });
  });
  await page.route("**/lastfm/analytics/quilt/images/**", (route) =>
    route.fulfill({
      status: 404,
      json: { detail: "Image fixture unavailable." },
    }),
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await openQuilt(page);
  const historyBefore = history;
  await expect(page.locator("#quilt-images")).toContainText("could not load");
  await expect(page.locator("#quilt-grid img")).toHaveCount(0);
  await expect(page.locator("#quilt-grid")).toContainText("<img src=x");
  expect(await page.evaluate(() => Boolean(window.coverNameExecuted))).toBe(
    false,
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(history).toBe(historyBefore);
  await page.locator("#quilt-labels").uncheck();
  await png(page);
  await page.screenshot({
    path: test.info().outputPath("quilt-mobile.png"),
    fullPage: true,
  });
});

test("unavailable cover metadata preserves historical views and disables exports", async ({
  page,
}) => {
  await page.route("**/lastfm/analytics/quilt/status", (route) =>
    route.fulfill({
      status: 503,
      json: { detail: "Cover fixture unavailable." },
    }),
  );
  await page.goto("/lastfm");
  await page
    .getByLabel("App password", { exact: true })
    .fill("browser-test-password");
  await page.getByRole("button", { name: "Unlock explorer" }).click();
  await expect(page.locator("#metric-plays")).not.toHaveText("—");
  await page.getByRole("button", { name: "All time", exact: true }).click();
  await page.getByRole("button", { name: "Album quilt", exact: true }).click();
  await expect(page.locator("#quilt-coverage")).toContainText("unavailable");
  await expect(page.locator("#quilt-png")).toBeDisabled();
  await expect(page.locator("#quilt-csv")).toBeDisabled();
  await expect(page.locator("#metric-plays")).toHaveText("781");
  await page.getByRole("button", { name: "Overview", exact: true }).click();
  await expect(page.locator("#tab-overview canvas")).toHaveCount(3);
});
