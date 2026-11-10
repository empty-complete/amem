import { expect, test } from "@playwright/test";
import { TOKENS } from "./tokens";

// общая служба (AMEMO_TOKENS): статика открыта, API — только по токену; cookie нет
test("вход по токену: без токена — экран входа; неверный — «не подошёл»; верный — интерфейс работает", async ({
  page,
}) => {
  await page.goto("./");
  const dlg = page.getByRole("dialog", { name: "Вход в общую службу" });
  await expect(dlg).toBeVisible();
  await dlg.getByLabel("Токен").fill("wrong-token");
  await dlg.getByRole("button", { name: "Войти" }).click();
  await expect(dlg.getByRole("alert")).toContainText("Токен не подошёл");
  await dlg.getByLabel("Токен").fill(TOKENS.writer);
  await dlg.getByRole("button", { name: "Войти" }).click();
  await expect(dlg).toBeHidden();
  await expect(page.locator("canvas").first()).toBeVisible();
  await expect(page.getByRole("banner").getByRole("link", { name: /Проверка/ })).toBeVisible();
});

test("с токеном: PDF источника грузится (pdf.js с заголовком), «Выйти» стирает токен", async ({ page }) => {
  await page.goto("./");
  await page.getByLabel("Токен").fill(TOKENS.writer);
  await page.getByRole("button", { name: "Войти" }).click();
  await page.getByRole("combobox", { name: "Поиск по базе" }).fill("погрешность влажности");
  await page.keyboard.press("Enter");
  await page
    .getByRole("link", { name: /Погрешность влажности В-2/ })
    .first()
    .click();
  await expect(page.locator(".textLayer mark, mark.q").first()).toBeVisible({ timeout: 15_000 });
  await page.goto("./settings");
  await page.getByRole("button", { name: "Выйти" }).click();
  await page.reload();
  await expect(page.getByRole("dialog", { name: "Вход в общую службу" })).toBeVisible();
});

test("токен только для чтения: читает, запись — 403 read_only", async ({ page }) => {
  await page.goto("./");
  await page.getByLabel("Токен").fill(TOKENS.reader);
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page.getByRole("dialog", { name: "Вход в общую службу" })).toBeHidden();
  const status = await page.evaluate(async (tok) => {
    const r = await fetch("/api/v1/folders", {
      method: "POST",
      headers: { "content-type": "application/json", Authorization: `Bearer ${tok}` },
      body: JSON.stringify({ path: "Проба" }),
    });
    return r.status;
  }, TOKENS.reader);
  expect(status).toBe(403);
});
