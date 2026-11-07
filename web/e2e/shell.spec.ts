import { expect, test } from "@playwright/test";

test("папки и «Все записи»", async ({ page }) => {
  await page.goto("./records");
  await expect(page.getByRole("heading", { level: 1, name: "Все записи" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Диапазон температуры Т-1/ })).toBeVisible();
  await page
    .getByRole("navigation", { name: "Папки" })
    .getByRole("link", { name: /^Архив/ })
    .click();
  await expect(page).toHaveURL(/folder=/);
  await expect(page.getByRole("heading", { level: 1, name: "Архив" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Корпус МС-1 из алюминия/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /Ставим мачту/ })).toHaveCount(0);
});

test("страница не прокручивается, прокручивается панель", async ({ page, isMobile }) => {
  test.skip(isMobile, "на телефоне страница прокручивается целиком");
  await page.goto("./records");
  await expect(page.getByRole("link", { name: /Диапазон температуры Т-1/ })).toBeVisible();
  const page_scroll = await page.evaluate(
    () => document.documentElement.scrollHeight <= document.documentElement.clientHeight,
  );
  expect(page_scroll).toBe(true);
  const main_scroll = await page.locator("main").evaluate((m) => m.scrollHeight > m.clientHeight);
  expect(main_scroll).toBe(true);
});

test("тема и язык переключаются в настройках", async ({ page }) => {
  await page.goto("./settings");
  await page.getByRole("radio", { name: "Тёмная" }).check({ force: true });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("radio", { name: "English" }).check({ force: true });
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});
