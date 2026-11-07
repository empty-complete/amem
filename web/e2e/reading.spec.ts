import { expect, test } from "@playwright/test";

const A3 = "atm:0193b7c2-5e1a-7d40-9f2e-00000000000b";

test("от поиска к записи: заголовок, формула, цитата подсвечена на странице PDF", async ({ page }) => {
  await page.goto("./search?q=погрешность");
  await page
    .getByRole("main")
    .getByRole("link", { name: /Погрешность влажности В-2/ })
    .first()
    .click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Погрешность влажности В-2: ±2 %" }),
  ).toBeVisible();
  await expect(page.locator(".prose .katex-display")).toBeVisible();
  const panel = page.getByRole("complementary", { name: "Источник" });
  await expect(panel).toContainText("Цитата найдена");
  await expect(panel.locator(".textLayer mark.q").first()).toBeAttached({ timeout: 15_000 });
  await expect(panel.locator(".pdf__note")).toHaveCount(0);
});

test("режимы записи: исходник и вид для агента", async ({ page }) => {
  await page.goto(`./atom/${A3}`);
  await page.getByRole("button", { name: "Исходник" }).click();
  await expect(page).toHaveURL(/view=source/);
  await expect(page.getByLabel("Исходник записи")).toContainText("kind: parameter");
  await page.getByRole("button", { name: "Ещё" }).click();
  await page.getByRole("menuitem", { name: "Как видит агент" }).click();
  await expect(page.getByRole("region", { name: "Запись, как её получает агент" })).toContainText(
    "verdict: ok",
  );
});

test("от записи к объекту: полнота, «Нужно», расхождение раскрывается", async ({ page }) => {
  await page.goto(`./atom/${A3}`);
  await page.getByLabel("Свойства").getByRole("link", { name: "Датчик влажности В-2" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Датчик влажности В-2" })).toBeVisible();
  await expect(page.getByRole("img", { name: /Известно 2 из 7/ })).toBeVisible();
  await expect(page.getByText("Нужно")).toBeVisible();
  await page.getByRole("button", { name: /2 значения/ }).click();
  await expect(page.getByRole("list", { name: "Кандидаты" })).toContainText("расхождение до 12 %");
});

test("от записи к источнику: лист с цитируемыми ячейками", async ({ page }) => {
  await page.goto("./atom/atm:0193b7c2-5e1a-7d40-9f2e-000000000016");
  const panel = page.getByRole("complementary", { name: "Источник" });
  await panel.getByRole("radio", { name: "Источник 2" }).click();
  await panel.getByRole("link", { name: "Страница источника" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Наблюдения ноябрь" })).toBeVisible();
  await expect(page.getByRole("table", { name: "Лист В-2" }).locator("td[data-cited]")).toHaveCount(12);
});

test("изменения: дни и фильтр «Люди»", async ({ page }) => {
  await page.goto("./changes");
  await expect(page.getByRole("region", { name: "Сегодня" })).toBeVisible();
  await page.getByRole("radio", { name: "Люди" }).click();
  await expect(page).toHaveURL(/who=person/);
  await expect(page.getByText("(модель)")).toHaveCount(0);
});

test("⌘K: командная строка открывает команду", async ({ page, isMobile }) => {
  test.skip(isMobile, "клавиатура — на компьютере");
  await page.goto("./records");
  await expect(page.getByRole("link", { name: /Диапазон температуры Т-1/ })).toBeVisible();
  await page.keyboard.press("Control+k");
  await page.keyboard.type("изменен");
  await page.getByRole("option", { name: /Открыть изменения/ }).click();
  await expect(page).toHaveURL(/\/changes/);
});
