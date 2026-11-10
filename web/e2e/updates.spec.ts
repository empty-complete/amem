import { expect, test } from "@playwright/test";

test("настройки: версия и обновления; установка — значок в верхней строке", async ({ page, isMobile }) => {
  await page.goto("./settings");
  const sec = page.getByRole("region", { name: "Версия и обновления" });
  await expect(sec.getByText("amemo 0.1.0a1")).toBeVisible();
  await expect(sec.getByRole("switch", { name: "Обновляться автоматически" })).toBeChecked();
  await expect(sec.getByRole("link", { name: "Доступна 0.1.0a2" })).toBeVisible();
  await sec.getByRole("button", { name: "Обновить сейчас" }).click();
  await expect(sec.getByText(/установлена — перезапуск/)).toBeVisible();
  if (!isMobile) await expect(page.getByRole("link", { name: "Обновление установлено" })).toBeVisible();
});
