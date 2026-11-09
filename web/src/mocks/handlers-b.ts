import { delay, HttpResponse, http } from "msw";
import { db } from "./db";
import changes from "./fixtures/changes.json";
import history from "./fixtures/history-a3.json";
import links from "./fixtures/links-a3.json";
import sheet from "./fixtures/sheet-v2.json";
import similar from "./fixtures/similar-a3.json";
import textManual from "./fixtures/text-manual.json";

export const problem = (status: number, title: string, detail?: string) =>
  HttpResponse.json(
    { type: "about:blank", title, status, detail },
    { status, headers: { "content-type": "application/problem+json" } },
  );

const MANUAL = "0193b7c2-5e1a-7d40-9f2e-0000000000a1";

/** Сдвиг дат ленты так, чтобы последнее событие было сегодня: «Сегодня» и «Вчера» в образце не стареют. */
function freshEvents() {
  const last = Math.max(...changes.events.map((e) => Date.parse(e.at)));
  const now = new Date();
  const shift =
    Math.round((now.setHours(12, 0, 0, 0) - new Date(last).setHours(12, 0, 0, 0)) / 86_400_000) * 86_400_000;
  const shifted = changes.events.map((e) => ({ ...e, at: new Date(Date.parse(e.at) + shift).toISOString() }));
  // записанное в этой сессии — с настоящим временем
  return [...shifted, ...db.events] as typeof shifted;
}

/** Сводка записи из её полного вида — для списков «о чём» (бриф источника, атомы объекта). */
/** about=ent:… — записи о сущности; about=obj:<id> или голый id — записи, цитирующие объект (как в библиотеке). */
function summaries(about: string) {
  const obj = about.startsWith("ent:") ? null : about.replace(/^obj:/, "");
  const fromA = obj ? [] : db.records.filter((r) => r.about?.some((a) => a.ref === about));
  const fromB = Object.values(db.views)
    .filter((v) =>
      obj
        ? v.sources.some((s) => s.object === obj)
        : (v.payload as { about?: string[] }).about?.includes(about),
    )
    .filter((v) => !fromA.some((r) => r.ref === v.ref))
    .map((v) => ({
      ref: v.ref,
      target: v.target,
      label: (v.payload as { label: { ru: string } }).label.ru,
      kind_or_class: (v.payload as { kind: string }).kind,
      status: v.status,
      folder: v.folder,
      about: v.about,
      recorded_at: v.recorded_at,
      agent: v.agent,
    }));
  return [...fromA, ...fromB];
}

/** Обработчики чтения (часть B): запись, история, связи, похожие, карточка, объекты, изменения. */
export const handlersB = (pdf: () => Promise<ArrayBuffer>) => [
  http.get("/api/v1/records", async ({ request }) => {
    const about = new URL(request.url).searchParams.get("about");
    if (!about) return; // дальше — обработчик части A
    await delay(80);
    const items = summaries(about);
    return HttpResponse.json({ items, total: items.length, next_cursor: null });
  }),
  http.get("/api/v1/records/:ref", async ({ params }) => {
    await delay(100);
    const v = db.views[String(params.ref)];
    return v ? HttpResponse.json(v) : problem(404, `Записи ${params.ref} нет`);
  }),
  http.get("/api/v1/records/:ref/history", ({ params }) =>
    HttpResponse.json(
      params.ref === history.ref
        ? history
        : {
            ref: params.ref,
            since: null,
            until: null,
            events: freshEvents().filter((e) => e.ref === params.ref),
          },
    ),
  ),
  http.get("/api/v1/records/:ref/links", ({ params }) =>
    HttpResponse.json(params.ref === history.ref ? links : []),
  ),
  http.get("/api/v1/similar", async () => {
    await delay(150);
    return HttpResponse.json(similar);
  }),
  http.get("/api/v1/entities/:ref/card", ({ params }) =>
    params.ref === db.card.entity.ref
      ? HttpResponse.json(db.card)
      : !db.views[String(params.ref)]
        ? problem(404, `Сущности ${params.ref} нет`)
        : // как служба: у сущности без профиля — карточка с пустыми fields
          HttpResponse.json({
            format: "amem.card/1",
            entity: { ref: String(params.ref), label: String(params.ref), entity_class: "artifact" },
            profile: null,
            templates: [],
            fields: [],
            extra: [],
            summary: { states: {}, blockers_open: 0, with_basis: [] },
          }),
  ),
  http.get("/api/v1/objects/:id", ({ params }) => {
    const o = db.objects[String(params.id)];
    return o ? HttpResponse.json(o) : problem(404, `Объекта ${params.id} нет`);
  }),
  http.get("/api/v1/objects/:id/versions/:n/content", async ({ params }) => {
    if (params.id !== MANUAL) return problem(415, "Нет превью в браузере");
    return HttpResponse.arrayBuffer(await pdf(), { headers: { "content-type": "application/pdf" } });
  }),
  http.get("/api/v1/objects/:id/versions/:n/text", ({ params, request }) => {
    if (params.id !== MANUAL) return problem(404, "Текст версии не извлечён");
    const page = Number(new URL(request.url).searchParams.get("page") ?? 0);
    return HttpResponse.json(page ? { pages: [textManual.pages[page - 1] ?? ""] } : textManual);
  }),
  http.get("/api/v1/objects/:id/versions/:n/sheet", ({ request }) => {
    const name = new URL(request.url).searchParams.get("name");
    if (name !== sheet.name) return HttpResponse.json({ name, range: "A1:A1", rows: [[null]] });
    return HttpResponse.json(sheet);
  }),
  http.get("/api/v1/changes", async ({ request }) => {
    await delay(100);
    const url = new URL(request.url);
    const who = url.searchParams.get("who") ?? "all";
    const since = url.searchParams.get("since");
    let events = freshEvents();
    if (who !== "all") events = events.filter((e) => e.agent?.startsWith(`${who}:`));
    if (since) events = events.filter((e) => e.at >= since);
    return HttpResponse.json({ ref: null, since, until: null, events });
  }),
];
