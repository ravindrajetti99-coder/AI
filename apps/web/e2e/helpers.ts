import fs from "node:fs";
import path from "node:path";

import { expect, type Page } from "@playwright/test";

export const ADMIN = { email: "admin@example.com", password: "e2e-admin-password" };
const MAIL_DIR = process.env.E2E_MAIL_DIR ?? "/tmp/eduverse-e2e-mail";

/** The newest emailed link to `pathname` sent to `to` (the API's console backend saves emails as JSON). */
export async function emailedLink(to: string, pathname: string): Promise<string> {
  for (let i = 0; i < 75; i++) {
    const files = fs.existsSync(MAIL_DIR) ? fs.readdirSync(MAIL_DIR).sort().reverse() : [];
    for (const file of files) {
      const email = JSON.parse(fs.readFileSync(path.join(MAIL_DIR, file), "utf8")) as { to: string; text: string };
      const link = email.text.match(/https?:\/\/\S+/)?.[0];
      if (email.to === to && link && new URL(link).pathname === pathname) return link;
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`No email to ${to} with a ${pathname} link`);
}

export async function register(page: Page, name = "E2E Learner"): Promise<string> {
  const email = `learner-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
  await page.goto("/register");
  await page.getByLabel("Name").fill(name);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("password-123");
  await page.getByRole("button", { name: "Create account" }).click();
  await page.waitForURL("**/courses");
  return email;
}

export async function signIn(page: Page, email: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/dashboard");
}

/** Give some answer to whatever objective question is on screen. */
export async function answerSomething(page: Page) {
  const radio = page.getByRole("radio");
  const box = page.getByRole("checkbox", { name: /^[a-e]/i });
  if (await radio.count()) await radio.first().check();
  else if (await box.count()) await box.first().check();
  else await page.getByPlaceholder("Your answer").fill("1");
  await expect(page.locator("body")).toBeVisible();
}
