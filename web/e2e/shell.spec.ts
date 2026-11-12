import { expect, test } from "@playwright/test";

test("папки: запись из дерева, папка списком из меню", async ({ page, isMobile }) => {
  await page.goto("./records");
  await expect(page.getByRole("heading", { level: 1, name: "Все записи" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Диапазон температуры Т-1/ })).toBeVisible();
  const menu = page.getByRole("button", { name: "Меню" });
  if (isMobile) {
    // на телефоне папки за кнопкой меню, первый экран — список
    await expect(page.getByRole("navigation", { name: "Папки" })).toBeHidden();
    await menu.click();
    await expect(menu).toHaveAttribute("aria-expanded", "true");
  } else {
    await expect(menu).toBeHidden();
  }
  const nav = page.getByRole("navigation", { name: "Папки" });
  // папка раскрывается в панели; запись открывается из неё, а в центре — запись, не список
  await nav.getByRole("button", { name: /^Станция 2024/ }).click();
  await nav.getByRole("link", { name: /Корпус МС-1 из алюминия/ }).click();
  await expect(page).toHaveURL(/\/(atom|entity)\//);
  // в центре — запись, а не список папки
  await expect(page.locator(".page-head")).toHaveCount(0);
  if (isMobile) {
    await expect(nav).toBeHidden();
    await menu.click();
  }
  // широкий список — правой кнопкой по папке, «Открыть списком»
  await nav.getByRole("button", { name: /^Архив/ }).click({ button: "right" });
  await page.getByRole("menuitem", { name: "Открыть списком" }).click();
  await expect(page).toHaveURL(/folder=/);
  await expect(page.getByRole("heading", { level: 1, name: "Архив" })).toBeVisible();
  await expect(page.getByRole("main").getByRole("link", { name: /Корпус МС-1 из алюминия/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /Ставим мачту/ })).toHaveCount(0);
});

test("на телефоне меню ведёт в разделы и страница не шире экрана", async ({ page, isMobile }) => {
  test.skip(!isMobile, "только телефон");
  await page.goto("./atom/atm:0193b7c2-5e1a-7d40-9f2e-00000000000b");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const wide = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(wide).toBeLessThanOrEqual(0);
  await page.getByRole("button", { name: "Меню" }).click();
  await page
    .getByRole("navigation", { name: "Папки" })
    .getByRole("link", { name: /^Проверка/ })
    .click();
  await expect(page).toHaveURL(/\/review/);
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

test("язык меняется в настройках и переживает перезагрузку", async ({ page }) => {
  await page.goto("./settings");
  await page.getByRole("combobox", { name: "Язык" }).selectOption("en");
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
});

test("окно настроек: Ctrl+, разделы и поиск; небо на главной выключается как плагин ядра", async ({
  page,
  isMobile,
}) => {
  test.skip(isMobile, "клавиши — на компьютере");
  await page.goto("./");
  // клавиши оболочки — после первой отрисовки
  await expect(page.getByRole("navigation", { name: "Папки" })).toBeVisible();
  await page.keyboard.press("Control+Comma");
  const win = page.getByRole("dialog", { name: "Настройки" });
  await expect(win.getByRole("button", { name: "Общие" })).toHaveAttribute("aria-current", "page");
  await win.getByRole("searchbox", { name: "Поиск по настройкам" }).fill("папк");
  // поле пути с подсказками папок (datalist) — для доступности это combobox
  await expect(win.getByRole("combobox", { name: "Куда класть новые записи" })).toBeVisible();
  await win.getByRole("searchbox", { name: "Поиск по настройкам" }).fill("");
  await win.getByRole("button", { name: "Плагины ядра" }).click();
  await win.getByRole("switch", { name: "Небо на главной" }).uncheck();
  await win.getByRole("button", { name: "Закрыть" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Все записи" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Все записи" })).toBeVisible();
});
