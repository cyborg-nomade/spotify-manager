import { expect, test } from "@playwright/test";

async function open(page, tab) {
  await page.goto(`/lastfm?tab=${tab}&preset=all`);
  await page
    .getByLabel("App password", { exact: true })
    .fill("browser-test-password");
  await page.getByRole("button", { name: "Unlock explorer" }).click();
}

test("Spotify append requires review and keeps exact order and progress after reload", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  let confirmations = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.endsWith("/confirm")) confirmations++;
  });
  await open(page, "playlist-preview");
  await page
    .getByRole("button", { name: "Review Spotify export", exact: true })
    .click();
  const dialog = page.getByRole("dialog", { name: "Export to Spotify" });
  await dialog
    .getByRole("combobox", { name: "Destination", exact: true })
    .selectOption("existing");
  await expect(dialog.locator("#spotify-export-kind option")).toHaveCount(2);
  await expect(dialog.locator("#spotify-export-existing")).toHaveText(
    "A Blast from the Past · public",
  );
  await dialog.getByRole("button", { name: "Review exact additions" }).click();
  await expect(dialog).toContainText(
    "Append to public playlist “A Blast from the Past”",
  );
  await expect(dialog.locator("tbody tr")).toHaveCount(2);
  await expect(dialog.locator("tbody tr").first()).toContainText("Song 0");
  expect(confirmations).toBe(0);
  await dialog.getByRole("button", { name: "Confirm Spotify export" }).click();
  await expect(dialog).toContainText("2 / 2 tracks confirmed");
  expect(confirmations).toBe(1);
  await expect(
    dialog.getByRole("link", { name: "Open playlist in Spotify" }),
  ).toHaveAttribute(
    "href",
    "https://open.spotify.com/playlist/" + "w".repeat(22),
  );
  await page.reload();
  await page.getByRole("button", { name: "Spotify export status" }).click();
  await expect(dialog).toContainText("2 / 2 tracks confirmed");
  expect(confirmations).toBe(1);
});

test("Rediscover reviews a complete selected album before creating a private playlist", async ({
  page,
}) => {
  await open(page, "rediscovery");
  await expect(page.locator("#revisit-library")).toContainText(
    "published saved albums",
  );
  const row = page
    .locator("#revisit-table tbody tr")
    .filter({ hasText: "Old Favorite" });
  const choice = row.getByRole("combobox");
  await choice.selectOption(
    await row
      .locator("option")
      .filter({ hasText: "Record 0" })
      .getAttribute("value"),
  );
  await row.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Preview album tracks" }).click();
  await page
    .getByRole("button", { name: "Review Spotify export", exact: true })
    .click();
  const dialog = page.getByRole("dialog", { name: "Export to Spotify" });
  await dialog
    .getByLabel("Playlist name", { exact: true })
    .fill("Synthetic rediscovery");
  await dialog.getByRole("button", { name: "Review exact additions" }).click();
  await expect(dialog).toContainText(
    "Create private playlist “Synthetic rediscovery”",
  );
  await expect(dialog.locator("tbody tr")).toHaveCount(3);
  await expect(dialog.locator("tbody tr").last()).toContainText("Disc two");
  await dialog.getByRole("button", { name: "Confirm Spotify export" }).click();
  await expect(dialog).toContainText("3 / 3 tracks confirmed");
});

