import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

// e2e против настоящей службы на образце tools/seed_sample.py (метеостанция МС-1). Ссылки на записи — через
// поиск службы: идентификаторы у каждого запуска свои. Тесты идут по порядку и меняют базу.
const WINDOW = 6500;

function watch(page: Page) {
  const problems: string[] = [];
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const where = m.location().url;
    if (/favicon/.test(where)) return;
    problems.push(`${m.text()} @ ${where}`);
  });
  page.on("pageerror", (e) => problems.push(`page: ${e.message}`));
  return problems;
}

async function refOf(page: Page, q: string) {
  const r = await page.request.get(`/api/v1/search?q=${encodeURIComponent(q)}`);
  const items = ((await r.json()) as { items: { ref: string; label: string }[] }).items;
  const hit = items.find((x) => x.label.startsWith(q));
  if (!hit) throw new Error(`в образце нет записи «${q}»`);
  return hit.ref;
}

async function axe(page: Page) {
  const r = await new AxeBuilder({ page }).analyze();
  expect(r.violations.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
}

test("главная: небо и поиск по базе", async ({ page }) => {
  const problems = watch(page);
  await page.goto("./");
  await expect(page.locator("canvas").first()).toBeVisible();
  await expect(page.getByRole("banner").getByRole("link", { name: /Проверка/ })).toContainText("2");
  await page.getByRole("combobox", { name: "Поиск по базе" }).fill("погрешность влажности");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("link", { name: /Погрешность влажности В-2: ±2 %/ }).first()).toBeVisible();
  await axe(page);
  expect(problems).toEqual([]);
});

test("запись: свойства, путь по part_of, цитата подсвечена на странице PDF, формула", async ({ page }) => {
  const problems = watch(page);
  await page.goto(`./atom/${await refOf(page, "Погрешность влажности В-2")}`);
  await expect(
    page.getByRole("heading", { level: 1, name: "Погрешность влажности В-2: ±2 %" }),
  ).toBeVisible();
  await expect(page.getByRole("navigation", { name: "О чём" })).toContainText("Метеостанция МС-1");
  await expect(page.locator(".textLayer mark, mark.q").first()).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Цитата найдена").first()).toBeVisible();
  await expect(page.locator(".katex").first()).toBeVisible();
  await expect(page.getByText("Параметр", { exact: true }).first()).toBeVisible();
  await axe(page);
  expect(problems).toEqual([]);
});

test("содержание записи на службе: формула с обозначениями и таблица с единицами", async ({ page }) => {
  const problems = watch(page);
  await page.goto(`./atom/${await refOf(page, "Точка росы по формуле Магнуса")}`);
  const formula = page.getByRole("region", { name: "Формула" });
  await expect(formula.locator(".katex").first()).toBeVisible();
  await expect(formula.getByRole("definition").first()).toContainText("точка росы");
  await page.goto(`./atom/${await refOf(page, "В-2 и психрометр")}`);
  const table = page.getByRole("region", { name: "Таблица", exact: true });
  await expect(table.getByRole("columnheader", { name: "В-2, %" })).toBeVisible();
  await expect(table.getByRole("row")).toHaveCount(4);
  await axe(page);
  expect(problems).toEqual([]);
});

test("запись по N: полный редактор, «Отменить» — ничего нет; без отмены — запись в «Изменениях»", async ({
  page,
}) => {
  const problems = watch(page);
  const write = async (title: string) => {
    await page.goto("./records");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.keyboard.press("n");
    await expect(page).toHaveURL(/\/new/);
    await page.getByRole("textbox", { name: "Заголовок" }).fill(title);
    await page.getByRole("main").getByRole("button", { name: "Записать" }).click();
  };
  await write("Отменённая мысль о мачте");
  await page.getByRole("button", { name: "Отменить" }).click();
  await page.waitForTimeout(WINDOW);
  const none = await page.request.get(`/api/v1/search?q=${encodeURIComponent("Отменённая мысль")}`);
  expect(((await none.json()) as { items: unknown[] }).items).toEqual([]);

  await write("Проверить растяжки мачты после ветра");
  await expect(page.getByText(/^Записано/)).toBeVisible();
  await page.waitForTimeout(WINDOW);
  await page.goto("./changes");
  await expect(page.getByText("Проверить растяжки мачты после ветра").first()).toBeVisible();
  expect(problems).toEqual([]);
});

