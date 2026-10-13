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
