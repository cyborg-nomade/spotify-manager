import { test, expect } from "@playwright/test";
import {
  confirmAction,
  credentials,
  openCockpit,
  postedTo,
  resetFixture,
} from "./cockpit-fixture.js";

test.beforeEach(async ({ request }) => {
  await resetFixture(request);
});

async function openGenreReveal(page) {
  await openCockpit(page);
  const card = page.locator("#genreRevealCard");
  await card.getByRole("button", { name: "Open", exact: true }).click();
  await expect(page).toHaveURL(/\/genre-reveal$/);
  await expect(
    page.getByRole("button", { name: "Run cathedral choir" }),
  ).toBeEnabled();
}

test("Genre Reveal uses the cockpit tab password and restores route progress, filters, and position controls", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  expect((await page.request.get("/genre-reveal/state")).status()).toBe(401);
  await page.goto("/genre-reveal");
  await expect(
    page.getByRole("button", { name: "Unlock", exact: true }),
  ).toBeVisible();
  await openGenreReveal(page);
  await expect(page.locator("#progressText")).toHaveText("1 / 6,132");
  const firstGenre = page.getByRole("link", { name: "kerkkoor", exact: true });
  const nextGenre = page.getByRole("link", {
    name: "cathedral choir",
    exact: true,
  });
  await expect(firstGenre).toBeVisible();
  const search = page.getByRole("searchbox", { name: "Search genres" });
  await search.fill("cathedralchoir");
  await expect(firstGenre).toBeHidden();
  await expect(nextGenre).toBeVisible();
  await search.fill("no-genre-for-this-query");
  await expect(page.getByText("No matching genres.")).toBeVisible();
  await page.getByRole("button", { name: "Resume" }).click();
  await expect(search).toHaveValue("");
  await expect(page.locator("article.current")).toContainText(
    "cathedral choir",
  );

  const jump = page.getByLabel("Jump to #");
  await jump.fill("3");
  await jump.press("Tab");
  await expect(page.locator("article.current")).toContainText(
    "early music choir",
  );
  const saved = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/genre-reveal/state" &&
      response.request().method() === "PUT" &&
      response.ok(),
  );
  await page.getByLabel("Hide completed").check();
  expect((await saved).request().postDataJSON()).toEqual({
    completed: ["kerkkoor"],
    hide_done: true,
  });
  await page.reload();
  await expect(page.getByLabel("Hide completed")).toBeChecked();
  await expect(firstGenre).toBeHidden();
  await expect(nextGenre).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("Genre Reveal marks a genre complete only after a successful run and confirms reset", async ({
  page,
}) => {
  await openGenreReveal(page);
  const run = page.getByRole("button", { name: "Run cathedral choir" });
  const checkbox = page.getByRole("checkbox", {
    name: "Mark cathedral choir completed",
  });
  const endpoint = "/genre-reveal/run-next";
  await expect(page.locator("#nextGenreLink")).toBeVisible();
  await expect(page.locator("#nextPlaylistLink")).toBeVisible();
  await page.route(
    "**" + endpoint,
    (route) =>
      route.fulfill({
        status: 502,
        json: { detail: "Sample source unavailable" },
      }),
    { times: 1 },
  );
  const failed = postedTo(page, endpoint);
  await run.click();
  expect((await failed).postDataJSON()).toEqual({
    slug: "cathedralchoir",
    name: "cathedral choir",
  });
  await expect(
    page.getByText("cathedral choir failed: Sample source unavailable"),
  ).toBeVisible();
  await expect(checkbox).not.toBeChecked();
  await expect(page.locator("#progressText")).toHaveText("1 / 6,132");
  await run.click();
  await expect(
    page.getByText(
      "cathedral choir: playlist saved; 1 tracks added, 1 already present.",
    ),
  ).toBeVisible();
  await expect(checkbox).toBeChecked();
  await expect(
    page.getByRole("button", { name: "Run early music choir" }),
  ).toBeEnabled();
  await expect(page.locator("#progressText")).toHaveText("2 / 6,132");

  const reset = page.getByRole("button", { name: "Reset progress" });
  await confirmAction(page, reset, "Clear all completed genres?", false);
  await expect(checkbox).toBeChecked();
  await confirmAction(page, reset, "Clear all completed genres?", true);
  await expect(page.locator("#progressText")).toHaveText("0 / 6,132");
  await expect(
    page.getByRole("button", { name: "Run kerkkoor" }),
  ).toBeEnabled();
});

test("Flush Mode suppresses new discovery starts and refreshes the open Genre Reveal controls", async ({
  page,
}) => {
  await page.clock.install();
  await openGenreReveal(page);
  const response = await page.request.put("/flush-mode/control", {
    ...credentials,
    data: { control: "on" },
  });
  expect(response.ok()).toBe(true);
  await page.clock.fastForward(5_000);
  await expect(
    page.getByText(/Flush Mode blocks new Genre Reveal actions/),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Run cathedral choir" }),
  ).toBeDisabled();
  await expect(page.getByLabel("Hide completed")).toBeDisabled();
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Force on" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(
    page.locator("#genreRevealCard").getByRole("button", { name: "Open" }),
  ).toBeDisabled();
  await expect(
    page
      .locator("#foundArtCard")
      .getByRole("button", { name: "Run", exact: true }),
  ).toBeDisabled();
  const wine = page.locator("#newWineCard").getByLabel("No discovery");
  await expect(wine).toBeChecked();
  await expect(wine).toBeDisabled();
  await page.getByRole("button", { name: "Automatic", exact: true }).click();
  await expect(
    page.locator("#genreRevealCard").getByRole("button", { name: "Open" }),
  ).toBeEnabled();
  await expect(wine).toBeEnabled();
  await expect(wine).not.toBeChecked();
});
