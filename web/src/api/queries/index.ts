import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";
import { api, data } from "../client";
import type { components } from "../schema";

/** Фабрики запросов: компоненты не знают путей API, только эти функции. */
/** Пунктов очереди в одном запросе — предел контракта (/review/items, limit до 500). */
export const REVIEW_LIMIT = 500;

/** Фильтр списка записей (адрес страницы /records). */
export interface RecordFilter {
  tag?: string[];
  kind?: string[];
  status?: components["schemas"]["Status"][];
  about?: string;
}

/** Параметры /records для папки и фильтра; пустые не передаются. */
export function recordQuery(folder: string | null, f: RecordFilter) {
  return {
    ...(folder ? { folder } : {}),
    ...(f.tag?.length ? { tag: f.tag } : {}),
    ...(f.kind?.length ? { kind: f.kind } : {}),
    ...(f.status?.length ? { status: f.status } : {}),
    ...(f.about ? { about: f.about } : {}),
  };
}

/** Все ссылки под фильтром — по страницам у службы («Выбрать все отобранные», а не только загруженные). */
export async function allRecordRefs(folder: string | null, f: RecordFilter) {
  const refs: string[] = [];
  let cursor: string | null = null;
  do {
    const page: components["schemas"]["RecordList"] = data(
      await api.GET("/records", {
        params: { query: { ...recordQuery(folder, f), limit: 200, ...(cursor ? { cursor } : {}) } },
      }),
    );
    refs.push(...page.items.map((r) => r.ref));
    cursor = page.next_cursor ?? null;
  } while (cursor);
  return refs;
}