test("проверка: Y — решено в службе после окна; второй раз — «Уже решено»", async ({ page }) => {
  const problems = watch(page);
  // пункты образца — смысловая проверка черновиков модели: вкладка «Разбирает модель»
  await page.goto("./review?who=model");
  const list = page.getByRole("listbox", { name: "Очередь проверки" });
  await expect(list.getByRole("option")).toHaveCount(2);
  await list.getByRole("option").first().click();
  const id = new URL(page.url()).pathname.split("/").pop() as string;
  // похожие записи — ссылками на записи, а не @именами пачки (ядро: check._details)
  const issues = page.getByRole("region", { name: "Замечания проверки" });
  await expect(issues.getByRole("link").first()).toBeVisible();
  await expect(issues).not.toContainText("@");
  await page.keyboard.press("y");
  await expect(page.getByText("Подтверждено", { exact: true })).toBeVisible();
  await page.waitForTimeout(WINDOW);
  const item = await page.request.get(`/api/v1/review/items/${id}`);
  expect(((await item.json()) as { item: { state: string } }).item.state).toBe("done");
  await expect(page.getByRole("banner").getByRole("link", { name: /Проверка/ })).toContainText("1");
  const again = await page.request.post(`/api/v1/review/items/${id}/resolve`, {
    data: { outcome: "confirmed" },
    headers: { origin: new URL(page.url()).origin },
  });
  expect(again.status()).toBe(409);
  await axe(page);
  expect(problems).toEqual([]);
});

test("очередь по документам: пункт знает документ, группа с его именем", async ({ page }) => {
  const problems = watch(page);
  const items = (await (await page.request.get("/api/v1/review/items?state=queued&limit=500")).json()) as {
    reason: string;
    source: { object_name: string } | null;
  }[];
  const hit = items.find((i) => i.source?.object_name);
  const named = hit?.source?.object_name;
  expect(named, "у открытого пункта образца есть документ").toBeTruthy();
  // смысловую проверку показывает вкладка «Разбирает модель», остальное — «Ждут вас»
  await page.goto(`./review?group=source${hit?.reason === "semantic" ? "&who=model" : ""}`);
  const list = page.getByRole("listbox", { name: "Очередь проверки" });
  await expect(list.locator(".qhead").first()).toContainText(named as string);
  await axe(page);
  expect(problems).toEqual([]);
});

test("карточка по профилю пакета-образца: группы словами, «спросить», умолчание к принятию", async ({
  page,
}) => {
  const problems = watch(page);
  await page.goto(`./entity/${await refOf(page, "Датчик влажности В-2")}?tab=card`);
  const measure = page.getByRole("region", { name: "Измерение", exact: true });
  await expect(measure).toContainText(/диапазон влажности/i);
  const env = page.getByRole("region", { name: "Условия работы", exact: true });
  await expect(env).toContainText("спросить: изготовитель");
  await expect(env).toContainText("нужно, если площадка зимой ниже −30 °C");
  await expect(env).toContainText("паспорт");
  await expect(env.getByRole("button", { name: "Принять" })).toBeVisible();
  await axe(page);
  expect(problems).toEqual([]);
});

test("папки: создать, перенести запись из меню, переименовать, удалить пустую", async ({ page }) => {
  const problems = watch(page);
  const ref = await refOf(page, "Проверить растяжки мачты после ветра");
  await page.goto("./records");
  const nav = page.getByRole("navigation", { name: "Папки" });
  await nav.getByRole("button", { name: "Папка", exact: true }).click();
  await page.getByRole("textbox", { name: "Имя новой папки" }).fill("Обходы");
  await page.keyboard.press("Enter");
  await expect(nav.getByRole("button", { name: /^Обходы/ })).toBeVisible();

  await page.goto(`./atom/${ref}`);
  await page.getByRole("button", { name: "Ещё" }).click();
  await page.getByRole("menuitem", { name: "Переместить в папку" }).click();
  await page.getByRole("radio", { name: "Обходы" }).check({ force: true });
  await page.getByRole("dialog").getByRole("button", { name: "Переместить в папку" }).click();
  await page.waitForTimeout(WINDOW);
  await page.goto(`./records?folder=${encodeURIComponent("Обходы")}`);
  await expect(page.getByRole("link", { name: /Проверить растяжки мачты/ })).toBeVisible();

  await nav.getByRole("button", { name: "Папка «Обходы»: действия" }).click();
  await page.getByRole("menuitem", { name: "Переименовать" }).click();
  await page.getByRole("textbox").filter({ hasText: "" }).last().fill("Обходы площадки");
  await page.keyboard.press("Enter");
  await expect(nav.getByRole("button", { name: /^Обходы площадки/ })).toBeVisible();
  const moved = await page.request.get(`/api/v1/records/${ref}`);
  expect(((await moved.json()) as { folder: string }).folder).toBe("Обходы площадки");

  await page.request.patch(`/api/v1/records/${ref}/folder`, {
    data: { folder: null },
    headers: { origin: new URL(page.url()).origin },
  });
  await page.reload();
  await nav.getByRole("button", { name: "Папка «Обходы площадки»: действия" }).click();
  await page.getByRole("menuitem", { name: "Удалить" }).click();
  await expect(nav.getByRole("button", { name: /^Обходы площадки/ })).toHaveCount(0);
  expect(problems).toEqual([]);
});

