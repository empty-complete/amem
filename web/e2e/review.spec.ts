import { expect, test } from "@playwright/test";

const ID = (n: number) => `5f0c2a8e-1d3b-4c6a-9e7f-0a1b2c3d4e${n.toString(16).padStart(2, "0")}`;

test("очередь с клавиатуры: J к следующему, Y — подтверждено с окном отмены, «Отменить» возвращает", async ({
  page,
  isMobile,
}) => {
  test.skip(isMobile, "клавиатура — на компьютере");
  await page.goto("./review");
  const list = page.getByRole("listbox", { name: "Очередь проверки" });
  await expect(list.getByRole("option")).toHaveCount(8);
  await expect(list.getByRole("option", { selected: true })).toContainText("правка");
  await page.keyboard.press("j");
  await expect(list.getByRole("option", { selected: true })).toContainText("высокий риск");
  await page.keyboard.press("y");
  await expect(page.getByText("Подтверждено", { exact: true })).toBeVisible();
  await expect(list.getByRole("option")).toHaveCount(7);
  await page.getByRole("button", { name: "Отменить" }).click();
  await expect(list.getByRole("option")).toHaveCount(8);
});

test("решение уходит после окна: счётчик «Проверка» уменьшается", async ({ page, isMobile }) => {
  test.skip(isMobile, "на телефоне «Проверка» — в меню");
  await page.goto(`./review/${ID(1)}`);
  await expect(page.getByRole("region", { name: "Что изменится" })).toBeVisible();
  await page.getByRole("button", { name: "Подтвердить, Y" }).click();
  await page.waitForTimeout(6500);
  await expect(page.getByRole("banner").getByRole("link", { name: /Проверка/ })).toContainText("7");
});

test("источник изменился — две версии с подсветкой; сомнение модели — вердикт", async ({ page }) => {
  await page.goto(`./review/${ID(2)}`);
  const vers = page.getByRole("region", { name: "Источник изменился" });
  await expect(vers).toContainText("Было (версия 1)");
  await expect(vers.locator("ins").first()).toBeVisible();
  await page.goto(`./review/${ID(0x5f)}`);
  await expect(page.getByRole("region", { name: "Вердикт модели" })).toContainText("уверенность 58 %");
});

test("решённые — фильтр, пусто без пунктов", async ({ page }) => {
  await page.goto("./review?state=done");
  await expect(page.getByRole("listbox", { name: "Очередь проверки" }).getByRole("option")).toHaveCount(1);
  await page.goto("./review?reason=imported");
  await expect(page.getByRole("listbox", { name: "Очередь проверки" }).getByRole("option")).toHaveCount(1);
});

test("телефон: список и пункт — на разных экранах", async ({ page, isMobile }) => {
  test.skip(!isMobile, "только на телефоне");
  await page.goto("./review");
  await page.getByRole("listbox", { name: "Очередь проверки" }).getByRole("option").first().click();
  await expect(page.getByRole("button", { name: /К списку/ })).toBeVisible();
  await expect(page.getByRole("listbox", { name: "Очередь проверки" })).toBeHidden();
  await page.getByRole("button", { name: /К списку/ }).click();
  await expect(page.getByRole("listbox", { name: "Очередь проверки" })).toBeVisible();
});

test("База — таблицы статусов, очереди, пакетов, бэкапов", async ({ page }) => {
  await page.goto("./base");
  await expect(page.getByRole("table", { name: "Записи по статусам" })).toBeVisible();
  await expect(page.getByRole("table", { name: "Очередь по причинам" })).toContainText("правка");
  await expect(page.getByRole("table", { name: "Бэкапы" })).toContainText("amemo-2026-11-07T03-00.dump");
});

test("по документам: группы, фильтр документа, решение — следующий в той же группе", async ({
  page,
  isMobile,
}) => {
  test.skip(isMobile, "клавиатура — на компьютере");
  await page.goto("./review?group=source");
  const list = page.getByRole("listbox", { name: "Очередь проверки" });
  await expect(list.locator(".qhead").first()).toContainText("Руководство_МС-1.pdf");
  await expect(list.locator(".qhead").first()).toContainText("3");
  await expect(list.locator(".qhead").last()).toContainText("Без источника");
  await page.getByRole("combobox", { name: "Документ" }).selectOption({ label: "Руководство_МС-1.pdf · 3" });
  await expect(page).toHaveURL(/object=/);
  await expect(list.getByRole("option")).toHaveCount(3);
  await list.getByRole("option").first().click();
  await page.keyboard.press("y");
  await expect(list.getByRole("option")).toHaveCount(2);
  await expect(list.getByRole("option", { selected: true })).toBeVisible();
});
