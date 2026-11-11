import { expect, type Page, test } from "@playwright/test";

const E3 = "ent:0193b7c2-5e1a-7d40-9f2e-000000000003";
const A3 = "atm:0193b7c2-5e1a-7d40-9f2e-00000000000b";

type Handle = {
  screen: (id: string) => { x: number; y: number } | null;
  count: () => number;
  dim: () => string[];
  emit: (d: unknown) => void;
};

/** Ждём, пока небо уложится и вернёт экранные координаты звезды. */
async function star(page: Page, id: string) {
  await expect
    .poll(
      () =>
        page.evaluate(
          (i) => (window as unknown as { __amemoSky?: Handle }).__amemoSky?.screen(i) ?? null,
          id,
        ),
      {
        timeout: 15_000,
      },
    )
    .not.toBeNull();
  // на телефоне небо ниже папок — сначала прокрутить к нему
  await page.getByRole("application").first().scrollIntoViewIfNeeded();
  // ждём, пока укладка остынет и вписывание закончится: звезда стоит на месте
  const at = () =>
    page.evaluate((i) => (window as unknown as { __amemoSky: Handle }).__amemoSky.screen(i), id) as Promise<{
      x: number;
      y: number;
    }>;
  let prev = await at();
  for (let k = 0; k < 40; k++) {
    await page.waitForTimeout(250);
    const cur = await at();
    if (Math.hypot(cur.x - prev.x, cur.y - prev.y) < 0.5) {
      await page.waitForTimeout(500);
      const last = await at();
      if (Math.hypot(last.x - cur.x, last.y - cur.y) < 0.5) return last;
    }
    prev = cur;
  }
  return prev;
}

test("главная — небо: итог, звезда открывает карточку, «Открыть» ведёт на запись", async ({ page }) => {
  await page.goto("./");
  await expect(page.getByText("23 записи о 8 объектах, 3 ждут решения")).toBeVisible();
  const p = await star(page, A3);
  await page.mouse.click(p.x, p.y);
  const card = page.getByRole("region", { name: "Выбранная звезда" });
  await expect(card).toContainText("Погрешность влажности В-2: ±2 %");
  await card.getByRole("link", { name: "Открыть" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Погрешность влажности В-2: ±2 %" }),
  ).toBeVisible();
});

test("фильтр «Объекты» приглушает записи и попадает в адрес", async ({ page }) => {
  await page.goto("./");
  await star(page, E3);
  await page.getByRole("button", { name: "Объекты" }).click();
  await expect(page).toHaveURL(/f=object/);
  const dim = await page.evaluate(() => (window as unknown as { __amemoSky: Handle }).__amemoSky.dim());
  expect(dim).toContain(A3);
  expect(dim).not.toContain(E3);
});

test("клавиатура: фокус на небе, стрелка выбирает, Enter открывает", async ({ page, isMobile }) => {
  test.skip(isMobile, "клавиатура — на компьютере");
  await page.goto(`./entity/${E3}`);
  await star(page, E3);
  await page.getByRole("application", { name: /^Небо:/ }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("region", { name: "Выбранная звезда" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("region", { name: "Выбранная звезда" })).toHaveCount(0);
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/(atom|entity)\//);
});

test("глубина 1 уменьшает окрестность; большая база — честная строка", async ({ page }) => {
  await page.goto(`./entity/${E3}`);
  await star(page, E3);
  const before = await page.evaluate(() => (window as unknown as { __amemoSky: Handle }).__amemoSky.count());
  await page.getByRole("radio", { name: "Глубина 1" }).click();
  await expect
    .poll(() => page.evaluate(() => (window as unknown as { __amemoSky: Handle }).__amemoSky.count()))
    .toBeLessThan(before);
  await page.goto("./?project=big");
  await expect(page.getByText("Показано 300 звёзд из 420", { exact: false })).toBeVisible();
});

test("запись: «Окрестность» — вкладка правой панели, небо видно без прокрутки", async ({
  page,
  isMobile,
}) => {
  await page.goto(`./atom/${A3}`);
  const tab = page.getByRole("tab", { name: "Окрестность" });
  // на узком экране панель стоит под записью
  if (isMobile) await tab.scrollIntoViewIfNeeded();
  await tab.click();
  const w = page.getByRole("tabpanel", { name: "Окрестность" });
  const sky = w.getByRole("application", { name: /^Небо: 8 звёзд/ });
  if (isMobile) await sky.scrollIntoViewIfNeeded();
  await expect(sky).toBeInViewport();
});

test("правая панель: ширина стрелками, свёрнутость и вкладка переживают перезагрузку", async ({
  page,
  isMobile,
}) => {
  test.skip(isMobile, "на узком экране панель стоит под записью, ширина не меняется");
  await page.goto(`./atom/${A3}`);
  const grip = page.getByRole("separator", { name: "Ширина панели" });
  const before = Number(await grip.getAttribute("aria-valuenow"));
  await grip.focus();
  await page.keyboard.press("ArrowLeft");
  await expect(grip).toHaveAttribute("aria-valuenow", String(before + 24));
  await page.getByRole("tab", { name: "Окрестность" }).click();
  await page.reload();
  await expect(page.getByRole("tab", { name: "Окрестность" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("separator", { name: "Ширина панели" })).toHaveAttribute(
    "aria-valuenow",
    String(before + 24),
  );
  await page.getByRole("button", { name: "Свернуть панель" }).click();
  await page.reload();
  await expect(page.getByRole("tab", { name: "Окрестность" })).toHaveCount(0);
  await page.getByRole("button", { name: /^Развернуть панель/ }).click();
  await expect(page.getByRole("tab", { name: "Окрестность" })).toBeVisible();
});

test("новая запись загорается звездой", async ({ page }) => {
  await page.goto(`./entity/${E3}`);
  await star(page, E3);
  const before = await page.evaluate(() => (window as unknown as { __amemoSky: Handle }).__amemoSky.count());
  await page.evaluate((e3) => {
    (window as unknown as { __amemoSky: Handle }).__amemoSky.emit({
      star: {
        id: "atm:new",
        label: "Новая заметка",
        kind: "note",
        family: "work",
        status: "draft",
        pending: false,
        object: false,
        degree: 1,
        depth: 1,
        r: 2.6,
      },
      links: [{ source: "atm:new", target: e3, rel: "about" }],
    });
  }, E3);
  await expect
    .poll(() => page.evaluate(() => (window as unknown as { __amemoSky: Handle }).__amemoSky.count()))
    .toBe(before + 1);
  await expect(page.getByRole("region", { name: "Выбранная звезда" })).toContainText("Новая заметка");
});

test("небо светлое в светлой теме и тёмное в тёмной", async ({ page }) => {
  const lightness = () =>
    page.evaluate(() => {
      // цвет фона неба на главной: из токена --sky, приведённого браузером
      const el = document.createElement("div");
      el.style.color = "var(--sky)";
      document.body.append(el);
      const c = getComputedStyle(el).color;
      el.remove();
      const ok = c.match(/oklch\(([\d.]+)(%?)/);
      if (ok?.[1]) return ok[2] ? Number(ok[1]) / 100 : Number(ok[1]);
      const rgb = c.match(/rgba?\((\d+)/);
      return rgb?.[1] ? Number(rgb[1]) / 255 : -1;
    });
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("./");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  expect(await lightness()).toBeGreaterThan(0.85);
  await page.emulateMedia({ colorScheme: "dark" });
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(await lightness()).toBeLessThan(0.25);
});
