import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";

test.use({ reducedMotion: "reduce" });

async function unlock(page) {
  await page.goto("/lastfm");
  await expect(page.locator("#login")).toBeVisible();
  await page
    .getByLabel("App password", { exact: true })
    .fill("browser-test-password");
  await page.getByRole("button", { name: "Unlock explorer" }).click();
  await expect(page.locator("#workspace")).toBeVisible();
  await expect(page.locator("#metric-plays")).not.toHaveText("—");
  await expect(page.locator("#workspace")).toHaveAttribute(
    "aria-busy",
    "false",
  );
}

async function allTime(page) {
  await page.getByRole("button", { name: "All time", exact: true }).click();
  await expect(page.locator("#metric-plays")).toHaveText("781");
  await expect(page.locator("#workspace")).toHaveAttribute(
    "aria-busy",
    "false",
  );
}

test("shell is private, charts render, and entity records paginate", async ({
  page,
}) => {
  const failures = [];
  page.on("pageerror", (error) => failures.push(error.message));
  await page.goto("/lastfm");
  await expect(page.locator("#workspace")).toBeHidden();
  const unauthorized = await page.request.get("/lastfm/analytics/status");
  expect(unauthorized.status()).toBe(401);
  await unlock(page);
  await allTime(page);
  await expect(page.locator("#tab-overview canvas")).toHaveCount(3);
  await page.screenshot({
    path: test.info().outputPath("desktop.png"),
    fullPage: true,
  });
  await page
    .locator("#rankings-table")
    .getByRole("button", { name: "Alpha", exact: true })
    .click();
  await expect(page.locator("#detail")).toBeVisible();
  await expect(page.locator("#detail-title")).toHaveText("Alpha");
  await expect(page.locator("#detail-facts")).toContainText("156");
  await expect(page.locator("#records-page")).toContainText("Page 1");
  await page.locator("#records-next").click();
  await expect(page.locator("#records-page")).toContainText("Page 2");
  await page.locator("#close-detail").click();
  await page.getByRole("button", { name: "Lock", exact: true }).click();
  await expect(page.locator("#workspace")).toBeHidden();
  expect(await page.evaluate(() => localStorage.getItem("sm_pw"))).toBeNull();
  expect(failures).toEqual([]);
});

