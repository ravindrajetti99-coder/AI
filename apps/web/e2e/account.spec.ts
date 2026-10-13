import { expect, test } from "@playwright/test";

import { emailedLink, register, signIn } from "./helpers";

test("forgot password: the emailed link sets a new password", async ({ page }) => {
  const email = await register(page);
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.waitForURL("**/login");
  await page.getByRole("link", { name: "Forgot password?" }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Send reset link" }).click();
  await expect(page.getByText(/a reset link is on its way/)).toBeVisible();

  await page.goto(await emailedLink(email, "/reset-password"));
  await page.getByRole("textbox", { name: /^New password/ }).fill("a-new-password-1"); // its name includes the hint
  await page.getByLabel("Repeat the new password").fill("a-new-password-1");
  await page.getByRole("button", { name: "Set new password" }).click();
  await expect(page.getByText(/Your password is changed/)).toBeVisible();
  await signIn(page, email, "a-new-password-1");
});

test("the confirmation email verifies the address, and the password can be changed", async ({ page }) => {
  const email = await register(page);
  await page.goto("/profile");
  await expect(page.getByText("not verified")).toBeVisible();

  await page.goto(await emailedLink(email, "/verify-email"));
  await expect(page.getByText("your email address is confirmed")).toBeVisible();
  await page.getByRole("link", { name: "Go to your profile" }).click();
  await expect(page.getByText("verified", { exact: true })).toBeVisible();

  await page.getByLabel("Current password").fill("password-123");
  await page.getByLabel("New password", { exact: true }).fill("changed-password-1");
  await page.getByLabel("Repeat new password").fill("changed-password-1");
  await page.getByRole("button", { name: "Change password" }).click();
  await expect(page.getByText("Password changed. Other devices were signed out.")).toBeVisible();
  await page.reload(); // this session continues with the tokens issued by the change
  await expect(page.getByRole("heading", { name: "Profile" })).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.waitForURL("**/login");
  await signIn(page, email, "changed-password-1");
});
