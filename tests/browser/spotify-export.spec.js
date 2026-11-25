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
  await choice.selectOption(await alternate.getAttribute("value"));
  await expect(alternate).toHaveText(/No exact saved edition/);
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
  await expect(alternate).toHaveText(/Spotify edition available/);
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
