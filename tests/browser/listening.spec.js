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
  await expect(page.locator("#workspace")).toHaveAttribute(
    "aria-busy",
    "false",
  );
  await page.locator("#minimum-plays").fill("1");
  await page.locator("#minimum-gap").fill("30");
  const favorites = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      url.pathname === "/lastfm/analytics/rediscovery" &&
      url.searchParams.get("minimum_plays") === "1" &&
      url.searchParams.get("minimum_gap") === "30"
    );
  });
  await page
    .getByRole("button", { name: "Find favorites", exact: true })
    .click();
  expect((await favorites).ok()).toBe(true);
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
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    )
    .toBe(true);
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

test("era bands, grouped coordinates and highlighting preserve scores across reload and export", async ({
  page,
}) => {
  await unlock(page);
  await allTime(page);
  const labels = ["2023-01", "2023-02", "2023-03", "2023-04", "2023-05"];
  const matrix = [
    [1, 0.03, 0.2, 0.01, null],
    [0.03, 1, 0.02, 0.35, null],
    [0.2, 0.02, 1, 0.05, null],
    [0.01, 0.35, 0.05, 1, null],
    [null, null, null, null, null],
  ];
  let eraRequests = 0;
  await page.route("**/lastfm/analytics/eras?**", async (route) => {
    eraRequests++;
    const response = await route.fetch();
    const body = await response.json();
    body.data = {
      grain: "month",
      periods: labels.map((label, index) => ({
        label,
        start: label + "-01",
        end: label + "-28",
        plays: index === 4 ? 0 : 10,
        artists: index === 4 ? 0 : 2,
        covered: true,
        partial: false,
      })),
      similarities: matrix,
    };
    await route.fulfill({ response, json: body });
  });
  await page.getByRole("button", { name: "Time capsule", exact: true }).click();
  await expect(page.locator("#eras-table table")).toBeVisible();
  await page.getByLabel("Group similar periods", { exact: true }).check();
  const rendered = await page.locator("#eras-chart").evaluate((node) => {
    const chart = window.echarts.getInstanceByDom(node),
      options = chart.getOption();
    const index = options.series[0].data.findIndex(
      (item) => item.originalRow === 0 && item.originalColumn === 1,
    );
    return {
      labels: options.xAxis[0].data,
      type: options.visualMap[0].type,
      pieces: options.visualMap[0].pieces.map((piece) => piece.label),
      color: chart.getVisual({ seriesIndex: 0, dataIndex: index }, "color"),
      diagonal: chart.getVisual({ seriesIndex: 1, dataIndex: 0 }, "color"),
    };
  });
  expect(rendered.labels).toEqual([
    "2023-01",
    "2023-03",
    "2023-02",
    "2023-04",
    "2023-05",
  ]);
  expect(rendered.type).toBe("piecewise");
  expect(rendered.pieces).toEqual([
    "<2%",
    "2–5%",
    "5–10%",
    "10–20%",
    "20–35%",
    "≥35%",
  ]);
  expect(rendered.color).toBe("#426fa3");
  expect(rendered.diagonal).toBe("#727981");
  await page.locator("#era-threshold").focus();
  await page.keyboard.press("End");
  await expect(page.locator("#era-threshold-value")).toHaveText("100%");
  const opacity = await page.locator("#eras-chart").evaluate((node) => {
    const chart = window.echarts.getInstanceByDom(node);
    return {
      comparison: chart
        .getModel()
        .getSeriesByIndex(0)
        .getData()
        .getItemVisual(0, "style").opacity,
      self: chart
        .getModel()
        .getSeriesByIndex(1)
        .getData()
        .getItemVisual(0, "style").opacity,
    };
  });
  expect(opacity).toEqual({ comparison: 0.16, self: 1 });
  expect(eraRequests).toBe(1);
  await expect(page.locator("#eras-table")).toContainText(
    "Below highlight threshold",
  );
  const point = await page
    .locator("#eras-chart")
    .evaluate((node) =>
      window.echarts
        .getInstanceByDom(node)
        .convertToPixel({ seriesIndex: 0 }, [2, 0]),
    );
  await page.locator("#eras-chart").scrollIntoViewIfNeeded();
  const rectangle = await page.locator("#eras-chart").boundingBox();
  await page.mouse.click(rectangle.x + point[0], rectangle.y + point[1]);
  await expect(page.locator("#era-comparison")).toContainText(
    "2023-02 ↔ 2023-01: 3.0%",
  );
  await expect(page.locator("#era-reference")).toHaveValue("2023-02");
  const download = page.waitForEvent("download");
  await page.locator('[data-csv="eras"]').click();
  const csv = await readFile(await (await download).path(), "utf8");
  expect(csv).toContain(
    '"Period ordering","Grouped by similarity (average linkage)"',
  );
  expect(csv).toContain('"Highlight minimum (%)","100"');
  const row = csv.split("\r\n").find((line) => line.startsWith('"2023-01",'));
  expect(row.split(",").slice(7)).toEqual([
    '"1"',
    '"0.2"',
    '"0.03"',
    '"0.01"',
    '"Not comparable"',
  ]);
  await page.reload();
  await expect(page.locator("#era-grouped")).toBeChecked();
  await expect(page.locator("#era-threshold")).toHaveValue("100");
  await expect(page.locator("#era-reference")).toHaveValue("2023-02");
  await expect(page.locator("#eras-table button").last()).toHaveText("2023-05");
  await expect(page.locator("#eras-table button").last()).toBeEnabled();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    )
    .toBe(true);
  await page.screenshot({
    path: test.info().outputPath("grouped-eras-mobile.png"),
    fullPage: true,
  });
  await page.getByLabel("Group similar periods", { exact: true }).uncheck();
  expect(new URL(page.url()).searchParams.get("era_order")).toBe(
    "chronological",
  );
  expect(await page.locator("#eras-table button").allTextContents()).toEqual(
    labels,
  );
  const fractional = new URL(page.url());
  fractional.searchParams.set("era_min", "3.6");
  await page.goto(fractional.href);
  await expect(page.locator("#era-threshold")).toHaveValue("4");
  await expect(page.locator("#era-threshold-value")).toHaveText("4%");
});

