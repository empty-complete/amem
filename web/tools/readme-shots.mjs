// Снимки экрана для README (docs/assets/readme/{en,ru}/<экран>-{light,dark}.png) — с настоящей службы на образце
// tools/seed_sample.py. Запуск из web/: node tools/readme-shots.mjs [адрес службы, по умолчанию http://127.0.0.1:8770]
// Только образец «метеостанция»: ни реальных баз, ни путей, ни имён людей и компаний.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const base = (process.argv[2] ?? "http://127.0.0.1:8770").replace(/\/$/, "");
const out = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "docs", "assets", "readme");

const browser = await chromium.launch();
const ctx0 = await browser.newContext();
const api = async (path) => (await ctx0.request.get(`${base}/api/v1${path}`)).json();
const find = async (q) =>
  (await api(`/search?q=${encodeURIComponent(q)}`)).items.find((x) => x.label.startsWith(q)).ref;
const fact = await find("Погрешность влажности В-2");
const v2 = await find("Датчик влажности В-2");
const item = (await api("/review/items?state=queued"))[0].id;

const screens = [
  ["sky", `/ui/?center=${encodeURIComponent(v2)}`, 3500],
  ["record", `/ui/atom/${fact}`, 3000],
  ["review", `/ui/review/${item}`, 3000],
  ["card", `/ui/entity/${v2}?tab=card`, 3000],
];

for (const lang of ["en", "ru"]) {
  mkdirSync(join(out, lang), { recursive: true });
  for (const theme of ["light", "dark"]) {
    const ctx = await browser.newContext({
      viewport: { width: 1600, height: 900 },
      colorScheme: theme,
      locale: lang,
    });
    await ctx.addInitScript(
      ([l, t]) => {
        localStorage.setItem("amem.locale", l);
        localStorage.setItem("amem.theme", t);
      },
      [lang, theme],
    );
    const page = await ctx.newPage();
    for (const [name, path, settle] of screens) {
      await page.goto(base + path);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(settle);
      // панели с прокруткой (пункт проверки сам листает к цитате) — к началу, чтобы был виден заголовок
      await page.evaluate(() => {
        for (const e of document.querySelectorAll("*")) if (e.scrollTop) e.scrollTop = 0;
      });
      await page.waitForTimeout(300);
      const file = join(out, lang, `${name}-${theme}.png`);
      await page.screenshot({ path: file });
      console.log(file);
    }
    await ctx.close();
  }
}
await browser.close();
