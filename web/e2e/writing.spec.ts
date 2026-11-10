import { expect, type Page, test } from "@playwright/test";

const E3 = "ent:0193b7c2-5e1a-7d40-9f2e-000000000003";
const N1 = "atm:0193b7c2-5e1a-7d40-9f2e-00000000001e";
const A3 = "atm:0193b7c2-5e1a-7d40-9f2e-00000000000b";
const WINDOW = 6500;

const skyCount = (page: Page) =>
  page.evaluate(
    () => (window as unknown as { __amemoSky?: { count: () => number } }).__amemoSky?.count() ?? 0,
  );

test("N на странице объекта: вопрос из текста, звезда загорается, после окна — в «Заметках и решениях»", async ({
  page,
  isMobile,
}) => {
  test.skip(isMobile, "клавиатура — на компьютере");
  await page.goto(`./entity/${E3}`);
  await expect(page.getByRole("heading", { level: 1, name: "Датчик влажности В-2" })).toBeVisible();
  await expect.poll(() => skyCount(page), { timeout: 10_000 }).toBeGreaterThan(0);
  const before = await skyCount(page);
  await page.locator("main h1").click();
  await page.keyboard.press("n");
  const dlg = page.getByRole("dialog", { name: "Новая запись" });
  await expect(dlg).toContainText("О чём: Датчик влажности В-2");
  await dlg.getByRole("textbox", { name: "Текст записи" }).fill("Нужен ли козырёк над В-2?");
  await expect(dlg.getByRole("button", { name: /Вид: Вопрос/ })).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Записано: вопрос")).toBeVisible();
  await expect.poll(() => skyCount(page)).toBe(before + 1);
  await page.waitForTimeout(WINDOW);
  await expect(
    page
      .getByRole("region", { name: "Заметки и решения" })
      .getByRole("link", { name: /Нужен ли козырёк над В-2\?/ }),
  ).toBeVisible();
});

test("«Отменить» в окне — ничего не записано", async ({ page }) => {
  await page.goto(`./entity/${E3}`);
  const add = page.getByRole("textbox", { name: "Добавить заметку" });
  await add.fill("Временная мысль");
  await add.press("Enter");
  await page.getByRole("button", { name: "Отменить" }).click();
  await page.waitForTimeout(WINDOW);
  await expect(page.getByText("Временная мысль")).toHaveCount(0);
});

test("пустое поле карточки — значение; «Принять» умолчание — полоса полноты растёт", async ({ page }) => {
  await page.goto(`./entity/${E3}`);
  const cond = page.getByRole("region", { name: "Условия" });
  await cond.getByRole("button", { name: "Нужно" }).click();
  await cond.getByRole("textbox", { name: "Рабочая температура" }).fill("-40");
  await cond.getByRole("textbox", { name: "Рабочая температура" }).press("Enter");
  await page.getByRole("region", { name: "Опрос" }).getByRole("button", { name: "Принять" }).click();
  await page.waitForTimeout(WINDOW);
  await expect(cond.getByText("−40 °C")).toBeVisible();
  await expect(page.getByRole("img", { name: /Известно 4 из 7/ })).toBeVisible();
});

test("правка своей записи: заголовок → новая ревизия", async ({ page }) => {
  await page.goto(`./atom/${N1}`);
  await page.getByRole("button", { name: /^Править, (⌘|Ctrl\+)E$/ }).click();
  await page.getByRole("textbox", { name: "Заголовок" }).fill("Проверить мачту после бури");
  await page.getByRole("main").getByRole("button", { name: "Записать" }).click();
  await page.waitForTimeout(WINDOW);
  await expect(page.getByRole("heading", { level: 1, name: "Проверить мачту после бури" })).toBeVisible();
  await expect(page.getByText("ревизия 2")).toBeVisible();
});

test("чужая запись — «Поставить на проверку»", async ({ page }) => {
  await page.goto(`./atom/${A3}`);
  await page.getByRole("button", { name: /— её не правят/ }).click();
  await page.getByRole("menuitem", { name: "Поставить на проверку" }).click();
  await expect(page.getByText("Поставлено на проверку")).toBeVisible();
});

test("запись по шаблону пакета с источником-таблицей", async ({ page, isMobile }) => {
  test.skip(isMobile, "протяжка по ячейкам — мышью");
  await page.goto(`./new?about=${encodeURIComponent(E3)}&kind=sensor_reading`);
  await page.getByRole("textbox", { name: "Заголовок" }).fill("Влажность 7 ноября: 87 %");
  await page.getByRole("textbox", { name: "Влажность" }).fill("87");
  await page.getByLabel("Когда").fill("2026-11-07");
  await page.getByRole("button", { name: "Добавить источник" }).click();
  const dlg = page.getByRole("dialog", { name: "Источник" });
  await dlg.getByRole("button", { name: /Наблюдения_ноябрь.xlsx/ }).click();
  await page.getByRole("tab", { name: "В-2" }).click();
  const table = page.getByRole("table", { name: "Лист В-2" });
  const from = table.getByRole("cell", { name: "99", exact: true }).first();
  const to = table.getByRole("cell", { name: "85", exact: true }).first();
  await from.dispatchEvent("pointerdown", { bubbles: true });
  await to.dispatchEvent("pointerenter");
  await to.dispatchEvent("pointerup", { bubbles: true });
  await expect(page.getByRole("textbox", { name: "Диапазон" })).toHaveValue(/^B\d+:C\d+$/);
  await page.getByRole("button", { name: "Готово" }).click();
  await expect(page.getByRole("region", { name: "Источники" })).toContainText("Наблюдения_ноябрь.xlsx");
  await page.getByRole("main").getByRole("button", { name: "Записать" }).click();
  await page.waitForTimeout(WINDOW);
  await page.goto("./records");
  await expect(page.getByRole("link", { name: /Влажность 7 ноября: 87 %/ })).toBeVisible();
});

