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

/** Обработчики контракта v1 на образцах (метеостанция МС-1). Особые запросы: «ошибка» — 503, «без смысла» — смысловой канал выключен. */
export const handlers = [
  http.get("/api/v1/session", () => HttpResponse.json(session)),
  http.get("/api/v1/base", () => HttpResponse.json(base)),
  http.get("/api/v1/folders", () => HttpResponse.json(folderTree())),
  http.get("/api/v1/records", async ({ request }) => {
    await delay(120);
    const url = new URL(request.url);
    const folder = url.searchParams.get("folder");
    const status = url.searchParams.getAll("status");
    let items = db.records;
    if (folder === "-") items = items.filter((r) => !r.folder);
    else if (folder) items = items.filter((r) => r.folder === folder || r.folder?.startsWith(`${folder}/`));
    if (status.length) items = items.filter((r) => status.includes(r.status));
    return HttpResponse.json({ items, total: items.length, next_cursor: null });
  }),
  http.get("/api/v1/search", async ({ request }) => {
    await delay(150);
    const url = new URL(request.url);
    const q = (url.searchParams.get("q") ?? "").trim();
    const kinds = url.searchParams.getAll("kind");
    if (q === "ошибка") return problem(503, "Служба недоступна", "База не отвечает");
    const result = q === "без смысла" ? searchSemanticOff : search;
    let items = q ? result.items : [];
    if (kinds.length) items = items.filter((i) => kinds.includes(i.kind));
    const limit = Number(url.searchParams.get("limit") ?? 10);
    return HttpResponse.json({ ...result, items: items.slice(0, limit), candidate_count: items.length });
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
