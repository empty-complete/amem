import { expect, test } from "@playwright/test";

test("поиск из верхней строки: точное совпадение кода первым", async ({ page, isMobile }) => {
  await page.goto("./records");
  const box = page.getByRole("combobox", { name: "Поиск по базе" });
  await box.fill("погрешность");
  await box.press("Enter");
  await expect(page).toHaveURL(/\/search\?.*q=/);
  await expect(page.getByText("Точное совпадение кода")).toBeVisible();
  const first = page.getByRole("main").getByRole("link").first();
  await expect(first).toContainText("Погрешность влажности В-2");
  if (!isMobile) await expect(page.getByText("Точное совпадение кода")).toBeInViewport();
});

test("фильтр вида попадает в URL", async ({ page }) => {
  await page.goto("./search?q=погрешность");
  await page.getByRole("button", { name: "Урок" }).click();
  await expect(page).toHaveURL(/kind=lesson(&|$)/);
  await expect(page.getByRole("main").getByRole("link")).toHaveCount(1);
});

test("клавиша / ставит курсор в поиск", async ({ page, isMobile }) => {
  test.skip(isMobile, "клавиатура — на компьютере");
  await page.goto("./records");
  await expect(page.getByRole("link", { name: /Диапазон температуры Т-1/ })).toBeVisible();
  await page.keyboard.press("/");
  await expect(page.getByRole("combobox", { name: "Поиск по базе" })).toBeFocused();
});

test("ошибка службы: что сломалось и «Повторить»", async ({ page }) => {
  await page.goto("./search?q=ошибка");
  await expect(page.getByRole("alert")).toContainText("База не отвечает");
  await expect(page.getByRole("button", { name: "Повторить" })).toBeVisible();
});

test("фильтр списка записей живёт в адресе: перезагрузка оставляет тот же набор", async ({ page }) => {
  await page.goto("./records");
  const count = page.locator(".page-head .count");
  const all = await count.textContent();
  await page.getByRole("combobox", { name: "Статус" }).selectOption("verified");
  await expect(page).toHaveURL(/status=/);
  await expect(count).not.toHaveText(all ?? "");
  const filtered = await count.textContent();
  await page.reload();
  await expect(page.getByRole("combobox", { name: "Статус" })).toHaveValue("verified");
  await expect(count).toHaveText(filtered ?? "");
  await page.getByRole("button", { name: "Сбросить" }).click();
  await expect(count).toHaveText(all ?? "");
});