export const q = {
  session: () =>
    queryOptions({
      queryKey: ["session"],
      queryFn: async () => data(await api.GET("/session")),
      staleTime: 5 * 60_000,
    }),
  updates: () =>
    queryOptions({
      queryKey: ["updates"],
      queryFn: async () => data(await api.GET("/updates")),
    }),
  base: () =>
    queryOptions({
      queryKey: ["base"],
      queryFn: async () => data(await api.GET("/base")),
      refetchInterval: 60_000,
    }),
  folders: () =>
    queryOptions({ queryKey: ["folders"], queryFn: async () => data(await api.GET("/folders")) }),
  records: (folder: string | null) =>
    queryOptions({
      queryKey: ["records", folder],
      queryFn: async () => data(await api.GET("/records", { params: { query: folder ? { folder } : {} } })),
    }),
  /** Список записей страницами по cursor (предел контракта — 200): «Все записи» и папка доходят до конца.
   * Фильтры складываются (И): теги — все сразу, виды и статусы — любой из. */
  recordPages: (folder: string | null, f: RecordFilter = {}, nested = true) =>
    infiniteQueryOptions({
      queryKey: ["records", folder, "pages", f, nested],
      initialPageParam: null as string | null,
      queryFn: async ({ pageParam }) =>
        data(
          await api.GET("/records", {
            params: {
              query: {
                ...recordQuery(folder, f),
                ...(nested ? {} : { nested: false }),
                limit: 200,
                ...(pageParam ? { cursor: pageParam } : {}),
              },
            },
          }),
        ),
      getNextPageParam: (last) => last.next_cursor ?? null,
    }),
  search: (p: { q: string; kind: string[]; status: string[]; limit: number }) =>
    queryOptions({
      queryKey: ["search", p],
      enabled: p.q.trim().length > 0,
      queryFn: async () =>
        data(
          await api.GET("/search", {
            params: {
              query: {
                q: p.q,
                kind: p.kind.length ? p.kind : undefined,
                status: p.status.length ? (p.status as never) : undefined,
                limit: p.limit,
              },
            },
          }),
        ),
    }),
  vocab: (scheme: string) =>
    queryOptions({
      queryKey: ["vocab", scheme],
      queryFn: async () => data(await api.GET("/vocab/{scheme}", { params: { path: { scheme } } })),
      staleTime: Infinity,
    }),
  record: (ref: string) =>
    queryOptions({
      queryKey: ["record", ref],
      queryFn: async () => data(await api.GET("/records/{ref}", { params: { path: { ref } } })),
    }),
  /** Запись с прежней ревизией n: сравнение и «Вернуть эту ревизию». */
  recordAt: (ref: string, n: number) =>
    queryOptions({
      queryKey: ["record", ref, "rev", n],
      queryFn: async () =>
        data(await api.GET("/records/{ref}", { params: { path: { ref }, query: { revision: n } } })),
      staleTime: Infinity,
    }),
  history: (ref: string) =>
    queryOptions({
      queryKey: ["history", ref],
      queryFn: async () => data(await api.GET("/records/{ref}/history", { params: { path: { ref } } })),
    }),
  links: (ref: string) =>
    queryOptions({
      queryKey: ["links", ref],
      queryFn: async () => data(await api.GET("/records/{ref}/links", { params: { path: { ref } } })),
    }),
  similar: (ref: string) =>
    queryOptions({
      queryKey: ["similar", ref],
      queryFn: async () => data(await api.GET("/similar", { params: { query: { ref } } })),
      staleTime: 5 * 60_000,
    }),
  about: (about: string) =>
    queryOptions({
      queryKey: ["records-about", about],
      queryFn: async () => data(await api.GET("/records", { params: { query: { about } } })),
    }),
  card: (ref: string) =>
    queryOptions({
      queryKey: ["card", ref],
      queryFn: async () => data(await api.GET("/entities/{ref}/card", { params: { path: { ref } } })),
    }),
  object: (id: string) =>
    queryOptions({
      queryKey: ["object", id],
      queryFn: async () => data(await api.GET("/objects/{id}", { params: { path: { id } } })),
    }),
  objectText: (id: string, n: number, page?: number) =>
    queryOptions({
      queryKey: ["object-text", id, n, page],
      queryFn: async () =>
        data(
          await api.GET("/objects/{id}/versions/{n}/text", { params: { path: { id, n }, query: { page } } }),
        ),
      staleTime: Infinity,
    }),
  sheet: (id: string, n: number, name: string) =>
    queryOptions({
      queryKey: ["sheet", id, n, name],
      queryFn: async () =>
        data(
          await api.GET("/objects/{id}/versions/{n}/sheet", { params: { path: { id, n }, query: { name } } }),
        ),
      staleTime: Infinity,
    }),
  templates: (target?: "atom" | "entity") =>
    queryOptions({
      queryKey: ["templates", target ?? "all"],
      queryFn: async () => data(await api.GET("/templates", { params: { query: { target } } })),
      staleTime: 5 * 60_000,
    }),
  pick: (target: "atom" | "entity", text: string) =>
    queryOptions({
      queryKey: ["pick", target, text],
      queryFn: async () =>
        data(await api.GET("/search", { params: { query: { q: text || "*", target, limit: 8 } } })),
      staleTime: 30_000,
    }),
  /** Теги на записях с частотой (подсказки # и поля тегов); text — начало тега. */
  tags: (text: string) =>
    queryOptions({
      queryKey: ["tags", text],
      queryFn: async () =>
        data(await api.GET("/tags", { params: { query: { q: text || undefined, limit: 8 } } })),
      staleTime: 30_000,
    }),
  objects: (text: string) =>
    queryOptions({
      queryKey: ["objects", text],
      queryFn: async () =>
        data(await api.GET("/objects", { params: { query: { q: text || undefined, limit: 20 } } })),
    }),
  tasks: (object: string) =>
    queryOptions({
      queryKey: ["tasks", object],
      queryFn: async () => data(await api.GET("/tasks", { params: { query: { object } } })),
    }),
  reviewItems: (p: { state: "open" | "done"; reason?: string }) =>
    queryOptions({
      queryKey: ["review-items", p],
      // без state служба отдаёт пункты в любом состоянии (контракт); открытые для человека — queued и claimed
      queryFn: async () => {
        const states = p.state === "done" ? (["done"] as const) : (["queued", "claimed"] as const);
        const lists = await Promise.all(
          states.map(async (state) =>
            data(
              await api.GET("/review/items", {
                // предел контракта: без limit служба отдаёт 100, и длинная очередь молча обрезалась бы
                params: { query: { state, reason: (p.reason || undefined) as never, limit: REVIEW_LIMIT } },
              }),
            ),
          ),
        );
        return lists.flat().sort((a, b) => b.created_at.localeCompare(a.created_at));
      },
      refetchOnWindowFocus: true,
    }),
  reviewItem: (id: string) =>
    queryOptions({
      queryKey: ["review-item", id],
      queryFn: async () => data(await api.GET("/review/items/{id}", { params: { path: { id } } })),
    }),
  reviewStats: (days = 7) =>
    queryOptions({
      queryKey: ["review-stats", days],
      queryFn: async () => data(await api.GET("/review/stats", { params: { query: { days } } })),
    }),
  backups: () =>
    queryOptions({ queryKey: ["backups"], queryFn: async () => data(await api.GET("/backups")) }),
  /** Небо: окрестность записи (ref) или обзор базы; tag, kind, folder сужают только обзор. */
  graph: (p: {
    ref?: string;
    depth: number;
    project?: string;
    limit?: number;
    tag?: string[];
    kind?: string;
    folder?: string;
  }) =>
    queryOptions({
      queryKey: ["graph", p],
      queryFn: async () =>
        data(
          await api.GET("/graph", {
            params: {
              query: {
                ref: p.ref,
                depth: p.depth,
                project: p.project,
                limit: p.limit,
                ...(p.tag?.length ? { tag: p.tag } : {}),
                ...(p.kind ? { kind: [p.kind] } : {}),
                ...(p.folder ? { folder: p.folder } : {}),
              },
            },
          }),
        ),
      staleTime: 60_000,
    }),
  changes: (p: { who: "all" | "person" | "model"; since?: string }) =>
    queryOptions({
      queryKey: ["changes", p],
      queryFn: async () =>
        data(await api.GET("/changes", { params: { query: { who: p.who, since: p.since } } })),
    }),
};

/** Адрес файла версии — для pdf.js и «Открыть файл». */
export const contentUrl = (id: string, n: number) =>
  `${globalThis.location?.origin ?? ""}/api/v1/objects/${encodeURIComponent(id)}/versions/${n}/content`;