test("неверная цитата — замечание уровня 2 у источника и «Взять это»", async ({ page }) => {
  await page.goto(`./new?about=${encodeURIComponent(E3)}&kind=fact`);
  await page.getByRole("textbox", { name: "Заголовок" }).fill("Погрешность В-2 — 2 %");
  await page.getByRole("button", { name: "Добавить источник" }).click();
  const dlg = page.getByRole("dialog", { name: "Источник" });
  await dlg.getByRole("button", { name: /Руководство_МС-1.pdf/ }).click();
  await dlg.getByRole("textbox", { name: /Цитата/ }).fill("Погрешность ±2 % во всём диапазоне");
  await dlg.getByRole("button", { name: "Готово" }).click();
  await page.getByRole("main").getByRole("button", { name: "Записать" }).click();
  await page.waitForTimeout(WINDOW);
  const alert = page.getByRole("alert").filter({ hasText: "Цитаты на странице нет" });
  await expect(alert).toBeVisible();
  await alert.getByRole("button", { name: "Взять это" }).click();
  await expect(page.getByRole("region", { name: "Источники" })).toContainText("Погрешность ±2 % в диапазоне");
});

test("свой вид из конструктора — сразу в /new", async ({ page }) => {
  await page.goto("./settings");
  await page.getByRole("button", { name: "Настроить виды" }).click();
  const dlg = page.getByRole("dialog", { name: "Мои виды" });
  await dlg.getByRole("button", { name: "Вид" }).click();
  await dlg.getByRole("textbox", { name: "Имя вида" }).fill("Обход площадки");
  await dlg.getByRole("button", { name: "Добавить свойство" }).click();
  await dlg.getByRole("textbox", { name: "Имя свойства" }).fill("Что нашли");
  await dlg.getByRole("button", { name: "Сохранить вид" }).click();
  await expect(dlg.getByText("Вид «Обход площадки» сохранён")).toBeVisible();
  await page.keyboard.press("Escape");
  await page.goto("./new?kind=obkhod_ploshchadki");
  await expect(page.getByRole("button", { name: /Вид: Обход площадки/ })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Что нашли" })).toBeVisible();
});

test("перенос в папку сохраняется, даже если сразу обновить страницу; «Отменить» возвращает", async ({
  page,
}) => {
  const move = async () => {
    await page.goto(`./atom/${N1}`);
    await page.getByRole("button", { name: "Ещё" }).click();
    await page.getByRole("menuitem", { name: "Переместить в папку" }).click();
    await page.getByRole("radio", { name: "Архив" }).check({ force: true });
    const done = page.waitForResponse((r) => r.request().method() === "PATCH" && r.url().endsWith("/folder"));
    await page.getByRole("dialog").getByRole("button", { name: "Переместить в папку" }).click();
    await expect(page.getByText("Перенесено в «Архив»")).toBeVisible();
    await done;
  };
  const inArchive = () => page.getByRole("main").getByRole("link", { name: /Проверить крепление мачты/ });
  await move();
  // не ждём окна отмены: перенос уже у службы
  await page.goto(`./records?folder=${encodeURIComponent("Архив")}`);
  await expect(inArchive()).toBeVisible();
  await page.goto(`./atom/${N1}`);
  await page.getByRole("button", { name: "Ещё" }).click();
  await page.getByRole("menuitem", { name: "Переместить в папку" }).click();
  await page.getByRole("radio", { name: "Без папки" }).check({ force: true });
  await page.getByRole("dialog").getByRole("button", { name: "Переместить в папку" }).click();
  const back = page.waitForResponse(
    (r) => r.request().method() === "PATCH" && r.request().postData()?.includes("Архив") === true,
  );
  await page.getByRole("button", { name: "Отменить" }).click();
  await back;
  await page.goto(`./records?folder=${encodeURIComponent("Архив")}`);
  await expect(inArchive()).toBeVisible();
});

test("загрузка файла в «+ Источник»", async ({ page }) => {
  await page.goto(`./new?about=${encodeURIComponent(E3)}`);
  await page.getByRole("button", { name: "Добавить источник" }).click();
  await page.locator('input[type="file"]').setInputFiles({
    name: "Обход_ноябрь.md",
    mimeType: "text/markdown",
    buffer: Buffer.from("# Обход\nвсё в порядке"),
  });
  await expect(page.getByRole("heading", { name: "Обход_ноябрь.md" })).toBeVisible();
});

test("конструктор видов на низком экране: длинная форма листается, «Сохранить вид» достижима", async ({
  page,
  isMobile,
}) => {
  test.skip(isMobile, "высота окна задаётся явно");
  await page.setViewportSize({ width: 1280, height: 520 });
  await page.goto("./settings");
  await page.getByRole("button", { name: "Настроить виды" }).click();
  const dlg = page.getByRole("dialog", { name: "Мои виды" });
  await dlg.getByRole("button", { name: "Вид", exact: true }).click();
  await dlg.getByRole("textbox", { name: "Имя вида" }).fill("Длинный обход");
  for (const name of ["Что нашли", "Где", "Кто смотрел", "Что сделали"]) {
    await dlg.getByRole("button", { name: "Добавить свойство" }).click();
    await dlg.getByRole("textbox", { name: "Имя свойства" }).last().fill(name);
  }
  await dlg.getByRole("button", { name: "Сохранить вид" }).click();
  await expect(dlg.getByText("Вид «Длинный обход» сохранён")).toBeVisible();
});