test("подборка: антология — zip и HTML-отчёт", async ({ page }) => {
  const problems = watch(page);
  await page.goto("./bundles");
  await page.getByRole("checkbox", { name: /Антология: проверенное и предпочтительное/ }).check();
  await page.getByRole("textbox", { name: "Заголовок отчёта" }).fill("Метеостанция");
  await page.getByRole("button", { name: "Собрать подборку" }).click();
  await expect(page.getByRole("heading", { name: /Подборка собрана/ })).toBeVisible();
  const report = await page.getByRole("link", { name: "Открыть отчёт" }).getAttribute("href");
  const zip = await page
    .getByRole("link", { name: /zip|Скачать/ })
    .first()
    .getAttribute("href");
  const html = await page.request.get(report as string);
  expect(await html.text()).toContain("Метеостанция");
  expect((await page.request.get(zip as string)).headers()["content-type"]).toContain("zip");
  expect(problems).toEqual([]);
});

test("«Мои виды» на службе: свой вид, запись по его форме, удалить вид с записями — отказ словами", async ({
  page,
}) => {
  // длинный путь по службе: сохранение вида, запись с окном отмены 6,5 с, снова конструктор
  test.setTimeout(90_000);
  const problems = watch(page);
  await page.goto("./settings");
  await page.getByRole("button", { name: "Настроить виды" }).click();
  const dlg = page.getByRole("dialog", { name: "Мои виды" });
  await dlg.getByRole("button", { name: "Вид", exact: true }).click();
  await dlg.getByRole("textbox", { name: "Имя вида" }).fill("Обход площадки");
  await dlg.getByRole("button", { name: "Добавить свойство" }).click();
  await dlg.getByRole("textbox", { name: "Имя свойства" }).fill("Что нашли");
  await dlg.getByRole("button", { name: "Сохранить вид" }).click();
  await expect(dlg.getByText("Вид «Обход площадки» сохранён")).toBeVisible();
  await page.keyboard.press("Escape");

  // форма вида — от службы: запись уходит с полем свойства и проходит проверку
  await page.goto("./new?kind=obkhod_ploshchadki");
  await page.getByRole("textbox", { name: "Заголовок" }).fill("Обход 10 ноября");
  await page.getByRole("textbox", { name: "Что нашли" }).fill("растяжка ослабла");
  await page.getByRole("main").getByRole("button", { name: "Записать" }).click();
  await page.waitForTimeout(WINDOW);
  const ref = await refOf(page, "Обход 10 ноября");
  const rec = (await (await page.request.get(`/api/v1/records/${ref}`)).json()) as {
    payload: { kind: string; qualifiers?: { value_text?: string }[] };
  };
  expect(rec.payload.kind).toBe("obkhod_ploshchadki");
  expect(rec.payload.qualifiers?.[0]?.value_text).toBe("растяжка ослабла");

  await page.goto("./settings");
  await page.getByRole("button", { name: "Настроить виды" }).click();
  await dlg.getByRole("button", { name: "Обход площадки" }).click();
  await dlg.getByRole("button", { name: "Удалить вид" }).click();
  await expect(dlg).toContainText("есть записи");
  expect(problems.filter((p) => !p.includes("409"))).toEqual([]);
});

test("загрузка файла на службу: новый — объект, тот же ещё раз — тот же объект", async ({ page }) => {
  const problems = watch(page);
  const file = {
    name: "Обход_ноябрь.md",
    mimeType: "text/markdown",
    buffer: Buffer.from("# Обход\nвсё в порядке\n"),
  };
  for (let i = 0; i < 2; i++) {
    await page.goto("./new");
    await page.getByRole("button", { name: "Добавить источник" }).click();
    await page.locator('input[type="file"]').setInputFiles(file);
    await expect(page.getByRole("heading", { name: "Обход_ноябрь.md" })).toBeVisible();
  }
  const found = (await (await page.request.get("/api/v1/objects?q=Обход_ноябрь")).json()) as {
    items: unknown[];
  };
  expect(found.items).toHaveLength(1);
  expect(problems).toEqual([]);
});
