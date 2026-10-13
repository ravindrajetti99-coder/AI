import { expect, test } from "@playwright/test";

import { ADMIN, register, signIn } from "./helpers";

test("staff generate a draft, review it and publish it", async ({ page }) => {
  await signIn(page, ADMIN.email, ADMIN.password);
  await page.getByRole("link", { name: "Admin", exact: true }).click();
  await expect(page.getByText("Verified questions")).toBeVisible();

  await page.getByRole("tab", { name: "Generate" }).click();
  await page.getByLabel("Course").selectOption({ label: "SSC CGL Quantitative Aptitude: Arithmetic" });
  await page.getByLabel("Marked price and discount").check();
  await page.getByRole("button", { name: "Start job" }).click();
  await expect(page.getByText(/Created 2 · via offline/)).toBeVisible();

  await page.getByRole("tab", { name: "Review queue" }).click();
  const cards = page.getByRole("button", { name: "Approve" });
  await expect(cards).toHaveCount(2);
  await cards.first().click();
  await expect(cards).toHaveCount(1);
  await page.getByRole("button", { name: "Reject" }).click();
  await expect(page.getByText("The review queue is empty")).toBeVisible();

  await page.getByRole("tab", { name: "AI usage" }).click();
  await expect(page.getByText("teacher.lesson")).toBeVisible();
});

test("learners cannot open the content studio", async ({ page }) => {
  await register(page);
  await page.goto("/admin");
  await expect(page.getByText("This page is for reviewer or admin accounts.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Admin", exact: true })).toHaveCount(0);
});

test("admins invite a reviewer, who signs up through the link", async ({ page, browser }) => {
  await signIn(page, ADMIN.email, ADMIN.password);
  await page.goto("/admin");
  await page.getByRole("tab", { name: "Invites" }).click();
  await page.getByLabel("Note").fill("E2E reviewers");
  await page.getByLabel("Role").selectOption("reviewer");
  await page.getByRole("button", { name: "Create invite" }).click();
  const link = await page.getByText(/\/register\?invite=/).innerText();
  await expect(page.getByText("E2E reviewers")).toBeVisible();

  const guest = await (await browser.newContext()).newPage();
  await guest.goto(link);
  await expect(guest.getByLabel("Invite code")).toHaveValue(/^[A-Z2-7]{4}(-[A-Z2-7]{4}){3}$/);
  await guest.getByLabel("Name").fill("Invited Reviewer");
  await guest.getByLabel("Email").fill(`reviewer-${Date.now()}@example.com`);
  await guest.getByLabel("Password").fill("password-123");
  await guest.getByRole("button", { name: "Create account" }).click();
  await guest.waitForURL("**/courses");
  await expect(guest.getByRole("link", { name: "Admin", exact: true })).toBeVisible(); // reviewers get the studio

  await page.reload();
  await page.getByRole("tab", { name: "Invites" }).click();
  await expect(page.getByText("used", { exact: true })).toBeVisible();
});
