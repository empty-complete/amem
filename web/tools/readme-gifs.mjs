// Анимации для README (docs/assets/readme/<язык>/demo-<сцена>.gif): сцены работы с настоящей службой на образце.
// Видео Playwright → GIF через ffmpeg (палитра palettegen/paletteuse). Курсор и нажатые клавиши рисуются поверх
// страницы: в видео Playwright их не видно. Сцены меняют базу (запись, решение проверки, значение карточки), поэтому
// запускать после снимков readme-shots.mjs.
// Запуск из web/: node tools/readme-gifs.mjs <адрес службы> <en|ru> [сцена,сцена]; нужен ffmpeg в PATH.
// Только образцы: ни реальных баз, ни путей, ни имён людей и компаний.
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const base = (process.argv[2] ?? "http://127.0.0.1:8770").replace(/\/$/, "");
const lang = process.argv[3] ?? "en";
const only = process.argv[4]?.split(",");
const here = dirname(fileURLToPath(import.meta.url));
const out = join(here, "..", "..", "docs", "assets", "readme", lang);
const SIZE = { width: 1280, height: 720 };
const GIF = { fps: 12, width: 1200, colors: 192 };

const dict = JSON.parse(readFileSync(join(here, "..", "src", "i18n", `${lang}.json`), "utf8"));
const t = (key, vars = {}) => {
  const s = key.split(".").reduce((o, k) => o?.[k], dict);
  if (typeof s !== "string") throw new Error(`нет перевода ${key} (${lang})`);
  return s.replace(/\{\{(\w+)\}\}/g, (_, k) => String(vars[k] ?? ""));
};

// что делать на каждом образце: текст быстрой записи, запрос, записи по подписи, значение для карточки
const SAMPLES = {
  en: {
    write: "WS-2 battery reads 11.8 V after the frost night",
    query: "humidity accuracy",
    result: "TH-20 humidity accuracy",
    card: "WS-100 automatic weather station",
    value: "2.4",
  },
  ru: {
    write: "Влажность В-2 утром 87 %",
    query: "погрешность влажности",
    result: "Погрешность влажности В-2",
    card: "Датчик влажности В-2",
    value: "-30",
  },
};
const sample = SAMPLES[lang];
if (!sample) throw new Error(`нет образца для языка ${lang}: ${Object.keys(SAMPLES).join(", ")}`);

// курсор, круг на щелчке и плашка нажатой клавиши — в самой странице, чтобы попасть в видео
function overlay() {
  const ready = () => {
    const root = document.documentElement;
    const NS = "http://www.w3.org/2000/svg";
    const cursor = document.createElementNS(NS, "svg");
    cursor.setAttribute("width", "24");
    cursor.setAttribute("height", "24");
    cursor.setAttribute("viewBox", "0 0 24 24");
    const arrow = document.createElementNS(NS, "path");
    arrow.setAttribute("d", "M4 2v17l4.6-4.3 3.1 6.8 2.7-1.2-3.1-6.6H18z");
    arrow.setAttribute("fill", "#15171c");
    arrow.setAttribute("stroke", "#fff");
    arrow.setAttribute("stroke-width", "1.6");
    arrow.setAttribute("stroke-linejoin", "round");
    cursor.appendChild(arrow);
    Object.assign(cursor.style, {
      position: "fixed",
      left: "0",
      top: "0",
      zIndex: "2147483647",
      pointerEvents: "none",
      transform: "translate(-80px,-80px)",
    });
    root.appendChild(cursor);
    addEventListener(
      "mousemove",
      (e) => {
        cursor.style.transform = `translate(${e.clientX - 4}px,${e.clientY - 2}px)`;
      },
      true,
    );
    addEventListener(
      "mousedown",
      (e) => {
        const ring = document.createElement("div");
        Object.assign(ring.style, {
          position: "fixed",
          left: `${e.clientX - 16}px`,
          top: `${e.clientY - 16}px`,
          width: "32px",
          height: "32px",
          borderRadius: "50%",
          border: "3px solid #2a78d6",
          zIndex: "2147483646",
          pointerEvents: "none",
          transition: "transform .45s ease-out, opacity .45s ease-out",
        });
        root.appendChild(ring);
        requestAnimationFrame(() => {
          ring.style.transform = "scale(1.9)";
          ring.style.opacity = "0";
        });
        setTimeout(() => ring.remove(), 500);
      },
      true,
    );
    const badge = document.createElement("div");
    Object.assign(badge.style, {
      position: "fixed",
      left: "50%",
      bottom: "28px",
      transform: "translateX(-50%)",
      zIndex: "2147483647",
      pointerEvents: "none",
      padding: "8px 18px",
      borderRadius: "10px",
      background: "#15171cd9",
      color: "#fff",
      font: "600 22px/1.2 ui-monospace, monospace",
      opacity: "0",
      transition: "opacity .15s",
    });
    root.appendChild(badge);
    let timer;
    window.__key = (label) => {
      badge.textContent = label;
      badge.style.opacity = "1";
      clearTimeout(timer);
      timer = setTimeout(() => {
        badge.style.opacity = "0";
      }, 900);
    };
  };
  if (document.readyState === "loading") addEventListener("DOMContentLoaded", ready);
  else ready();
}