test("a warm older asset cache cannot disable the new era controls", async ({
  page,
  context,
  baseURL,
}) => {
  await context.addCookies([
    { name: "legacy_assets", value: "1", url: baseURL },
  ]);
  await page.goto("/lastfm?legacy=1");
  await page.waitForFunction(
    () =>
      window.legacyExplorer &&
      window.legacyCharts &&
      window.legacyTables &&
      window.legacyEras,
  );
  await context.clearCookies();
  await page.goto("/lastfm?legacy=1&visit=2");
  // The server now serves current files at these URLs. Old markers prove the
  // browser still has the earlier, explicitly cacheable module graph.
  await page.waitForFunction(
    () =>
      window.legacyExplorer &&
      window.legacyCharts &&
      window.legacyTables &&
      window.legacyEras,
  );
  await unlock(page);
  await allTime(page);
  await page.getByRole("button", { name: "Time capsule", exact: true }).click();
  await expect(page.locator("#eras-table table")).toBeVisible();
  expect(
    await page.evaluate(() => [
      window.legacyExplorer,
      window.legacyCharts,
      window.legacyTables,
      window.legacyEras,
    ]),
  ).toEqual([undefined, undefined, undefined, undefined]);
  expect(
    await page
      .locator(".era-controls")
      .evaluate((node) => getComputedStyle(node).pointerEvents),
  ).toBe("auto");
  await page.getByLabel("Group similar periods", { exact: true }).check();
  await expect(page.locator("#era-view-description")).toContainText(
    "Periods are grouped",
  );
  expect(new URL(page.url()).searchParams.get("era_order")).toBe("grouped");
  await page.locator("#era-threshold").focus();
  await page.keyboard.press("End");
  await expect(page.locator("#era-threshold-value")).toHaveText("100%");
  expect(new URL(page.url()).searchParams.get("era_min")).toBe("100");
  expect(
    await page
      .locator("#eras-chart")
      .evaluate(
        (node) =>
          window.echarts.getInstanceByDom(node).getOption().visualMap[0].type,
      ),
  ).toBe("piecewise");
  await expect(page.locator("#eras-table")).toContainText(
    "Below highlight threshold",
  );
});

