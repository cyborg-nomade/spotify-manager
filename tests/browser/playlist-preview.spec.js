import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";

async function openPreview(page) {
  await page.goto("/lastfm?tab=playlist-preview&preset=all");
  await page
    .getByLabel("App password", { exact: true })
    .fill("browser-test-password");
  await page.getByRole("button", { name: "Unlock explorer" }).click();
  await expect(page.locator("#playlist-table table")).toBeAttached();
}

test("the playlist reconciles repeated and unresolved plays and exports the full proposal", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const proposal = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname ===
        "/lastfm/analytics/playlist-preview" && response.ok(),
  );
  await openPreview(page);
  const summary = (await (await proposal).json()).data.summary;
  expect(summary.selected_plays).toBe(781);
  expect(summary.playlist_tracks).toBe(2);
  expect(
    summary.playlist_tracks +
      summary.duplicate_plays +
      summary.unresolved_plays,
  ).toBe(781);
  await expect(page.locator("#playlist-source")).toContainText(
    "Liked tracks published",
  );
  await expect(page.locator("#playlist-table tbody tr").first()).toContainText(
    "Song 0",
  );
  await page.locator("#playlist-view").selectOption("duplicates");
  await expect(page.locator("#playlist-table tbody tr")).toHaveCount(1);
  await expect(page.locator("#playlist-table")).toContainText("Repeat plays");
  await page.locator("#playlist-view").selectOption("unresolved");
  await expect(page.locator("#playlist-table")).toContainText(
    "Multiple exact-name candidates",
  );
  await page.locator("#playlist-next").click();
  await expect(page.locator("#playlist-page")).toContainText("Page 2");
  const saved = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download playlist CSV" }).click();
  const csv = await readFile(await (await saved).path(), "utf8");
  expect(csv).toContain('"Liked tracks snapshot","l1-');
  expect(csv).toContain('"Selected plays","781"');
  expect(csv).toContain(`"1","spotify:track:${"f".repeat(22)}","Song 0"`);
  expect(csv).toContain(`"2","spotify:track:${"d".repeat(22)}","'=formula"`);
  expect(csv).not.toContain("spotify:track:" + "g".repeat(22));
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);

  await page.route("**/lastfm/analytics/playlist-preview/csv?*", (route) =>
    route.fulfill({
      status: 409,
      json: { detail: "Collection version expired." },
    }),
  );
  await page.getByRole("button", { name: "Download playlist CSV" }).click();
  await expect(page.locator("#playlist-message")).toContainText(
    "A publication version expired",
  );
});

test("a current Library Bridge confirmation resolves an otherwise ambiguous track", async ({
  page,
}) => {
  await page.goto(
    "/lastfm?tab=library&preset=all&library_kind=track&library_status=ambiguous",
  );
  await page
    .getByLabel("App password", { exact: true })
    .fill("browser-test-password");
  await page.getByRole("button", { name: "Unlock explorer" }).click();
  await page
    .getByRole("button", { name: "Review match for Song 1", exact: true })
    .click();
  const dialog = page.getByRole("dialog", { name: "Review Spotify match" });
  const uri = "spotify:track:" + "g".repeat(22);
  await dialog
    .getByRole("row")
    .filter({ hasText: uri })
    .getByRole("button", { name: "Confirm match for Song 1", exact: true })
    .click();
  await expect(dialog).toContainText("Match confirmed in this browser");
  await dialog.getByRole("button", { name: "Close match review" }).click();
  await page
    .getByRole("button", { name: "Playlist preview", exact: true })
    .click();
  const selected = page
    .locator("#playlist-table tbody tr")
    .filter({ hasText: "Song 1" });
  await expect(selected).toContainText("Confirmed in Library Bridge");
  await expect(
    selected.getByRole("link", { name: "Song 1", exact: true }),
  ).toHaveAttribute("href", `https://open.spotify.com/track/${"g".repeat(22)}`);
  await selected.getByRole("button", { name: /Song 1/ }).click();
  await expect(page.locator("#detail-title")).toHaveText("Song 1");
});
