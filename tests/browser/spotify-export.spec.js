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
  const owner = dialog.getByRole("combobox", {
    name: "Your playlists",
    exact: true,
  });
  await owner.selectOption("w".repeat(22));
  await expect(owner.locator("option")).toHaveCount(2);
  await dialog.getByRole("button", { name: "Review exact additions" }).click();
  await expect(dialog).toContainText(
    "Append to public playlist “Existing mix”",
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
