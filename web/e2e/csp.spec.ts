import { expect, type Page, test } from "@playwright/test";

// Сборка с моками под CSP службы (vite preview, проект «csp»): ни одного нарушения и ни одной ошибки в консоли.
const A3 = "atm:0193b7c2-5e1a-7d40-9f2e-00000000000b";
const E3 = "ent:0193b7c2-5e1a-7d40-9f2e-000000000003";

async function watch(page: Page) {
  const problems: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") problems.push(`console: ${m.text()}`);
  });
  page.on("pageerror", (e) => problems.push(`page: ${e.message}`));
  await page.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (e) =>
      console.error(
        `CSP: ${e.violatedDirective} ${e.blockedURI} ${e.sourceFile}:${e.lineNumber}:${e.columnNumber}`,
      ),
    );
  });
  return problems;
}

test("CSP службы: тема и zod из boot.js до модулей", async ({ page }) => {
  const problems = await watch(page);
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("./records");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  expect(problems).toEqual([]);
});

test("CSP службы: небо, PDF с цитатой, формулы, редактор, таблица, проверка", async ({ page }) => {
  const problems = await watch(page);
  await page.goto("./");
  await expect(page.locator("canvas").first()).toBeVisible();
  // 3D (three.js) — если в этом браузере есть WebGL
  const three = page.getByRole("button", { name: "3D", exact: true });
  if (await three.isEnabled()) {
    await three.click();
    await expect(three).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator("canvas").first()).toBeVisible();
  }
  await page.goto(`./atom/${A3}`);
  await expect(page.locator(".textLayer mark, mark.q").first()).toBeVisible({ timeout: 15_000 });
  await expect(page.locator(".katex").first()).toBeVisible();
  await page.goto(`./atom/${A3}?view=source`);
  await expect(page.locator(".cm-editor").first()).toBeVisible();
  await page.goto("./object/0193b7c2-5e1a-7d40-9f2e-0000000000a2");
  await expect(page.locator("table").first()).toBeVisible();
  await page.goto(`./entity/${E3}`);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.goto("./review/5f0c2a8e-1d3b-4c6a-9e7f-0a1b2c3d4e01");
  await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
  await page.goto("./bundles");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  expect(problems).toEqual([]);
});
