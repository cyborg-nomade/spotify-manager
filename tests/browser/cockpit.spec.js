import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";
import {
  confirmAction,
  credentials,
  openCockpit,
  postedTo,
  resetFixture,
  submitPassword,
} from "./cockpit-fixture.js";

test.beforeEach(async ({ request }) => {
  await resetFixture(request);
});

test("the password gate protects cockpit data and remembers only the selected tab session", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.locator("#gate")).toBeVisible();
  await expect(page.locator("#app")).toBeHidden();
  expect((await page.request.get("/library-mirrors/status")).status()).toBe(
    401,
  );
  expect((await page.request.get("/scrobble-history/download")).status()).toBe(
    401,
  );
  await submitPassword(page, "wrong-password");
  await expect(page.getByText("Wrong password")).toBeVisible();
  await expect(page.locator("#gate")).toBeVisible();

  const password = page.getByPlaceholder("Any text");
  await password.fill(credentials.headers["X-App-Password"]);
  await password.press("Enter");
  await expect(page.getByText("4 / 4 sources available")).toBeVisible();
  await page.reload();
  await expect(page.getByText("4 / 4 sources available")).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.locator("#gate")).toBeVisible();
  await page.reload();
  await expect(page.locator("#gate")).toBeVisible();

  await page.getByLabel("Keep me signed in on this device").uncheck();
  await submitPassword(page, credentials.headers["X-App-Password"]);
  await expect(page.getByText("4 / 4 sources available")).toBeVisible();
  await page.reload();
  await expect(page.locator("#app")).toBeHidden();
});

test("a Full mirror sync reconnects after reload and can be stopped", async ({
  page,
}) => {
  await openCockpit(page);
  const albums = page.locator('[data-mirror-resource="albums"]');
  const recent = albums.getByRole("button", { name: "Recent" });
  const full = albums.getByRole("button", { name: "Full" });
  await expect(recent).toHaveAttribute("aria-pressed", "true");
  await full.click();
  const launch = postedTo(page, "/commands/refresh-library-mirrors/albums");
  await albums.getByRole("button", { name: "Sync", exact: true }).click();
  const request = await launch;
  expect(new URL(request.url()).searchParams.toString()).toBe(
    "full_rebuild=true",
  );
  expect(await request.headerValue("x-app-password")).toBe(
    credentials.headers["X-App-Password"],
  );
  await expect(full).toBeDisabled();
  await expect(albums.getByText("84 / 120")).toBeVisible();

  const job = "/commands/library-analysis-jobs/sample-mirror-albums-1";
  const reconnected = page.waitForResponse(
    (response) => new URL(response.url()).pathname === job && response.ok(),
  );
  await page.reload();
  await reconnected;
  await expect(full).toHaveAttribute("aria-pressed", "true");
  await expect(recent).toBeDisabled();
  const cancel = postedTo(page, job + "/cancel");
  await albums.getByTitle("Stop refresh", { exact: true }).click();
  await cancel;
  await expect(
    albums.getByText("Sample library refresh cancelled"),
  ).toBeVisible();
  await expect(
    albums.getByRole("button", { name: "Sync", exact: true }),
  ).toBeEnabled();
  await expect(full).toBeEnabled();
});

