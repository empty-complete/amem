// Снимки экрана для README (docs/assets/readme/<язык>/<экран>-{light,dark}.png) — с настоящей службы на образце.
// Английские — с образца tools/seed_sample_en.py (README.md), русские — с tools/seed_sample.py (README.ru.md).
// Запуск из web/: node tools/readme-shots.mjs <адрес службы> <en|ru>  (по умолчанию http://127.0.0.1:8770 en)
// Только образцы: ни реальных баз, ни путей, ни имён людей и компаний.
import { existsSync, mkdirSync, readFileSync } from "node:fs";
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

// сессия агента (tools/readme_agent_session.py): настоящие вызовы MCP, нарисованные как окно терминала
const transcriptPath = process.env.AGENT_TRANSCRIPT;
const transcript =
  transcriptPath && existsSync(transcriptPath) ? JSON.parse(readFileSync(transcriptPath, "utf8")) : null;

const esc = (s) =>
  String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const text = (v) =>
  typeof v === "string" ? v : v && typeof v === "object" ? (v.en ?? v.ru ?? Object.values(v)[0]) : "";
const WORDS = {
  en: {
    hits: (n) => `${n} ${n === 1 ? "hit" : "hits"}`,
    retrieval: "retrieval",
    value: "value",
    at: "at",
    summary: "summary",
    source: "source",
    page: "page",
    version: "version",
    review: "review",
    helpful: "marked as helpful",
    nothing: "nothing",
    session: "agent session · MCP server: amem mcp",
    verdict: { ok: "quote found", fuzzy: "quote close", not_found: "quote not found" },
  },
  ru: {
    hits: (n) => `найдено: ${n}`,
    retrieval: "выдача",
    value: "значение",
    at: "при",
    summary: "суть",
    source: "источник",
    page: "стр.",
    version: "версия",
    review: "проверка",
    helpful: "отмечено как полезное",
    nothing: "ничего",
    session: "сессия агента · MCP-сервер: amem mcp",
    verdict: { ok: "цитата найдена", fuzzy: "цитата приблизительно", not_found: "цитата не найдена" },
  },
};
const W = WORDS[lang] ?? WORDS.en;
const short = (ref) => (ref && ref.length > 20 ? `${ref.slice(0, 12)}…${ref.slice(-4)}` : ref);
const status = (s) => `<span class="st ${esc(s)}">${esc(String(s).replace("_", " "))}</span>`;
const args = (a) =>
  Object.entries(a)
    .map(
      ([k, v]) =>
        `<span class="k">${esc(k)}</span>=<span class="v">${esc(JSON.stringify(Array.isArray(v) ? v.map(short) : k === "retrieval_id" ? short(v) : v))}</span>`,
    )
    .join(", ");

