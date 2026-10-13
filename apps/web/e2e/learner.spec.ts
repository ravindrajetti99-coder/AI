import { expect, test } from "@playwright/test";

import { answerSomething, register } from "./helpers";

test("register, enroll, practise, and keep the session across a reload", async ({ page }) => {
  await register(page, "Ravi Kumar");
  await page.getByRole("link", { name: /SSC CGL Quantitative Aptitude/ }).click();
  await expect(page.getByRole("heading", { name: "Syllabus" })).toBeVisible();
  await page.getByRole("button", { name: "Enroll and build my plan" }).click();
  await page.getByRole("link", { name: "Practise adaptively" }).click();

  await expect(page.getByText("Next concept in your syllabus")).toBeVisible();
  await page.getByRole("button", { name: "Need a hint?" }).click();
  await expect(page.getByText("Hint", { exact: true })).toBeVisible();
  await answerSomething(page);
  await page.getByRole("button", { name: "Check answer" }).click();
  await expect(page.getByText(/^(Correct!|Not quite|Partly right)/)).toBeVisible();
  await expect(page.getByText(/Mastery \d+% →/)).toBeVisible();
  await expect(page.getByText("1 hint step(s) used")).toBeVisible();

  // The access token lives in memory only; the httpOnly refresh cookie (via the Next proxy) restores it.
  await page.goto("/dashboard");
  await page.reload();
  await expect(page.getByRole("heading", { name: /^Good (morning|afternoon|evening), Ravi$/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Today's plan" })).toBeVisible();
  await expect(page.getByText("Exam readiness").first()).toBeVisible();

  await page.getByRole("link", { name: "Revision" }).first().click();
  await expect(page.getByRole("heading", { name: "Coming up (30 days)" })).toBeVisible();
  await expect(page.getByText("Percentage basics")).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await page.waitForURL("**/login");
  await page.goto("/dashboard");
  await page.waitForURL("**/login?next=%2Fdashboard");
});

test("lesson viewer: levels, Telugu, diagram, flashcards, tutor and draft generation", async ({ page }) => {
  await register(page);
  await page.goto("/learn/percentage-basics");
  await expect(page.getByText(/A percentage is a way of writing a number as a part of 100/)).toBeVisible();
  await expect(page.getByRole("img", { name: "Diagram" }).locator("svg")).toBeVisible();
  await page.getByRole("tab", { name: "తెలుగు" }).click();
  await expect(page.getByText(/శాతం \(percentage\)/)).toBeVisible();
  await page.getByRole("tab", { name: "English" }).click();

  const card = page.getByRole("button", { name: "Flip card" });
  await card.click();
  await expect(card).toHaveText("(p/100) × x");

  await page.getByLabel("Question for the tutor").fill("What does per cent mean?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(page.getByText(/Here is what the lesson says/)).toBeVisible();

  // Percentage basics is part of the SSC CGL exam course: learners get reviewed lessons only.
  await page.getByRole("tab", { name: "Expert" }).click();
  await expect(page.getByText("The expert lesson is on its way.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Generate a draft lesson" })).toHaveCount(0);

  await page.getByRole("tab", { name: "Beginner" }).click();
  await page.getByRole("button", { name: "✓ I have learned this" }).click();
  await expect(page.getByText(/first revision is scheduled for day 3/)).toBeVisible();

  // Open courses still let a learner draft a missing lesson.
  await page.goto("/learn/python-loops");
  await page.getByRole("tab", { name: "Expert" }).click();
  await page.getByRole("button", { name: "Generate a draft lesson" }).click();
  await expect(page.getByText(/Draft built from course material without an AI model/)).toBeVisible();
});

test("timed mock test with negative marking and a full report", async ({ page }) => {
  await register(page);
  await page.goto("/courses/ssc-cgl-quant-arithmetic");
  await page.getByRole("link", { name: "Start", exact: true }).click();
  await expect(page.getByText("Question 1 of 20")).toBeVisible();
  await expect(page.getByText(/0.5 deducted for each wrong answer/)).toBeVisible();
  await answerSomething(page);
  await expect(page.getByText(/saved$/)).toBeVisible();
  await page.getByRole("button", { name: "Next →" }).click();
  await expect(page.getByText("Question 2 of 20")).toBeVisible();
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Submit test" }).click();
  await expect(page.getByRole("heading", { name: "Question-by-question review" })).toBeVisible();
  await expect(page.getByText(/\/ 40$/).first()).toBeVisible();
  await expect(page.getByText("1 / 20")).toBeVisible();
});

test("code lab runs examples, then hidden tests and a review", async ({ page }) => {
  await register(page);
  await page.goto("/lab/code");
  await page.getByLabel("Topic").selectOption({ label: "Variables and data types" });
  const editor = page.getByLabel("Code editor");
  await editor.fill("def celsius_to_fahrenheit(c):\n    return c * 9 / 5 + 32\n");
  await page.getByRole("button", { name: "Run examples" }).click();
  await expect(page.getByText("Passed 2 of 2 tests")).toBeVisible();
  await page.getByRole("button", { name: "Submit (runs hidden tests)" }).click();
  await expect(page.getByText("Correct!")).toBeVisible();
  await expect(page.getByText("Passed 4 of 4 tests")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Code review" })).toBeVisible();
});

test("language lab corrects mistakes and scores pronunciation", async ({ page }) => {
  await register(page);
  await page.goto("/lab/language");
  await page.getByLabel("Your message").fill("i am agree with you");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("I agree", { exact: true })).toBeVisible();
  await expect(page.getByText(/'Agree' is already a verb/)).toBeVisible();

  await page.getByRole("tab", { name: "Pronunciation drills" }).click();
  const sentence = (await page.locator("p.text-xl").first().textContent()) ?? "";
  await page.getByLabel("What we heard").fill(sentence);
  await page.getByRole("button", { name: "Score my pronunciation" }).click();
  await expect(page.getByText("Pronunciation match:")).toContainText("100%");
});
