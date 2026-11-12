import { expect, test } from "@playwright/test";

test("антология: собрать, HTML-отчёт в окне приложения", async ({ page }) => {
  await page.goto("./bundles");
  await page.getByRole("radio", { name: /^Подборка amemo/ }).check();
  await page.getByRole("checkbox", { name: /Антология: проверенное и предпочтительное/ }).check();
  await page.getByRole("textbox", { name: "Заголовок отчёта" }).fill("Датчики");
  await page.getByRole("button", { name: "Собрать подборку" }).click();
  await expect(page.getByRole("heading", { name: /Подборка собрана/ })).toBeVisible();
  await page.getByRole("button", { name: "Открыть отчёт" }).click();
  // рамка отчёта изолирована (sandbox без скриптов): содержимое сверяем по srcdoc, внутрь рамки не заходим
  const frame = page.getByRole("dialog", { name: "Отчёт подборки" }).locator("iframe");
  await expect(frame).toHaveAttribute("srcdoc", /<h1>Датчики<\/h1>/);
});

test("импорт: проверка → пробный импорт → влить; пункты импорта — в проверке", async ({ page }) => {
  await page.goto("./bundles");
  await page.getByRole("tab", { name: "Импорт" }).click();
  await page
    .locator('input[type="file"]')
    .setInputFiles({ name: "зима.zip", mimeType: "application/zip", buffer: Buffer.from("PK") });
  const card = page.getByRole("region", { name: "В подборке" });
  await expect(card).toContainText("5 записей · 2 объектов");
  await expect(card).toContainText("Части целы");
  await page.getByRole("radio", { name: /Всё на проверку/ }).check();
  await page.getByRole("button", { name: "Пробный импорт" }).click();
  await expect(page.getByRole("region", { name: "Пробный импорт" })).toContainText(
    "Будет: 4 новых, 2 без изменений, 1 изменённых",
  );
  await page.getByRole("button", { name: "Влить в базу" }).click();
  await expect(page.getByText("Влито. Новых записей: 4")).toBeVisible();
  await page.getByRole("link", { name: "Открыть пункты импорта в проверке" }).click();
  await expect(page).toHaveURL(/\/review/);
});

test("повреждённая подборка — пробный импорт недоступен", async ({ page }) => {
  await page.goto("./bundles");
  await page.getByRole("tab", { name: "Импорт" }).click();
  await page
    .locator('input[type="file"]')
    .setInputFiles({ name: "битый.zip", mimeType: "application/zip", buffer: Buffer.from("PK") });
  await expect(page.getByRole("region", { name: "В подборке" })).toContainText(
    "Повреждены части: atoms.jsonl",
  );
  await expect(page.getByRole("button", { name: "Пробный импорт" })).toBeDisabled();
});