const pause = (page, ms) => page.waitForTimeout(ms);
const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const born = new WeakMap();
const mark = (page) => (Date.now() - born.get(page)) / 1000;
let pointer = { x: SIZE.width / 2, y: SIZE.height / 2 };

async function click(page, locator) {
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  if (!box) throw new Error(`не видно: ${locator}`);
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await page.mouse.move(pointer.x, pointer.y);
  await page.mouse.move(x, y, { steps: 18 });
  pointer = { x, y };
  await pause(page, 250);
  await page.mouse.down();
  await page.mouse.up();
}

async function key(page, name, label = name) {
  await page.evaluate((l) => window.__key?.(l), label);
  await pause(page, 180);
  await page.keyboard.press(name);
}

const typeIn = (page, text) => page.keyboard.type(text, { delay: 55 });

const browser = await chromium.launch();
const api = await browser.newContext();
const find = async (q) => {
  const r = await api.request.get(`${base}/api/v1/search?q=${encodeURIComponent(q)}`);
  const hit = (await r.json()).items.find((x) => x.label.startsWith(q));
  if (!hit) throw new Error(`образец: нет записи «${q}»`);
  return hit.ref;
};
const card = await find(sample.card);

// сцены по порядку; каждая возвращает секунду видео, с которой его резать (без белой загрузки)
const scenes = {
  // быстрая запись по N: вид угадывается по тексту, звезда вспыхивает на небе, «Отменить» в тосте
  async write(page) {
    await page.goto(`${base}/ui/`);
    await page.waitForLoadState("networkidle");
    await pause(page, 3000);
    const start = mark(page);
    await key(page, "n", "N");
    await pause(page, 700);
    await typeIn(page, sample.write);
    await pause(page, 1400);
    await key(page, "Enter", "Enter ↵");
    await pause(page, 3200);
    return start;
  },
  // от вопроса к источнику: поиск, запись, цитата на странице PDF; тёмная тема перекрашивает страницу
  async source(page) {
    await page.goto(`${base}/ui/`);
    await page.waitForLoadState("networkidle");
    await pause(page, 1500);
    const start = mark(page);
    await click(page, page.getByRole("combobox", { name: t("nav.search") }));
    await pause(page, 300);
    await typeIn(page, sample.query);
    await pause(page, 400);
    await key(page, "Enter", "Enter ↵");
    const hit = page.getByRole("link", { name: new RegExp(`^${escapeRe(sample.result)}`) }).first();
    await hit.waitFor();
    await pause(page, 1300);
    await click(page, hit);
    await page.locator(".textLayer mark, mark.q").first().waitFor({ timeout: 20_000 });
    await pause(page, 2600);
    await click(page, page.getByRole("button", { name: t("nav.theme") }));
    await pause(page, 2600);
    return start;
  },
  // проверка с клавиатуры: J — следующий пункт, Y — подтвердить, тост с «Отменить»
  async review(page) {
    await page.goto(`${base}/ui/review`);
    const list = page.getByRole("listbox", { name: t("review.list") });
    await list.getByRole("option").first().waitFor();
    await pause(page, 1500);
    const start = mark(page);
    const steps = Math.min(2, (await list.getByRole("option").count()) - 1);
    for (let i = 0; i < steps; i++) {
      await key(page, "j", "J");
      await pause(page, 1100);
    }
    await key(page, "y", "Y");
    await page.getByText(t("review.toast_confirmed"), { exact: true }).first().waitFor();
    await pause(page, 2800);
    return start;
  },
  // карточка: «Нужно» у обязательного поля, ввод значения, полоса полноты растёт
  async card(page) {
    await page.goto(`${base}/ui/entity/${card}?tab=card`);
    await page.waitForLoadState("networkidle");
    await pause(page, 2000);
    const start = mark(page);
    await click(page, page.getByRole("button", { name: t("card.need"), exact: true }).first());
    await pause(page, 600);
    await page.keyboard.type(sample.value, { delay: 160 });
    await pause(page, 500);
    await key(page, "Enter", "Enter ↵");
    await pause(page, 3200);
    return start;
  },
  // небо: укладка созвездия, стрелки выбирают звезду, Enter открывает, глубина окрестности 1 и 3
  async sky(page) {
    await page.goto(`${base}/ui/`);
    await page.waitForLoadState("domcontentloaded");
    const start = mark(page) + 0.4;
    await pause(page, 4200);
    await page.getByRole("application").first().focus();
    for (let i = 0; i < 3; i++) {
      await key(page, "ArrowRight", "→");
      await pause(page, 1000);
    }
    await key(page, "Enter", "Enter ↵");
    await page.waitForURL(/\/(atom|entity)\//);
    await page.waitForLoadState("networkidle");
    await pause(page, 1800);
    for (const n of [1, 3]) {
      const radio = page.getByRole("radio", { name: `${t("sky.depth")} ${n}` }).first();
      if (await radio.isVisible()) {
        await click(page, radio);
        await pause(page, 1800);
      }
    }
    return start;
  },
};

mkdirSync(out, { recursive: true });
const videos = mkdtempSync(join(tmpdir(), "amemo-gifs-"));
for (const [name, scene] of Object.entries(scenes)) {
  if (only && !only.includes(name)) continue;
  const ctx = await browser.newContext({
    viewport: SIZE,
    colorScheme: "light",
    locale: lang,
    bypassCSP: true,
    recordVideo: { dir: videos, size: SIZE },
  });
  await ctx.addInitScript(
    ([l]) => {
      localStorage.setItem("amemo.locale", l);
      localStorage.setItem("amemo.theme", "light");
    },
    [lang],
  );
  await ctx.addInitScript(overlay);
  const page = await ctx.newPage();
  born.set(page, Date.now());
  pointer = { x: SIZE.width / 2, y: SIZE.height / 2 };
  const start = await scene(page);
  const video = page.video();
  await ctx.close();
  const webm = await video.path();
  const gif = join(out, `demo-${name}.gif`);
  const { fps, width, colors } = GIF;
  execFileSync("ffmpeg", [
    "-y",
    "-v",
    "error",
    "-ss",
    Math.max(0, start).toFixed(2),
    "-i",
    webm,
    "-vf",
    `fps=${fps},scale=${width}:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=${colors}:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle`,
    "-loop",
    "0",
    gif,
  ]);
  console.log(`${gif}  ${(statSync(gif).size / 1048576).toFixed(1)} MB`);
}
rmSync(videos, { recursive: true, force: true });
await browser.close();