function agentHtml(t, theme) {
  const blocks = t.calls.map(({ tool, args: a, result: r }) => {
    let body = "";
    if (tool === "amem_search") {
      body = `<div class="res">${W.hits(r.items.length)} · ${W.retrieval} ${esc(short(r.retrieval_id))}</div>${r.items
        .map(
          (i) =>
            `<div class="row"><span class="ref">${esc(short(i.ref))}</span><span class="lab">${esc(i.label)}</span><span class="meta">${esc(i.kind)} · ${status(i.status)}</span></div>`,
        )
        .join("")}`;
    } else if (tool === "amem_get") {
      body = r.records
        .map((v) => {
          const p = v.payload ?? {};
          const val = p.content?.values?.[0];
          const q = val?.qualifiers?.[0];
          const value = val
            ? `<div class="row"><span class="k2">${W.value}</span><span>${esc(val.value_text ?? val.amount ?? `${val.lower_bound}…${val.upper_bound}`)} ${esc(val.unit)}${q ? ` <span class="muted">${W.at} ${esc(String(q.property).replaceAll("_", " "))} ${esc(q.lower_bound)}–${esc(q.upper_bound)} ${esc(q.unit)}</span>` : ""}</span></div>`
            : "";
          const sources = (v.sources ?? [])
            .map((s) => {
              const page = (s.selectors ?? []).find((x) => x.type === "page");
              return `<div class="row"><span class="k2">${W.source}</span><span>${esc(s.object_name ?? s.object)}${page ? ` · ${W.page} ${esc(page.label ?? page.value)}` : ""} · ${W.version} ${esc(s.object_version)} · <span class="ok">${esc(W.verdict[s.verdict] ?? String(s.verdict ?? "").replace("_", " "))}</span></span></div>${s.quote ? `<div class="row"><span class="k2"></span><mark>“${esc(s.quote)}”</mark></div>` : ""}`;
            })
            .join("");
          const open = (v.open_items ?? []).map((i) => `${esc(i.reason)} ${esc(i.state)}`).join(", ");
          return `<div class="res"><b>${esc(text(p.label))}</b> <span class="meta">${esc(p.kind)} · ${status(v.status)}</span></div>${value}<div class="row"><span class="k2">${W.summary}</span><span>${esc(text(p.summary_plain))}</span></div>${sources}${open ? `<div class="row"><span class="k2">${W.review}</span><span>${open}</span></div>` : ""}`;
        })
        .join("");
    } else if (tool === "amem_helpful") {
      body = `<div class="res">${W.helpful}: ${(r.marked ?? []).map((m) => esc(short(m))).join(", ") || W.nothing}</div>`;
    } else {
      body = `<div class="res">${esc(JSON.stringify(r))}</div>`;
    }
    const dot = { amem_search: "src", amem_get: "obj", amem_helpful: "work" }[tool] ?? "src";
    return `<div class="call"><div class="head"><i class="dot ${dot}"></i><b>${esc(tool)}</b>(${args(a)})</div><div class="body">${body}</div></div>`;
  });
  const dark = theme === "dark";
  return `<!doctype html><meta charset="utf-8"><style>
:root{--paper:${dark ? "#08090c" : "#f4f6f8"};--win:${dark ? "#0b0d11" : "#ffffff"};--ink:${dark ? "#e6e8ec" : "#181b20"};
--muted:${dark ? "#8b93a1" : "#656970"};--line:${dark ? "#ffffff14" : "#e0e1e4"};--mark:${dark ? "#635418" : "#f7e59f"};
--src:${dark ? "#3987e5" : "#2a78d6"};--work:${dark ? "#d95926" : "#eb6834"};--obj:${dark ? "#199e70" : "#1baf7a"};
--ok:${dark ? "#5fc183" : "#0a7e3a"};--warn:${dark ? "#e0a64a" : "#a46400"}}
*{box-sizing:border-box}html,body{margin:0;height:100%;background:var(--paper);color:var(--ink)}
body{display:flex;align-items:center;justify-content:center;font:19px/1.6 "JetBrains Mono","DejaVu Sans Mono",ui-monospace,monospace}
.win{width:1440px;min-height:520px;background:var(--win);border:1px solid var(--line);border-radius:16px;overflow:hidden;
box-shadow:0 18px 50px rgb(0 0 0 / ${dark ? "0.45" : "0.12"})}
.bar{height:46px;display:flex;align-items:center;gap:9px;padding:0 18px;border-bottom:1px solid var(--line);color:var(--muted);font-size:14px}
.bar i{width:12px;height:12px;border-radius:50%;display:inline-block}.bar .t{margin:0 auto;transform:translateX(-30px)}
main{padding:26px 34px}.prompt{font-weight:600;margin-bottom:22px}.prompt span{color:var(--muted);margin-right:10px}
.call{margin-bottom:18px}.head b{font-weight:700}.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:12px}
.dot.src{background:var(--src)}.dot.obj{background:var(--obj)}.dot.work{background:var(--work)}
.k{color:var(--muted)}.v{color:var(--src)}.body{border-left:2px solid var(--line);margin:6px 0 0 4px;padding-left:20px}
.res{margin:2px 0}.row{display:flex;gap:16px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.ref{color:var(--muted);min-width:205px}
.lab{flex:1;overflow:hidden;text-overflow:ellipsis}.meta,.muted{color:var(--muted)}.k2{color:var(--muted);min-width:80px}
.st{font-weight:600}.st.verified,.st.auto_verified{color:var(--ok)}.st.needs_review,.st.draft{color:var(--warn)}
.ok{color:var(--ok)}mark{background:var(--mark);color:inherit;padding:0 4px;border-radius:3px}
</style><div class="win"><div class="bar"><i style="background:#ff5f57"></i><i style="background:#febc2e"></i><i style="background:#28c840"></i><span class="t">${W.session}</span></div>
<main><div class="prompt"><span>›</span>${esc(t.prompt)}</div>${blocks.join("")}</main></div>`;
}

mkdirSync(out, { recursive: true });
if (transcript) {
  for (const theme of ["light", "dark"]) {
    const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 }, colorScheme: theme });
    const page = await ctx.newPage();
    await page.setContent(agentHtml(transcript, theme));
    await page.waitForTimeout(300);
    const file = join(out, `agent-${theme}.png`);
    await page.screenshot({ path: file });
    console.log(file);
    await ctx.close();
  }
}
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
    const file = join(out, `${name}-${theme}.png`);
    await page.screenshot({ path: file });
    console.log(file);
  }
  await ctx.close();
}
await browser.close();