test("library bridge keeps name evidence, source dates, CSV and history navigation", async ({
  page,
}) => {
  const failures = [];
  page.on("pageerror", (error) => failures.push(error.message));
  await unlock(page);
  await allTime(page);
  await page
    .getByRole("button", { name: "Library bridge", exact: true })
    .click();
  await expect(page.locator("#library-table table")).toBeAttached();
  await expect(page.locator("#library-source")).toContainText(
    "Saved albums · ready",
  );
  await expect(page.locator("#library-source")).toContainText("published");
  await expect(page.locator("#library-chart canvas")).toHaveCount(1);
  const libraryBounds = await page.locator("#library-chart").boundingBox();
  expect(libraryBounds.height).toBeGreaterThan(200);
  await page.screenshot({
    path: test.info().outputPath("library-bridge.png"),
    fullPage: true,
  });
  await expect(page.locator("#library-table")).toContainText(
    "One exact name candidate",
  );
  await expect(page.locator("#library-table")).toContainText(
    "Multiple name candidates",
  );
  await page.locator("#library-status").selectOption("ambiguous");
  await page
    .locator("#library-filters")
    .getByRole("button", { name: "Apply", exact: true })
    .click();
  await expect(page.locator("#library-table")).not.toContainText(
    "No exact name match",
  );
  await expect(page.locator("#library-table a")).toHaveCount(2);
  await expect(page).toHaveURL(/library_status=ambiguous/);
  await page.locator("#library-kind").selectOption("track");
  const downloading = page.waitForEvent("download");
  await page.locator("#library-export").click();
  const downloaded = await downloading;
  const csv = await readFile(await downloaded.path(), "utf8");
  expect(csv).toContain('"Collection","Saved albums"');
  await page.locator("#library-kind").selectOption("album");
  expect(csv).toContain("Library snapshot");
  expect(csv).toContain("Current page 1");
  expect(csv).toContain("ambiguous");
  expect(csv).toContain("spotify:album:");
  await page.reload();
  await expect(page.locator("#library-status")).toHaveValue("ambiguous");
  await expect(page.locator("#library-table table")).toBeAttached();
  await page
    .locator("#library-table")
    .getByRole("button", { name: "Record 2", exact: false })
    .first()
    .click();
  await expect(page.locator("#detail")).toBeVisible();
  await expect(page.locator("#detail-title")).toHaveText("Record 2");
  await page.locator("#close-detail").click();
  await page.locator("#library-kind").selectOption("artist");
  await page.locator("#library-status").selectOption("all");
  await page
    .locator("#library-filters")
    .getByRole("button", { name: "Apply", exact: true })
    .click();
  await expect(page.locator("#library-source")).toContainText(
    "Followed artists · missing",
  );
  await expect(page.locator("#library-table")).toContainText(
    "Collection unavailable",
  );
  await page.locator("#library-kind").selectOption("track");
  await page.locator("#library-status").selectOption("name_match");
  await page
    .locator("#library-filters")
    .getByRole("button", { name: "Apply", exact: true })
    .click();
  await expect(page.locator("#library-table")).toContainText("=formula");
  expect(await page.evaluate(() => window.musicNameExecuted)).toBeUndefined();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    )
    .toBe(true);
  expect(failures).toEqual([]);
});

test("unavailable collection service preserves history and can recover", async ({
  page,
}) => {
  await unlock(page);
  await allTime(page);
  await page.route("**/lastfm/analytics/library/status*", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Collection service unavailable" }),
    }),
  );
  await page
    .getByRole("button", { name: "Library bridge", exact: true })
    .click();
  await expect(page.locator("#library-message")).toContainText(
    "Your listening history is still available",
  );
  await expect(page.locator("#metric-plays")).toHaveText("781");
  await expect(page.locator("#library-export")).toBeDisabled();
  await page.unroute("**/lastfm/analytics/library/status*");
  await page.locator("#library-refresh").click();
  await expect(page.locator("#library-table table")).toBeAttached();
});

