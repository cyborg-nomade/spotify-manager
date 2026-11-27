import { expect, test } from "@playwright/test";

const startUri = "spotify:album:" + "q".repeat(22);
const palaceCard = "#palaceOfMemoryCard";

async function openPalaceFromRediscover(page) {
  await page.goto("/lastfm?tab=rediscovery&preset=all");
  await page
    .getByLabel("App password", { exact: true })
    .fill("browser-test-password");
  await page.getByRole("button", { name: "Unlock explorer" }).click();
  await expect(page.locator("#revisit-library")).toContainText(
    "published saved albums",
  );
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
  await page.locator("#revisit-tracks summary").click();
  await page
    .getByRole("button", { name: "Use as Palace starting album" })
    .click();
  await expect(page).toHaveURL(/\/\?palace=rediscover#palaceOfMemoryCard$/);
}

async function unlockCockpit(page) {
  await expect(page.locator(palaceCard)).not.toBeVisible();
  await page.locator("#pw").fill("browser-test-password");
  await page.locator("#pwBtn").click();
}

function palaceStarts(page) {
  const starts = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (
      url.pathname === "/commands/fill-palace-of-memory" &&
      request.method() === "POST"
    )
      starts.push(Object.fromEntries(url.searchParams));
  });
  return starts;
}

test("the Palace handoff fills the existing dry run and waits for Run", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const starts = palaceStarts(page);
  const job = {
    job_id: "fixture-palace",
    status: "completed",
    detail: "Synthetic Palace preview complete",
    dry_run: true,
    palace_alphabetical_reference: startUri,
  };
  await page.route("**/commands/fill-palace-of-memory?*", (route) =>
    route.fulfill({ json: job }),
  );
  await page.route("**/commands/fill-palace-of-memory-jobs**", (route) =>
    route.fulfill({
      json: route.request().url().endsWith("/fixture-palace") ? job : [],
    }),
  );
  await openPalaceFromRediscover(page);
  await unlockCockpit(page);
  const card = page.locator(palaceCard);
  await expect(card.locator("#palaceHandoffStatus")).toContainText(
    "Old Favorite — Record 1 is the alphabetical starting album",
  );
  await expect(card.locator("#palaceAlphabeticalStart")).toHaveValue(startUri);
  await expect(card.getByRole("checkbox", { name: "Dry run" })).toBeChecked();
  expect(starts).toEqual([]);
  expect(page.url()).not.toContain(startUri);

  const run = card.locator('[data-action="startPalaceOfMemory"]');
  await card.getByRole("checkbox", { name: "Dry run" }).uncheck();
  const confirm = page.waitForEvent("dialog");
  const click = run.click();
  const prompt = await confirm;
  expect(prompt.message()).toContain("Add the selected album first tracks");
  await prompt.dismiss();
  await click;
  expect(starts).toEqual([]);

  await card.getByRole("checkbox", { name: "Dry run" }).check();
  await run.click();
  await expect(card.locator("#palaceOfMemoryProgress")).toContainText(
    "Synthetic Palace preview complete",
  );
  expect(starts).toEqual([{ dry_run: "true", alphabetical_start: startUri }]);
});

test("a publication change requires a new album preview before Run", async ({
  page,
}) => {
  const starts = palaceStarts(page);
  await page.route("**/commands/fill-palace-of-memory-jobs", (route) =>
    route.fulfill({ json: [] }),
  );
  await openPalaceFromRediscover(page);
  await unlockCockpit(page);
  const card = page.locator(palaceCard);
  await expect(card.locator("#palaceAlphabeticalStart")).toHaveValue(startUri);
  await page.route("**/lastfm/analytics/library/status*", (route) =>
    route.fulfill({
      json: {
        state: "ready",
        checking: false,
        snapshot: "l1-" + "0".repeat(64),
      },
    }),
  );
  await card.locator('[data-action="startPalaceOfMemory"]').click();
  await expect(card.locator("#palaceHandoffStatus")).toContainText(
    "This album selection has expired",
  );
  await expect(
    card.getByRole("link", { name: "Return to Rediscover" }),
  ).toBeVisible();
  expect(starts).toEqual([]);
});

test("a handoff opened without a current browser preview stays idle", async ({
  page,
}) => {
  const starts = palaceStarts(page);
  await page.route("**/commands/fill-palace-of-memory-jobs", (route) =>
    route.fulfill({ json: [] }),
  );
  await page.goto("/?palace=rediscover#palaceOfMemoryCard");
  await unlockCockpit(page);
  const card = page.locator(palaceCard);
  await expect(card.locator("#palaceHandoffStatus")).toContainText(
    "This album selection has expired",
  );
  await expect(card.locator("#palaceAlphabeticalStart")).toHaveValue("");
  await card.locator('[data-action="startPalaceOfMemory"]').click();
  expect(starts).toEqual([]);
});
