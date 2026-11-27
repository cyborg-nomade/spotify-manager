import { expect } from "@playwright/test";

export const credentials = {
  headers: { "X-App-Password": "browser-test-password" },
};

export async function resetFixture(request) {
  const response = await request.post("/__browser_fixture/reset", credentials);
  expect(response.status()).toBe(204);
}

export async function submitPassword(page, password) {
  await page.getByLabel("App password").fill(password);
  await page.getByRole("button", { name: "Unlock", exact: true }).click();
}

export async function openCockpit(page) {
  await page.goto("/");
  await submitPassword(page, credentials.headers["X-App-Password"]);
  await expect(page.getByText("4 / 4 sources available")).toBeVisible();
}

export function postedTo(page, path) {
  return page.waitForRequest(
    (request) =>
      request.method() === "POST" && new URL(request.url()).pathname === path,
  );
}

export async function confirmAction(page, control, text, accept) {
  const dismissed = page.waitForEvent("dialog").then(async (dialog) => {
    expect(dialog.type()).toBe("confirm");
    const message = dialog.message();
    if (accept) await dialog.accept();
    else await dialog.dismiss();
    expect(message).toBe(text);
  });
  await Promise.all([dismissed, control.click()]);
}