test("tag atlas reconciles coverage, exports applied metadata and fetches only on request", async ({
  page,
}) => {
  const failures = [];
  page.on("pageerror", (error) => failures.push(error.message));
  await unlock(page);
  await allTime(page);
  await page
    .getByRole("button", { name: "Tags & genres", exact: true })
    .click();
  await expect(page.locator("#tag-coverage")).toContainText("312 of 781");
  await expect(page.locator("#tag-progress")).toContainText("idle");
  await expect(page.locator("#tags-chart canvas")).toHaveCount(1);
  expect(
    (await page.locator("#tags-chart").boundingBox()).height,
  ).toBeGreaterThan(200);
  await page.screenshot({
    path: test.info().outputPath("tag-atlas.png"),
    fullPage: true,
  });
  await page.locator("#tag-per-artist").selectOption("1");
  await page
    .getByRole("button", { name: "Apply tag filters", exact: true })
    .click();
  await expect(page).toHaveURL(/tags_per_artist=1/);
  await expect(page.locator("#workspace")).toHaveAttribute(
    "aria-busy",
    "false",
  );
  await page.locator("#tag-filter").selectOption("unknown");
  await page
    .getByRole("button", { name: "Apply tag filters", exact: true })
    .click();
  await expect(page.locator("#tag-artists-table")).toContainText(
    "Looked up · no tags",
  );
  await expect(page.locator("#tag-artists-table")).not.toContainText(
    "Available tags",
  );
  const downloading = page.waitForEvent("download");
  await page.getByText("Monthly allocation table", { exact: true }).click();
  await page.locator('[data-csv="tags"]').click();
  const csv = await readFile(await (await downloading).path(), "utf8");
  expect(csv).toContain("Metadata snapshot");
  expect(csv).toContain("Leading tag per artist");
  expect(csv).toContain("Unknown / no tags");
  await page.reload();
  await expect(page.locator("#tag-per-artist")).toHaveValue("1");
  await expect(page.locator("#tag-filter")).toHaveValue("unknown");
  await expect(page.locator("#tag-artists-table table")).toBeAttached();
  await page.locator("#tag-fetch").click();
  await expect(page.locator("#tag-progress")).toContainText("complete", {
    timeout: 15000,
  });
  await expect(page.locator("#tag-coverage")).toContainText("625 of 781");
  await page.locator("#tag-filter").selectOption("");
  await page
    .getByRole("button", { name: "Apply tag filters", exact: true })
    .click();
  await expect(page.locator("#tag-artists-table")).toContainText("onerror");
  expect(await page.locator("#tag-artists-table img").count()).toBe(0);
  expect(await page.evaluate(() => window.musicNameExecuted)).toBeUndefined();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    )
    .toBe(true);
  expect(failures).toEqual([]);
});

test("tag metadata expiry retries independently and outage preserves historical totals", async ({
  page,
}) => {
  await unlock(page);
  await allTime(page);
  let rejected = false;
  await page.route("**/lastfm/analytics/tags?*", async (route) => {
    if (!rejected) {
      rejected = true;
      await route.fulfill({
        status: 409,
        headers: { "X-Listening-Conflict": "tags" },
        contentType: "application/json",
        body: JSON.stringify({ detail: "Tag metadata version expired." }),
      });
    } else await route.continue();
  });
  await page
    .getByRole("button", { name: "Tags & genres", exact: true })
    .click();
  await expect(page.locator("#tag-artists-table table")).toBeAttached();
  await expect(page.locator("#metric-plays")).toHaveText("781");
  await page.unroute("**/lastfm/analytics/tags?*");
  await page.route("**/lastfm/analytics/tags/status", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Cache unavailable" }),
    }),
  );
  await page
    .getByRole("button", { name: "Apply tag filters", exact: true })
    .click();
  await expect(page.locator("#tag-progress")).toContainText(
    "listening history remains available",
  );
  await expect(page.locator("#metric-plays")).toHaveText("781");
  await expect(page.locator('[data-csv="tags"]')).toBeDisabled();
});