test("taste, discovery, and forgotten favorites have accessible tables", async ({
  page,
}) => {
  const failures = [];
  page.on("pageerror", (error) => failures.push(error.message));
  await unlock(page);
  await allTime(page);
  await page
    .getByRole("button", { name: "Taste over time", exact: true })
    .click();
  await expect(page.locator("#evolution-table table")).toBeAttached();
  await expect(page.locator("#tab-taste canvas")).toHaveCount(3);
  await page.locator("#evolution-mode").selectOption("share");
  await page.locator("#grain").selectOption("week");
  await expect(page.locator("#workspace")).toHaveAttribute(
    "aria-busy",
    "false",
  );
  await page.screenshot({
    path: test.info().outputPath("taste.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Discoveries", exact: true }).click();
  await expect(page.locator("#discovery-table")).toContainText("pending");
  await expect(page.locator("#discovery-description")).toContainText(
    "complete calendar days",
  );
  await page.getByRole("button", { name: "Rediscover", exact: true }).click();
  await page.locator("#minimum-plays").fill("1");
  await page.locator("#minimum-gap").fill("30");
  await page
    .getByRole("button", { name: "Find favorites", exact: true })
    .click();
  await expect(page.locator("#rediscovery-table")).toContainText(
    "Old Favorite",
  );
  await page
    .locator("#rediscovery-table")
    .getByRole("button", { name: "Old Favorite", exact: true })
    .click();
  await expect(page.locator("#detail-title")).toHaveText("Old Favorite");
  expect(failures).toEqual([]);
});

test("dates and selected entities restore from the URL", async ({ page }) => {
  await unlock(page);
  await allTime(page);
  await page
    .locator("#rankings-table")
    .getByRole("button", { name: "Alpha", exact: true })
    .click();
  await expect(page.locator("#detail-title")).toHaveText("Alpha");
  expect(new URL(page.url()).searchParams.get("entity")).toHaveLength(64);
  await page.reload();
  await expect(page.locator("#detail-title")).toHaveText("Alpha");
  await expect(page.locator("#metric-plays")).toHaveText("781");
  await page.locator("#close-detail").click();
  await page.locator("#timezone").fill("UTC");
  await page
    .getByRole("button", { name: "Apply filters", exact: true })
    .click();
  await expect(page.locator("#selection-caption")).toContainText("UTC");
  await page.reload();
  await expect(page.locator("#timezone")).toHaveValue("UTC");
  await expect(page.locator("#metric-plays")).toHaveText("781");
});

test("calendar and rhythm selections expose their underlying records", async ({
  page,
}) => {
  await unlock(page);
  await allTime(page);
  await page.locator("#calendar-year").selectOption("2023");
  await page.getByText("Calendar data", { exact: false }).click();
  await page.locator("#calendar-table button:not([disabled])").first().click();
  await expect(page.locator("#detail")).toBeVisible();
  await expect(page.locator("#records-table table")).toBeVisible();
  await expect(page.locator("#from")).toHaveValue("2023-01-01");
  await expect(page.locator("#to")).toHaveValue("2023-01-01");
  await page.locator("#close-detail").click();
  await allTime(page);
  await page.getByText("Weekly rhythm data", { exact: true }).click();
  await page.locator("#rhythm-table button").first().click();
  await expect(page.locator("#filter-chips")).toContainText("Monday · 00:00");
  await page.getByRole("button", { name: "Discoveries", exact: true }).click();
  await expect(page.locator("#discovery-table table")).toBeVisible();
  await expect(page.locator("#filter-chips")).not.toContainText("Monday");
});

test("PNG and CSV exports include data and safe music names", async ({
  page,
}) => {
  await unlock(page);
  await allTime(page);
  const imageDownload = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download listening calendar PNG" })
    .click();
  const image = await imageDownload;
  const imageBytes = await readFile(await image.path());
  expect(imageBytes.subarray(0, 8).toString("hex")).toBe("89504e470d0a1a0a");
  expect(imageBytes.length).toBeGreaterThan(1000);
  await page.locator("#rank-search").fill("<img");
  await expect(page.locator("#rankings-table button")).toHaveCount(1);
  await expect(page.locator("#rankings-table")).toContainText("onerror");
  expect(await page.locator("#rankings-table img").count()).toBe(0);
  expect(await page.evaluate(() => window.musicNameExecuted)).toBeUndefined();
  await page.locator("#rankings-table button").click();
  await expect(page.locator("#records-table")).toContainText("=formula");
  const csvDownload = page.waitForEvent("download");
  await page.locator('#detail [data-csv="records"]').click();
  const csv = await readFile(await (await csvDownload).path(), "utf8");
  expect(csv).toContain("Source snapshot");
  expect(csv).toContain("Europe/Berlin");
  expect(csv).toContain("'=formula");
});

test("mobile layout fits and keyboard login works", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/lastfm");
  await expect(page.locator("#login")).toBeVisible();
  await page.getByLabel("App password", { exact: true }).focus();
  await page.keyboard.type("browser-test-password");
  await page.keyboard.press("Enter");
  await expect(page.locator("#metric-plays")).not.toHaveText("—");
  await expect(page.locator("#workspace")).toHaveAttribute(
    "aria-busy",
    "false",
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: test.info().outputPath("mobile.png"),
    fullPage: true,
  });
  await page.getByText("Calendar data", { exact: false }).click();
  await expect(page.locator("#calendar-table table")).toBeVisible();
});

test("artist search applies a visible filter and racing date requests settle correctly", async ({
  page,
}) => {
  await unlock(page);
  await allTime(page);
  await page.locator("#artist-search").fill("bé");
  await page
    .locator("#artist-results")
    .getByRole("button", { name: /Béta/ })
    .click();
  await expect(page.locator("#filter-chips")).toContainText("Béta");
  await expect(page.locator("#metric-artists")).toHaveText("1");
  await page.getByRole("button", { name: /Artist: Béta/ }).click();
  await expect(page.locator("#metric-plays")).toHaveText("781");
  await page.route("**/lastfm/analytics/overview?**", async (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get("from")?.endsWith("01-20"))
      await new Promise((resolve) => setTimeout(resolve, 300));
    await route.continue();
  });
  await page.getByRole("button", { name: "30 days", exact: true }).click();
  await page.getByRole("button", { name: "90 days", exact: true }).click();
  await expect(page.locator("#workspace")).toHaveAttribute(
    "aria-busy",
    "false",
  );
  const current = new URL(page.url());
  const response = await page.request.get("/lastfm/analytics/overview", {
    headers: { "X-App-Password": "browser-test-password" },
    params: {
      from: current.searchParams.get("from"),
      to: current.searchParams.get("to"),
      tz: current.searchParams.get("tz"),
      snapshot: await page.evaluate(
        () =>
          document
            .getElementById("source-footnote")
            .textContent.match(/v1-[a-f0-9]{64}/)[0],
      ),
    },
  });
  const expected = (await response.json()).data.counts.scrobbles;
  await expect(page.locator("#metric-plays")).toHaveText(
    new Intl.NumberFormat().format(expected),
  );
  expect(current.searchParams.get("preset")).toBe("90");
});

