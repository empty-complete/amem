import { delay, HttpResponse, http } from "msw";
import { db, folderTree } from "./db";
import base from "./fixtures/base.json";
import search from "./fixtures/search.json";
import searchSemanticOff from "./fixtures/search-semantic-off.json";
import session from "./fixtures/session.json";
import vocabClass from "./fixtures/vocab-entity_class.json";
import vocabKind from "./fixtures/vocab-kind.json";
import vocabGroup from "./fixtures/vocab-parameter_group.json";
import vocabOrigin from "./fixtures/vocab-parameter_origin.json";

const problem = (status: number, title: string, detail?: string) =>
  HttpResponse.json(
    { type: "about:blank", title, status, detail },
    { status, headers: { "content-type": "application/problem+json" } },
  );

/** Фильтры /records, как у службы (И): папка с вложенными, «-» — без папки; статусы и виды — любой из;
 * теги — все сразу. */
export function filterSummaries<
  T extends { folder?: string | null; status: string; kind_or_class: string; tags?: string[] },
>(list: T[], url: URL): T[] {
  const folder = url.searchParams.get("folder");
  const status = url.searchParams.getAll("status").filter(Boolean);
  const kind = url.searchParams.getAll("kind").filter(Boolean);
  const tags = url.searchParams.getAll("tag").filter(Boolean);
  let items = list;
  if (folder === "-") items = items.filter((r) => !r.folder);
  else if (folder && url.searchParams.get("nested") === "false")
    items = items.filter((r) => r.folder === folder);
  else if (folder) items = items.filter((r) => r.folder === folder || r.folder?.startsWith(`${folder}/`));
  if (status.length) items = items.filter((r) => status.includes(r.status));
  if (kind.length) items = items.filter((r) => kind.includes(r.kind_or_class));
  if (tags.length) items = items.filter((r) => tags.every((t) => r.tags?.includes(t)));
  return items;
}

/** Обработчики контракта v1 на образцах (метеостанция МС-1). Особые запросы: «ошибка» — 503, «без смысла» — смысловой канал выключен. */
export const handlers = [
  http.get("/api/v1/session", () => HttpResponse.json(session)),
  http.get("/api/v1/base", () => HttpResponse.json(base)),
  http.get("/api/v1/folders", () => HttpResponse.json(folderTree())),
  http.get("/api/v1/records", async ({ request }) => {
    await delay(120);
    const url = new URL(request.url);
    const items = filterSummaries(db.records, url);
    // страницы, как у службы: limit (по умолчанию 50, до 200) и cursor — здесь смещение
    const limit = Math.min(Number(url.searchParams.get("limit") ?? 50), 200);
    const from = Number(url.searchParams.get("cursor") ?? 0);
    const next = from + limit < items.length ? String(from + limit) : null;
    return HttpResponse.json({
      items: items.slice(from, from + limit),
      total: items.length,
      next_cursor: next,
    });
  }),
  http.get("/api/v1/search", async ({ request }) => {
    await delay(150);
    const url = new URL(request.url);
    const q = (url.searchParams.get("q") ?? "").trim();
    const kinds = url.searchParams.getAll("kind");
    if (q === "ошибка") return problem(503, "Служба недоступна", "База не отвечает");
    // выбор сущности (@объект, «о чём»): ищем по всем сущностям базы, а не по образцам выдачи
    if (url.searchParams.get("target") === "entity") {
      const w = q === "*" ? "" : q.toLowerCase();
      const hits = db.records
        .filter((r) => r.target === "entity" && r.label.toLowerCase().includes(w))
        .slice(0, Number(url.searchParams.get("limit") ?? 10))
        .map((r, i) => ({
          ref: r.ref,
          revision: 1,
          label: r.label,
          snippet: "",
          status: r.status,
          review_state: "none",
          entity_class: r.kind_or_class,
          score: 1 - i / 100,
          matches: [],
        }));
      return HttpResponse.json({ ...search, items: hits, candidate_count: hits.length });
    }
    const result = q === "без смысла" ? searchSemanticOff : search;
    let items = q ? result.items : [];
    if (kinds.length) items = items.filter((i) => kinds.includes(i.kind));
    const limit = Number(url.searchParams.get("limit") ?? 10);
    return HttpResponse.json({ ...result, items: items.slice(0, limit), candidate_count: items.length });
  }),
  // теги на записях с частотой, как у службы: сначала частые, q — начало тега без регистра
  http.get("/api/v1/tags", ({ request }) => {
    const url = new URL(request.url);
    const q = (url.searchParams.get("q") ?? "").replace(/^#/, "").toLowerCase();
    const counts = new Map<string, number>();
    for (const r of db.records) for (const t of r.tags ?? []) counts.set(t, (counts.get(t) ?? 0) + 1);
    const items = [...counts]
      .filter(([t]) => t.toLowerCase().startsWith(q))
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .slice(0, Number(url.searchParams.get("limit") ?? 50))
      .map(([tag, count]) => ({ tag, count }));
    return HttpResponse.json(items);
  }),
  http.get("/api/v1/vocab/kind", () => HttpResponse.json(vocabKind)),
  http.get("/api/v1/vocab/entity_class", () => HttpResponse.json(vocabClass)),
  // прочие словари пакетов (parameter_group, parameter_origin…): неизвестная схема — пустой список, как у службы
  http.get("/api/v1/vocab/:scheme", ({ params }) =>
    HttpResponse.json(
      ({ parameter_group: vocabGroup, parameter_origin: vocabOrigin } as Record<string, unknown[]>)[
        String(params.scheme)
      ] ?? [],
    ),
  ),
];