test("artist atlas maps only single-country evidence and keeps source-aware exports and controls", async ({
  page,
}) => {
  const failures = [];
  page.on("pageerror", (error) => failures.push(error.message));
  await unlock(page);
  await allTime(page);
  await page.getByRole("button", { name: "Artist map", exact: true }).click();
  await expect(page.locator("#origin-coverage")).toContainText("313 of 781");
  await expect(page.locator("#origins-chart canvas")).toHaveCount(1);
  await expect(page.locator("#origin-progress")).toContainText("idle");
  await page.screenshot({
    path: test.info().outputPath("artist-atlas.png"),
    fullPage: true,
  });
  await page
    .getByRole("combobox", { name: "Map values", exact: true })
    .selectOption("artists");
  await expect(page).toHaveURL(/origin_metric=artists/);
  await page.locator("#origins-chart").scrollIntoViewIfNeeded();
  const point = await page
    .locator("#origins-chart")
    .evaluate((node) =>
      window.echarts
        .getInstanceByDom(node)
        .convertToPixel({ seriesIndex: 0 }, [-52, -10]),
    );
  const box = await page.locator("#origins-chart").boundingBox();
  await page.mouse.click(box.x + point[0], box.y + point[1]);
  await expect(page).toHaveURL(/origin_country=BR/);
  await expect(page.locator("#origin-artists-table")).toContainText("Alpha");
  await expect(page.locator("#origin-artists-table")).not.toContainText("Béta");
  await page
    .getByRole("combobox", { name: "Country evidence", exact: true })
    .selectOption("");
  await page
    .getByRole("combobox", { name: "Artist evidence", exact: true })
    .selectOption("ambiguous");
  await page
    .getByRole("button", { name: "Apply map filters", exact: true })
    .click();
  await expect(page.locator("#origin-artists-table")).toContainText("Delta");
  await expect(page.locator("#origin-artists-table")).toContainText(
    "Multiple name candidates",
  );
  const downloading = page.waitForEvent("download");
  await page
    .getByRole("button", {
      name: "Export country artist page CSV",
      exact: true,
    })
    .click();
  const csv = await readFile(await (await downloading).path(), "utf8");
  expect(csv).toContain("MusicBrainz exact-name artist search");
  expect(csv).toContain("ambiguous");
  expect(csv).toContain("o1-");
  expect(csv).toContain("Current page 1; 1 matching artists");
  await page.reload();
  await expect(page.locator("#origin-artists-table")).toContainText("Delta");
  await expect(
    page.getByRole("combobox", { name: "Map values", exact: true }),
  ).toHaveValue("artists");
  await page
    .getByRole("combobox", { name: "Artist evidence", exact: true })
    .selectOption("all");
  await page
    .getByRole("button", { name: "Apply map filters", exact: true })
    .click();
  const link = page.locator("#origin-artists-table a").first();
  await expect(link).toHaveAttribute(
    "href",
    /^https:\/\/musicbrainz\.org\/artist\/[a-f0-9-]{36}$/,
  );
  await page.route(
    "**/lastfm/analytics/origins/status",
    (route) => route.fulfill({ status: 503, json: { detail: "Busy" } }),
    { times: 1 },
  );
  await page
    .getByRole("button", { name: "Load all missing artists", exact: true })
    .click();
  await expect(page.locator("#origin-progress")).toContainText(
    "Checking again",
  );
  await expect(page.locator("#origin-progress")).toContainText("complete", {
    timeout: 10000,
  });
  await expect(page.locator("#origin-coverage")).toContainText("339 of 781");
  await page.getByRole("button", { name: "Alpha", exact: true }).click();
  await expect(page.locator("#detail")).toBeVisible();
  await page.locator("#close-detail").click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    )
    .toBe(true);
  const ratio = await page.locator("#origins-chart").evaluate((node) => {
    const chart = window.echarts.getInstanceByDom(node);
    const a = chart.convertToPixel({ seriesIndex: 0 }, [-52, -10]);
    const b = chart.convertToPixel({ seriesIndex: 0 }, [-51, -9]);
    return Math.abs((b[0] - a[0]) / (b[1] - a[1]));
  });
  expect(ratio).toBeCloseTo(1, 4);
  expect(await page.evaluate(() => window.musicNameExecuted)).toBeUndefined();
  expect(failures).toEqual([]);
});

test("artist metadata expiry and missing map outlines preserve history and table evidence", async ({
  page,
}) => {
  await page.route("**/lastfm/assets/world-110m-v1.geojson", (route) =>
    route.fulfill({ status: 503, body: "unavailable" }),
  );
  let expired = false;
  await page.route("**/lastfm/analytics/origins?*", async (route) => {
    if (!expired) {
      expired = true;
      await route.fulfill({
        status: 409,
        headers: { "X-Listening-Conflict": "origins" },
        contentType: "application/json",
        body: JSON.stringify({ detail: "Expired country metadata" }),
      });
      return;
    }
    await route.continue();
  });
  await unlock(page);
  await allTime(page);
  await page.getByRole("button", { name: "Artist map", exact: true }).click();
  await expect(page.locator("#origin-coverage")).toContainText("of 781");
  await expect(page.locator("#origins-chart")).toContainText(
    "Map outlines are unavailable",
  );
  await expect(
    page.getByRole("button", { name: "Download artist map PNG", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", {
      name: "Export all country counts CSV",
      exact: true,
    }),
  ).toBeEnabled();
  await expect(page.locator("#metric-plays")).toHaveText("781");
  await page.route("**/lastfm/analytics/origins/status", (route) =>
    route.fulfill({ status: 503, body: "unavailable" }),
  );
  await page
    .getByRole("button", { name: "Apply map filters", exact: true })
    .click();
  await expect(page.locator("#origin-coverage")).toContainText(
    "metadata unavailable",
  );
  await expect(page.locator("#metric-plays")).toHaveText("781");
  await expect(
    page.getByRole("button", {
      name: "Export all country counts CSV",
      exact: true,
    }),
  ).toBeDisabled();
});
