import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

/** Мастер первого запуска (setup.html, заглушка моста src/setup/mock.ts). Снимки каждого шага в обеих темах и
 * на обоих языках прикладываются к отчёту (playwright-report, артефакт CI) — их смотрят глазами; проверки — по
 * содержимому и axe. */

const STEPS = ["lang", "data", "docs", "features", "agents", "install", "done"] as const;

async function open(page: Page, query: string, theme: "light" | "dark") {
  await page.addInitScript((t) => window.localStorage.setItem("amemo.theme", t), theme);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(`./setup.html?${query}`);
  await expect(page.locator("h1")).toBeVisible();
}

async function axe(page: Page) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(", ")}`)).toEqual([]);
}

for (const lang of ["ru", "en"] as const) {
  for (const theme of ["light", "dark"] as const) {
    test(`снимки шагов: ${lang}, ${theme}`, async ({ page }, info) => {
      for (const step of STEPS) {
        // установка — на середине загрузки; остальные шаги — как их видит человек
        const query = `lang=${lang}&step=${step}${step === "install" ? "&freeze=download" : "&fast=1"}`;
        await open(page, query, theme);
        if (step === "install") await expect(page.locator("progress")).toBeVisible();
        if (step === "install") await expect(page.locator(".car__img")).toBeVisible();
        await axe(page);
        await info.attach(`${lang}-${theme}-${step}`, {
          body: await page.screenshot(),
          contentType: "image/png",
        });
      }
    });
  }
}

test("мастер от языка до «Готово»", async ({ page }) => {
  await open(page, "fast=1", "light");
  await expect(page.getByRole("heading", { name: "Язык amemo" })).toBeVisible();
  await page.getByText("English").click();
  await expect(page.getByRole("heading", { name: "amemo language" })).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();

  await expect(page.getByRole("heading", { name: "Where to keep the base" })).toBeVisible();
  await expect(page.getByText("C:\\Users\\anna\\amemo-data")).toBeVisible();
  await expect(page.getByText(/free, about .* needed/)).toBeVisible();
  await page.getByRole("button", { name: "Choose…" }).click();
  await expect(page.getByText("D:\\amemo-1")).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();

  await expect(page.getByRole("heading", { name: "Documents folder" })).toBeVisible();
  await page.getByRole("button", { name: "Not now" }).click();
  await expect(page.getByText(/Not chosen/)).toBeVisible();
  await page.getByRole("button", { name: "Skip" }).click();

  await expect(page.getByRole("heading", { name: "Features" })).toBeVisible();
  await page.getByLabel("Recognise scans").check();
  await expect(page.getByRole("checkbox", { name: "English" })).toBeChecked();
  await page.getByRole("checkbox", { name: "English" }).uncheck();
  await expect(page.getByRole("button", { name: "Next" })).toBeDisabled();
  await page.getByRole("checkbox", { name: "German" }).check();
  await page.getByRole("button", { name: "Next" }).click();

  await expect(page.getByRole("heading", { name: "Connect agents" })).toBeVisible();
  await expect(page.getByLabel(/Claude app/)).toBeChecked();
  await expect(page.getByLabel(/Codex/)).not.toBeChecked();
  await page.getByRole("button", { name: "Install" }).click();

  await expect(page.getByRole("heading", { name: "amemo is ready" })).toBeVisible();
  await expect(page.getByLabel("Desktop shortcut")).toBeChecked();
  await expect(page.getByLabel("Start when I sign in to Windows")).toBeChecked();
  await page.getByRole("button", { name: "Open amemo" }).click();
});

test("папка с символами вне кодировки Windows: подсказка и запасной путь", async ({ page }) => {
  await open(page, "step=data&nonansi=1&fast=1", "light");
  await expect(page.getByRole("alert")).toContainText("PostgreSQL не откроет этот путь");
  await expect(page.getByRole("button", { name: "Далее" })).toBeDisabled();
  await page.getByRole("button", { name: "Использовать C:\\amemo-data" }).click();
  await expect(page.getByText("C:\\amemo-data", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Далее" })).toBeEnabled();
});

test("мало места: дальше нельзя", async ({ page }) => {
  await open(page, "step=data&low=1&fast=1", "light");
  await expect(page.getByText(/Места мало/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Далее" })).toBeDisabled();
});

test("ошибка установки: сообщение и «Повторить»", async ({ page }) => {
  await open(page, "step=install&fail=database&fast=1", "dark");
  await expect(page.getByRole("heading", { name: "Установка остановилась" })).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("pg_ctl start");
  await axe(page);
  await page.getByRole("button", { name: "Повторить" }).click();
  await expect(page.getByRole("heading", { name: "amemo готов" })).toBeVisible();
});

test("карусель: следующий пример, пауза, подписи на языке мастера", async ({ page }) => {
  await open(page, "step=install&freeze=download&lang=en", "light");
  const carousel = page.getByRole("region", { name: "What amemo does" });
  const caption = carousel.locator(".car__cap");
  const first = await caption.textContent();
  await carousel.getByRole("button", { name: "Next example" }).click();
  await expect(caption).not.toHaveText(first ?? "");
  await expect(carousel.getByRole("button", { name: "Example 2" })).toHaveAttribute("aria-current", "true");
  // «уменьшить движение» — сюжеты меняет только человек: кнопка «Дальше», а не «Пауза»
  await expect(carousel.getByRole("button", { name: "Play" })).toBeVisible();
});