test("an unmatched shortlist album can use a saved alternate and queue only its opener", async ({
  page,
}) => {
  await open(page, "rediscovery");
  await expect(page.locator("#revisit-library")).toContainText(
    "published saved albums",
  );
  const row = page
    .locator("#revisit-table tbody tr")
    .filter({ hasText: "Old Favorite" });
  const choice = row.getByRole("combobox");
  const alternate = choice.locator("option").filter({ hasText: "Record 2" });
  const albumDetails = row.locator(".revisit-album-meta");
  await choice.selectOption(await alternate.getAttribute("value"));
  await expect(albumDetails).toContainText("No exact saved edition");
  const included = row.getByRole("checkbox");
  await expect(included).toBeDisabled();
  await row
    .getByRole("button", { name: "Match saved edition for Old Favorite" })
    .click();
  const match = page.getByRole("dialog", { name: "Review Spotify match" });
  await expect(
    match.getByRole("link", { name: "find and save it in Spotify" }),
  ).toHaveAttribute("href", /open.spotify.com/);
  await match
    .getByRole("button", { name: "Confirm match for Record 2 (Remastered)" })
    .click();
  await expect(match).toContainText("Match confirmed in this browser");
  await match.getByRole("button", { name: "Close match review" }).click();
  await expect(included).toBeChecked();
  await expect(albumDetails).toContainText("Spotify edition available");
  await page.getByRole("button", { name: "Preview album tracks" }).click();
  await page
    .getByRole("button", { name: "Review Spotify export", exact: true })
    .click();
  const dialog = page.getByRole("dialog", { name: "Export to Spotify" });
  await dialog
    .getByRole("combobox", { name: "Destination" })
    .selectOption({ label: "Palace of Memory · first track per album" });
  await dialog.getByRole("button", { name: "Review exact additions" }).click();
  await expect(dialog).toContainText("Palace of Memory");
  await expect(dialog.locator("tbody tr")).toHaveCount(1);
  await expect(dialog.locator("tbody tr")).toContainText("Album opener");
  await dialog.getByRole("button", { name: "Confirm Spotify export" }).click();
  await expect(dialog).toContainText("1 / 1 tracks confirmed");
});

test("Rediscover opens the applied dates and preselects A Blast from the Past", async ({
  page,
}) => {
  await page.route("**/analytics/playlist-preview?*", async (route) => {
    if (
      new URL(route.request().url()).searchParams.get("to") !== "2024-10-31"
    ) {
      await route.continue();
      return;
    }
    const response = await route.fetch();
    const json = await response.json();
    json.data.summary.playlist_tracks = 10001;
    await route.fulfill({ response, json });
  });
  await open(page, "rediscovery");
  await page.locator("#revisit-history").selectOption("selection");
  await page.locator("#revisit-from").fill("2024-01-01");
  await page.locator("#revisit-to").fill("2024-10-31");
  await page.getByRole("button", { name: "Find artists" }).click();
  await expect(page.locator("#revisit-coverage")).toContainText(
    "Then 2024-01-01 to 2024-10-31",
  );
  await page
    .getByRole("button", { name: "Preview tracks for A Blast from the Past" })
    .click();
  await expect(page.locator("#from")).toHaveValue("2024-01-01");
  await expect(page.locator("#to")).toHaveValue("2024-10-31");
  await expect(page.locator("#playlist-view")).toHaveValue("tracks");
  await expect(page.locator("#playlist-message")).toContainText(
    "Shorten the date range before exporting to Spotify.",
  );
  await page.locator("#to").fill("2024-06-30");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page.locator("#playlist-message")).toBeEmpty();
  await page.locator("#history-spotify-export").click();
  const dialog = page.getByRole("dialog", { name: "Export to Spotify" });
  await expect(
    dialog.getByRole("combobox", { name: "Destination" }),
  ).toHaveValue("existing");
  await expect(dialog.locator("#spotify-export-existing")).toHaveText(
    "A Blast from the Past · public",
  );
  await dialog.getByRole("button", { name: "Review exact additions" }).click();
  await expect(dialog).toContainText(
    "Append to public playlist “A Blast from the Past”",
  );
});

test("the album export dialog offers a route to the individual track preview", async ({
  page,
}) => {
  await open(page, "rediscovery");
  const row = page
    .locator("#revisit-table tbody tr")
    .filter({ hasText: "Old Favorite" });
  const choice = row.getByRole("combobox");
  await choice.selectOption(
    await choice
      .locator("option")
      .filter({ hasText: "Record 1" })
      .getAttribute("value"),
  );
  await row.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Preview album tracks" }).click();
  await page.locator("#revisit-spotify-export").click();
  const dialog = page.getByRole("dialog", { name: "Export to Spotify" });
  await dialog.getByRole("combobox", { name: "Destination" }).selectOption({
    label: "A Blast from the Past · review tracks",
  });
  await dialog.getByRole("button", { name: "Open track preview" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.locator("#playlist-table tbody tr").first()).toBeVisible();
  await page.locator("#history-spotify-export").click();
  await expect(dialog.locator("#spotify-export-existing")).toHaveText(
    "A Blast from the Past · public",
  );
});
