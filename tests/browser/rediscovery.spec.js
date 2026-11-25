import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";

async function open(page, tab) {
  await page.goto(`/lastfm?tab=${tab}&preset=all`);
  await page
    .getByLabel("App password", { exact: true })
    .fill("browser-test-password");
  await page.getByRole("button", { name: "Unlock explorer" }).click();
}

test("artists to revisit suggests an album, supports a swap, and exports its Spotify order", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  let tracklistRequests = 0;
  let selected = [];
  await page.route("**/rediscovery/album-tracklists?*", async (route) => {
    tracklistRequests++;
    selected = route.request().postDataJSON().albums;
    if (tracklistRequests === 1) {
      const response = await route.fetch();
      const json = await response.json();
      json.data.albums[0].tracks = [];
      json.data.albums[0].message = "Spotify timed out. Try again.";
      await route.fulfill({ response, json });
    } else await route.continue();
  });
  await open(page, "rediscovery");
  const row = page
    .locator("#revisit-table tbody tr")
    .filter({ hasText: "Old Favorite" });
  await expect(row).toContainText("listening weeks");
  await expect(row).toContainText("No recorded plays");
  await expect(page.locator("#revisit-library")).toContainText(
    "published saved albums",
  );
  const options = row.getByRole("combobox", { name: "Album for Old Favorite" });
  const alternate = options.locator("option").filter({ hasText: "Record 1" });
  await options.selectOption(await alternate.getAttribute("value"));
  await row.getByRole("checkbox", { name: "Include Old Favorite" }).check();
  expect(tracklistRequests).toBe(0);
  const preview = page.getByRole("button", { name: "Preview album tracks" });
  const csvButton = page.getByRole("button", {
    name: "Download rediscovery CSV",
  });
  await preview.click();
  await expect(page.locator("#revisit-tracks")).toContainText(
    "Spotify timed out",
  );
  await expect(csvButton).toBeDisabled();
  await preview.click();
  await expect(csvButton).toBeEnabled();
  expect(selected).toEqual(["spotify:album:" + "q".repeat(22)]);
  const album = page.locator("#revisit-tracks summary");
  await expect(album).toContainText("Old Favorite — Record 1");
  await album.click();
  const tracks = page.locator("#revisit-tracks li");
  await expect(tracks).toHaveText([
    "1.1 =Album opener",
    "1.2 Second song",
    "2.1 Disc two",
  ]);
  const download = page.waitForEvent("download");
  await csvButton.click();
  const csv = await readFile(await (await download).path(), "utf8");
  expect(csv).toContain('"Recent through","2025-02-17"');
  expect(csv).toContain('"Saved albums snapshot","l1-');
  expect(csv.indexOf("'=Album opener")).toBeLessThan(
    csv.indexOf("Second song"),
  );
  expect(csv.indexOf("Second song")).toBeLessThan(csv.indexOf("Disc two"));
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("a Musical Eras period becomes the editable historical window", async ({
  page,
}) => {
  await open(page, "capsule");
  await page.locator("#era-reference").selectOption("2023-08");
  await page
    .getByRole("button", { name: "Rediscover artists from this period" })
    .click();
  await expect(page.locator("#revisit-history")).toHaveValue("selection");
  await expect(page.locator("#revisit-from")).toHaveValue("2023-08-01");
  await expect(page.locator("#revisit-to")).toHaveValue("2023-08-31");
  await expect(page.locator("#revisit-coverage")).toContainText(
    "Then 2023-08-01 to 2023-08-31",
  );
  await page.reload();
  await expect(page.locator("#revisit-coverage")).toContainText(
    "Then 2023-08-01 to 2023-08-31",
  );
});
