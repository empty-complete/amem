import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const A3 = "atm:0193b7c2-5e1a-7d40-9f2e-00000000000b";
const N1 = "atm:0193b7c2-5e1a-7d40-9f2e-00000000001e";
const E3 = "ent:0193b7c2-5e1a-7d40-9f2e-000000000003";
const pages = [
  "./",
  "./search?q=погрешность",
  "./settings",
  `./atom/${A3}`,
  `./atom/${A3}?view=source`,
  `./atom/${A3}?view=agent`,
  `./atom/${N1}`,
  `./entity/${E3}`,
  "./object/0193b7c2-5e1a-7d40-9f2e-0000000000a1",
  "./object/0193b7c2-5e1a-7d40-9f2e-0000000000a2",
  "./changes?since=ever",
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
