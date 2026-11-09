import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const A3 = "atm:0193b7c2-5e1a-7d40-9f2e-00000000000b";
const N1 = "atm:0193b7c2-5e1a-7d40-9f2e-00000000001e";
const E3 = "ent:0193b7c2-5e1a-7d40-9f2e-000000000003";
const pages = [
  "./",
  "./records",
  `./?center=${E3}`,
  "./search?q=погрешность",
  "./settings",
  `./atom/${A3}`,
  `./atom/${A3}?view=source`,
  `./atom/${A3}?view=agent`,
  `./atom/${N1}`,
  "./atom/atm:0193b7c2-5e1a-7d40-9f2e-000000000021",
  "./atom/atm:0193b7c2-5e1a-7d40-9f2e-000000000022",
  `./entity/${E3}`,
  "./object/0193b7c2-5e1a-7d40-9f2e-0000000000a1",
  "./object/0193b7c2-5e1a-7d40-9f2e-0000000000a2",
  "./changes?since=ever",
  `./new?about=${E3}`,
  "./review",
  "./review?group=source",
  "./review/5f0c2a8e-1d3b-4c6a-9e7f-0a1b2c3d4e01",
  "./review/5f0c2a8e-1d3b-4c6a-9e7f-0a1b2c3d4e02",
  "./review/5f0c2a8e-1d3b-4c6a-9e7f-0a1b2c3d4e5f",
  "./review/5f0c2a8e-1d3b-4c6a-9e7f-0a1b2c3d4e03",
  "./base",
  "./bundles",
];

for (const theme of ["light", "dark"] as const) {
  for (const path of pages) {
    test(`axe: ${path} в теме ${theme}`, async ({ page }) => {
      await page.addInitScript((t) => window.localStorage.setItem("amem.theme", t), theme);
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await expect(page.locator("main")).not.toContainText("Загрузка");
      const r = await new AxeBuilder({ page }).analyze();
      const bad = r.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(
        bad.map(
          (v) =>
            `${v.id}: ${v.nodes
              .map((n) => n.target.join(" "))
              .slice(0, 3)
              .join(", ")}`,
        ),
      ).toEqual([]);
    });
  }
}

const opened: [string, string, (p: import("@playwright/test").Page) => Promise<void>][] = [
  ["правка записи", `./atom/${N1}`, async (p) => p.getByRole("button", { name: "Править, ⌘E" }).click()],
  [
    "окно N",
    `./records`,
    async (p) => p.getByRole("banner").getByRole("button", { name: "Записать" }).click(),
  ],
  ["конструктор видов", "./settings", async (p) => p.getByRole("button", { name: "Настроить виды" }).click()],
  [
    "«+ Источник»",
    `./new?about=${E3}`,
    async (p) => p.getByRole("button", { name: "Добавить источник" }).click(),
  ],
];

for (const theme of ["light", "dark"] as const) {
  for (const [name, path, open] of opened) {
    test(`axe: ${name} открыто, тема ${theme}`, async ({ page }) => {
      await page.addInitScript((t) => window.localStorage.setItem("amem.theme", t), theme);
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await open(page);
      await page.waitForTimeout(600);
      const r = await new AxeBuilder({ page }).analyze();
      const bad = r.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(
        bad.map(
          (v) =>
            `${v.id}: ${v.nodes
              .map((n) => n.target.join(" "))
              .slice(0, 3)
              .join(", ")}`,
        ),
      ).toEqual([]);
    });
  }
}