test("the Last.fm row refreshes, downloads a history attachment, and opens Explorer", async ({
  page,
}) => {
  await openCockpit(page);
  const history = page.locator("#scrobbleHistoryCard");
  await expect(history.getByRole("button", { name: "Recent" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  const refresh = postedTo(page, "/commands/update-scrobble-history");
  await history.getByRole("button", { name: "Sync", exact: true }).click();
  const parameters = new URL((await refresh).url()).searchParams;
  expect(Object.fromEntries(parameters)).toEqual({
    dry_run: "false",
    full_rebuild: "false",
  });
  await expect(history.getByText("Sample history refreshed")).toBeVisible();
  const attachment = page.waitForEvent("download");
  await history.getByRole("button", { name: "Download" }).click();
  const downloaded = await attachment;
  expect(downloaded.suggestedFilename()).toBe("lastfmstats-man-et-arms.json");
  const content = JSON.parse(await readFile(await downloaded.path(), "utf8"));
  expect(content.username).toBe("fixture");
  expect(content.scrobbles).toHaveLength(781);
  await history
    .getByRole("link", { name: "Open Last.fm Listening Explorer" })
    .click();
  await expect(page).toHaveURL(/\/lastfm$/);
  await expect(
    page.getByRole("button", { name: "Unlock explorer" }),
  ).toBeVisible();
});

test("Blast starts in Count dry-run mode and can reconnect to a concurrent Cap run", async ({
  page,
}) => {
  await openCockpit(page);
  const blast = page.locator("#blastCard");
  const run = blast.getByRole("button", { name: "Run", exact: true });
  await expect(blast.getByLabel("Tracks to process")).toHaveValue("10");
  await expect(
    blast.getByLabel("Dry run", { exact: true }).first(),
  ).toBeChecked();
  const start = "/commands/blast-from-the-past";
  const launch = postedTo(page, start);
  await run.click();
  expect(
    Object.fromEntries(new URL((await launch).url()).searchParams),
  ).toEqual({
    count: "10",
    dry_run: "true",
  });
  await expect(
    blast.getByText("Reviewing sample listening history for 10 tracks"),
  ).toBeVisible();
  await blast
    .getByRole("button", { name: "Stop A blast from the past" })
    .click();
  await expect(run).toBeEnabled();

  await blast.getByRole("button", { name: "Cap", exact: true }).click();
  await blast.getByLabel("Maximum playlist length").fill("24");
  const active = await page.request.post(
    start + "?dry_run=true&max_playlist_length=24",
    credentials,
  );
  expect(active.ok()).toBe(true);
  const { job_id: jobId } = await active.json();
  const conflict = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === start && response.status() === 409,
  );
  const reconnected = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === start + "-jobs/" + jobId &&
      response.ok(),
  );
  await run.click();
  const conflictRequest = (await conflict).request();
  expect(
    Object.fromEntries(new URL(conflictRequest.url()).searchParams),
  ).toEqual({
    max_playlist_length: "24",
    dry_run: "true",
  });
  await reconnected;
  await expect(
    blast.getByText(/Reviewing sample listening history for cap of 24/),
  ).toBeVisible();
});

test("Requeue requires live confirmation and reconnects to the exact pending album", async ({
  page,
}) => {
  await openCockpit(page);
  const panel = page.locator("#requeueForADreamCard");
  const dryRun = panel.getByLabel("Dry run");
  const run = panel.getByRole("button", { name: "Run", exact: true });
  const start = "/commands/flush-requeue-for-a-dream";
  const launches = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === start) launches.push(request);
  });
  await expect(dryRun).toBeChecked();
  await dryRun.uncheck();
  const warning = "Advance the first Requeue for a Dream artist?";
  await confirmAction(page, run, warning, false);
  expect(launches).toHaveLength(0);
  const launch = postedTo(page, start);
  await confirmAction(page, run, warning, true);
  expect(new URL((await launch).url()).searchParams.get("dry_run")).toBe(
    "false",
  );
  await expect(panel.getByText("Rooms Without Windows")).toBeVisible();
  await page.reload();
  await expect(panel.getByText("Rooms Without Windows")).toBeVisible();
  await expect(dryRun).not.toBeChecked();
  await expect(dryRun).toBeDisabled();

  const choice = start + "-jobs/sample-requeue-1/choice";
  const skipped = postedTo(page, choice);
  await panel.getByRole("button", { name: "Skip album" }).click();
  expect((await skipped).postDataJSON()).toEqual({
    request_id: "sample-choice-1",
    choice: "skip",
  });
  await expect(panel.getByText("Only a Receiver")).toBeVisible();
  const accepted = postedTo(page, choice);
  await panel.getByRole("button", { name: "Accept album" }).click();
  expect((await accepted).postDataJSON()).toEqual({
    request_id: "sample-choice-2",
    choice: "accept",
  });
  await expect(panel.getByText("Sample album accepted")).toBeVisible();
  await expect(run).toBeEnabled();
});

test("shared state preserves guided edits, confirmation, and stale revision recovery", async ({
  page,
}) => {
  await openCockpit(page);
  await page.getByRole("button", { name: "View", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Shared state" });
  const namespace = dialog.getByLabel("State namespace");
  await namespace.selectOption("discography");
  await dialog
    .locator("#stateGuidedEditor")
    .getByRole("combobox")
    .selectOption(JSON.stringify("requeue"));
  await expect(dialog.getByText("Unsaved changes")).toBeVisible();
  await dialog.getByRole("button", { name: "Advanced JSON" }).click();
  const json = dialog.getByLabel("Shared state JSON");
  expect(JSON.parse(await json.inputValue()).next_queue).toBe("requeue");
  const path = "/state/namespaces/discography";
  const save = dialog.getByRole("button", { name: "Save", exact: true });
  const warning = "Replace the shared state namespace “discography”?";
  const saved = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === path &&
      response.request().method() === "PUT" &&
      response.ok(),
  );
  await confirmAction(page, save, warning, true);
  expect((await saved).request().postDataJSON()).toEqual({
    expected_revision: "sample-revision-1",
    value: { version: 1, next_queue: "requeue" },
  });
  await expect(dialog.getByText("sample-revision-2")).toBeVisible();

  const competingEdit = await page.request.put(path, {
    ...credentials,
    data: {
      expected_revision: "sample-revision-2",
      value: { version: 1, next_queue: "memory_lane" },
    },
  });
  expect(competingEdit.ok()).toBe(true);
  const stale = JSON.stringify({ version: 1, next_queue: "newfoundland" });
  await json.fill(stale);
  await confirmAction(page, save, warning, true);
  await expect(
    page.getByText("State changed elsewhere. Reload before saving."),
  ).toBeVisible();
  await expect(json).toHaveValue(stale);
  await confirmAction(
    page,
    dialog.getByRole("button", { name: "Reload" }),
    "Discard unsaved state edits and reload?",
    true,
  );
  await expect(dialog.getByText("sample-revision-3")).toBeVisible();
  expect(JSON.parse(await json.inputValue()).next_queue).toBe("memory_lane");
  await dialog.getByRole("button", { name: "Close", exact: true }).click();
  await expect(dialog).toBeHidden();
});
