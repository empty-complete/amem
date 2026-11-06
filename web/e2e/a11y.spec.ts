import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

for (const theme of ["light", "dark"] as const) {
  for (const path of ["./", "./search?q=погрешность", "./settings"]) {
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
