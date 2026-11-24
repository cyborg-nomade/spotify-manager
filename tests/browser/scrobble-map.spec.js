import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";

test.use({ reducedMotion: "reduce" });

async function openMap(page, selection) {
  await page.goto(`/lastfm?tab=scrobble-map&tz=UTC&${selection}`);
  await page
    .getByLabel("App password", { exact: true })
    .fill("browser-test-password");
  await page.getByRole("button", { name: "Unlock explorer" }).click();
  await expect(page.locator("#scrobble-map-chart canvas")).toHaveCount(1);
}

async function download(page, label) {
  const saved = page.waitForEvent("download");
  await page.getByRole("button", { name: label, exact: true }).click();
  return readFile(await (await saved).path());
}

test("the density cell and its keyboard equivalent open the same scoped records", async ({
  page,
}) => {
  await openMap(page, "from=2023-01-01&to=2023-01-08");
  await expect(page.locator("#scrobble-map-summary")).toContainText(
    "8 recorded plays · 8 day columns · UTC",
  );
  const chart = page.locator("#scrobble-map-chart");
  await chart.scrollIntoViewIfNeeded();
  const pixel = await chart.evaluate((node) =>
    window.echarts
      .getInstanceByDom(node)
      .convertToPixel({ seriesIndex: 0 }, [0, 12]),
  );
  const box = await chart.boundingBox();
  await page.mouse.click(box.x + pixel[0], box.y + pixel[1]);
  await expect(page.locator("#detail-description")).toHaveText(
    "2023-01-01 · 12:00 local hour · UTC",
  );
  await expect(page.locator("#records-page")).toContainText("1 results");
  const scoped = (await download(page, "Export page CSV")).toString("utf8");
  expect(scoped).toContain('"Hour filter","12"');
  expect(scoped).toContain('"From","2023-01-01"');
  expect(scoped).toContain('"Through","2023-01-01"');
  await page.locator("#close-detail").click();

  await page
    .getByText("Browse hours and recorded plays", { exact: true })
    .click();
  await page.getByLabel("Date period").selectOption({ label: "2023-01-02" });
  await page
    .getByRole("button", { name: "View 1 recorded plays at 13:00" })
    .press("Enter");
  await expect(page.locator("#detail-description")).toHaveText(
    "2023-01-02 · 13:00 local hour · UTC",
  );
  await expect(page.locator("#records-page")).toContainText("1 results");
  await page.locator("#close-detail").click();

  await page.getByLabel("Individual plays").check();
  const series = await chart.evaluate(
    (node) => window.echarts.getInstanceByDom(node).getOption().series[0],
  );
  expect(series.type).toBe("scatter");
  expect(series.data).toHaveLength(8);
  const csv = (await download(page, "Export map CSV")).toString("utf8");
  expect(csv).toContain('"Scope","One row per recorded play"');
  expect(csv).toContain(
    '"2023-01-01","12:00:00.000","2023-01-01T12:00:00.000Z"',
  );
  const png = await download(page, "Download scrobble map PNG");
  expect(png.subarray(0, 8).toString("hex")).toBe("89504e470d0a1a0a");
});

test("wide selections keep an exact density map on mobile", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openMap(page, "preset=all");
  await expect(page.locator("#scrobble-map-summary")).toContainText(
    "781 recorded plays",
  );
  await expect(page.getByLabel("Individual plays")).toBeDisabled();
  const data = await page
    .locator("#scrobble-map-chart")
    .evaluate(
      (node) =>
        window.echarts.getInstanceByDom(node).getOption().series[0].data,
    );
  expect(data.reduce((sum, cell) => sum + cell[2], 0)).toBe(781);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: test.info().outputPath("scrobble-map-mobile.png"),
    fullPage: true,
  });
});