test("time capsule restores its reference, exports both views, and opens anniversary records", async ({
  page,
}) => {
  const failures = [];
  page.on("pageerror", (error) => failures.push(error.message));
  await unlock(page);
  await allTime(page);
  await page.getByRole("button", { name: "Time capsule", exact: true }).click();
  await expect(page.locator("#tab-capsule canvas")).toHaveCount(2);
  expect(
    (await page.locator("#anniversaries-chart").boundingBox()).height,
  ).toBeGreaterThan(200);
  expect(
    (await page.locator("#eras-chart").boundingBox()).height,
  ).toBeGreaterThan(400);
  await expect(page.locator("#eras-table table")).toBeVisible();
  await expect(page.locator("#anniversary-description")).toContainText(
    "earlier years",
  );
  await page.locator("#era-reference").selectOption("2024-02");
  await expect(page.locator("#era-comparison")).toContainText("2024-02");
  await page.reload();
  await expect(page.locator("#era-reference")).toHaveValue("2024-02");
  await expect(page.locator("#workspace")).toHaveAttribute(
    "aria-busy",
    "false",
  );
  const matrixDownload = page.waitForEvent("download");
  await page.locator('[data-csv="eras"]').click();
  const matrix = await readFile(await (await matrixDownload).path(), "utf8");
  expect(matrix).toContain("Source snapshot");
  expect(matrix).toContain("2024-02");
  expect(matrix).toContain("Partial period");
  const anniversaryDownload = page.waitForEvent("download");
  await page.locator('[data-csv="anniversaries"]').click();
  const anniversaries = await readFile(
    await (await anniversaryDownload).path(),
    "utf8",
  );
  expect(anniversaries).toContain("Anniversary as of");
  expect(anniversaries).toContain("Observed from");
  const pngDownload = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download Musical Eras PNG" }).click();
  const bytes = await readFile(await (await pngDownload).path());
  expect(bytes.subarray(0, 8).toString("hex")).toBe("89504e470d0a1a0a");
  await page.locator("#eras-chart").scrollIntoViewIfNeeded();
  const point = await page
    .locator("#eras-chart")
    .evaluate((node) =>
      window.echarts
        .getInstanceByDom(node)
        .convertToPixel({ seriesIndex: 0 }, [0, 1]),
    );
  const rectangle = await page.locator("#eras-chart").boundingBox();
  await page.mouse.click(rectangle.x + point[0], rectangle.y + point[1]);
  await expect(page.locator("#era-comparison")).toContainText("↔");
  await page.screenshot({
    path: test.info().outputPath("time-capsule.png"),
    fullPage: true,
  });
  await page
    .locator("#anniversary-table button:not([disabled])")
    .first()
    .click();
  await expect(page.locator("#detail")).toBeVisible();
  await expect(page.locator("#records-table table")).toBeVisible();
  await expect(page.locator('[data-tab="overview"]')).toHaveAttribute(
    "aria-current",
    "page",
  );
  expect(failures).toEqual([]);
});

test("time capsule handles long and empty ranges, safe names, and mobile period navigation", async ({
  page,
}) => {
  await unlock(page);
  await page.getByRole("button", { name: "Time capsule", exact: true }).click();
  await page.locator("#from").fill("1950-01-01");
  await page.locator("#to").fill("2025-12-01");
  await page
    .getByRole("button", { name: "Apply filters", exact: true })
    .click();
  await expect(page.locator("#eras-description")).toContainText("yearly");
  await expect(page.locator("#eras-table")).toContainText("Not comparable");
  await expect(page.locator("#anniversary-table")).toContainText("onerror");
  expect(await page.locator("#anniversary-table img").count()).toBe(0);
  expect(await page.evaluate(() => window.musicNameExecuted)).toBeUndefined();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: test.info().outputPath("time-capsule-mobile.png"),
    fullPage: true,
  });
  await page.locator("#eras-table button:not([disabled])").first().click();
  await expect(page.locator("#detail")).toBeVisible();
  await expect(page.locator("#from")).toHaveValue("2023-01-01");
  await expect(page.locator("#to")).toHaveValue("2023-12-31");
  await page.locator("#close-detail").click();
  await page.getByRole("button", { name: "Time capsule", exact: true }).click();
  await page.locator("#from").fill("2000-01-01");
  await page.locator("#to").fill("2000-01-31");
  await page
    .getByRole("button", { name: "Apply filters", exact: true })
    .click();
  await expect(page.locator("#eras-table")).toContainText("Not comparable");
  await expect(page.locator("#anniversary-table button")).toHaveCount(0);
});
