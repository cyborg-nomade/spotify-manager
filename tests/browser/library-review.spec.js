import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";

async function openBridge(page, filter) {
  const query = new URLSearchParams({
    tab: "library",
    preset: "all",
    ...filter,
  });
  await page.goto(`/lastfm?${query}`);
  await page
    .getByLabel("App password", { exact: true })
    .fill("browser-test-password");
  await page.getByRole("button", { name: "Unlock explorer" }).click();
  await expect(page.locator("#library-table table")).toBeAttached();
}

async function exportRow(page, name) {
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export current page CSV" }).click();
  const csv = await readFile(await (await download).path(), "utf8");
  expect(csv).toContain('"Reviewed Spotify URI","Reviewed at (UTC)"');
  return csv.split("\r\n").find((row) => row.includes(`,"${name}",`));
}

test("a confirmed choice survives reload and expires when the publication changes", async ({
  page,
}) => {
  await openBridge(page, { library_status: "ambiguous" });
  const table = page.locator("#library-table");
  const editor = page.getByRole("dialog", { name: "Review Spotify match" });
  const uri = "spotify:album:" + "b".repeat(22);
  const mutations = [];
  page.on("request", (request) => {
    if (
      request.url().includes("/analytics/library") &&
      request.method() !== "GET"
    )
      mutations.push(request.method());
  });
  await table
    .getByRole("button", { name: "Review match for Record 2" })
    .click();
  await expect(editor).toContainText("Recorded as Record 2 · Delta");
  await expect(editor).toContainText("2 candidates");
  const candidate = editor.getByRole("row").filter({ hasText: uri });
  await expect(candidate).toContainText("Exact name");
  await candidate
    .getByRole("button", { name: "Confirm match for Record 2" })
    .click();
  await expect(editor.locator("#library-review-saved")).toContainText(
    "Match confirmed in this browser",
  );
  await editor.getByRole("button", { name: "Close match review" }).click();
  await expect(
    table.getByRole("link", { name: "Confirmed match" }),
  ).toHaveAttribute("href", `https://open.spotify.com/album/${"b".repeat(22)}`);
  await expect(table).toContainText("Multiple name candidates");
  expect(await exportRow(page, "Record 2")).toMatch(
    new RegExp(`,"${uri}","[0-9]`),
  );
  await page.reload();
  await expect(
    table.getByRole("link", { name: "Confirmed match" }),
  ).toBeVisible();
  await table
    .getByRole("button", { name: "Review match for Record 2" })
    .click();
  await expect(
    editor.getByRole("button", { name: "Confirmed for Record 2" }),
  ).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(editor).toBeHidden();

  await page.route("**/lastfm/analytics/library?*", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.data.library_snapshot = "l1-" + "0".repeat(64);
    await route.fulfill({ response, json: body });
  });
  await page.reload();
  await expect(table).toContainText("Review expired");
  expect(await exportRow(page, "Record 2")).toMatch(/,"",""$/);
  await table
    .getByRole("button", { name: "Review match for Record 2" })
    .click();
  await expect(editor).toContainText("A publication version expired");
  await expect(
    editor.getByRole("button", { name: /Confirm match for/ }),
  ).toHaveCount(0);
  expect(mutations).toEqual([]);
});

test("an unresolved album can be reviewed using a published edition search", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openBridge(page, {
    library_q: "Record 3 Gamma",
    library_status: "unmatched",
  });
  const table = page.locator("#library-table");
  const editor = page.getByRole("dialog", { name: "Review Spotify match" });
  await table
    .getByRole("button", { name: "Review match for Record 3" })
    .click();
  await expect(editor).toContainText("No candidates in this publication");
  await editor
    .getByLabel("Candidate title, artist, or Spotify URI")
    .fill("Gamma Record 3");
  await editor.getByRole("button", { name: "Search candidates" }).click();
  const edition = editor
    .getByRole("row")
    .filter({ hasText: "Record 3 (Deluxe Edition)" });
  await expect(edition).toContainText("Gamma");
  await expect(edition).toContainText("Search result");
  expect(
    await editor
      .locator("#library-review-table")
      .evaluate((node) => node.scrollWidth <= node.clientWidth),
  ).toBe(true);
  await edition
    .getByRole("button", {
      name: "Confirm match for Record 3 (Deluxe Edition)",
    })
    .press("Enter");
  await expect(editor.locator("#library-review-saved")).toContainText(
    "Match confirmed",
  );
  await editor.getByRole("button", { name: "Remove saved review" }).click();
  await expect(editor).toContainText("Saved review removed");
  await editor.getByRole("button", { name: "Close match review" }).click();
  await expect(table).toContainText("No exact name match");
  await expect(
    table.getByRole("link", { name: "Confirmed match" }),
  ).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("a candidate that expires between browse and confirmation stays unresolved", async ({
  page,
}) => {
  await openBridge(page, { library_status: "ambiguous" });
  const table = page.locator("#library-table");
  const editor = page.getByRole("dialog", { name: "Review Spotify match" });
  await table
    .getByRole("button", { name: "Review match for Record 2" })
    .click();
  await expect(editor).toContainText("2 candidates");
  await page.route(
    "**/lastfm/analytics/library/candidates?*",
    async (route) => {
      const url = new URL(route.request().url());
      if (!url.searchParams.get("q")?.startsWith("spotify:"))
        return route.continue();
      await route.fulfill({
        status: 409,
        json: { detail: "Collection version expired." },
      });
    },
  );
  await editor
    .getByRole("button", { name: "Confirm match for Record 2" })
    .first()
    .click();
  await expect(editor).toContainText("A publication version expired");
  await editor.getByRole("button", { name: "Close match review" }).click();
  await expect(
    table.getByRole("link", { name: "Confirmed match" }),
  ).toHaveCount(0);
  expect(await exportRow(page, "Record 2")).toMatch(/,"",""$/);
});
