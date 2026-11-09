// Снимки экрана для README (docs/assets/readme/<язык>/<экран>-{light,dark}.png) — с настоящей службы на образце.
// Английские — с образца tools/seed_sample_en.py (README.md), русские — с tools/seed_sample.py (README.ru.md).
// Запуск из web/: node tools/readme-shots.mjs <адрес службы> <en|ru>  (по умолчанию http://127.0.0.1:8770 en)
// Только образцы: ни реальных баз, ни путей, ни имён людей и компаний.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const base = (process.argv[2] ?? "http://127.0.0.1:8770").replace(/\/$/, "");
const lang = process.argv[3] ?? "en";
const out = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "docs", "assets", "readme", lang);

// что снимать на каждом образце: подписи записей, по которым их находит поиск
const SAMPLES = {
  en: {
    fact: "TH-20 humidity accuracy",
    review: "WS-4 anemometer starts only",
    card: "WS-100 automatic weather station",
    sky: () => "/ui/",
  },
  ru: {
    fact: "Погрешность влажности В-2",
    review: "",
    card: "Датчик влажности В-2",
    sky: (card) => `/ui/?center=${encodeURIComponent(card)}`,
  },
};
const sample = SAMPLES[lang];
if (!sample) throw new Error(`нет образца для языка ${lang}: ${Object.keys(SAMPLES).join(", ")}`);

const browser = await chromium.launch();
const ctx0 = await browser.newContext();
const api = async (path) => (await ctx0.request.get(`${base}/api/v1${path}`)).json();
const find = async (q) => {
  const hit = (await api(`/search?q=${encodeURIComponent(q)}`)).items.find((x) => x.label.startsWith(q));
  if (!hit) throw new Error(`образец: нет записи «${q}»`);
  return hit.ref;
};
const fact = await find(sample.fact);
const card = await find(sample.card);
const items = await api("/review/items?state=queued");
const item = (items.find((x) => (x.label ?? "").startsWith(sample.review)) ?? items[0]).id;

const screens = [
  ["sky", sample.sky(card), 4500],
  ["record", `/ui/atom/${fact}`, 3000],
  ["review", `/ui/review/${item}`, 3000],
  ["card", `/ui/entity/${card}?tab=card`, 3000],
];

mkdirSync(out, { recursive: true });
for (const theme of ["light", "dark"]) {
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 }, colorScheme: theme, locale: lang });
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
    const file = join(out, `${name}-${theme}.png`);
    await page.screenshot({ path: file });
    console.log(file);
  }
  await ctx.close();
}
await browser.close();
