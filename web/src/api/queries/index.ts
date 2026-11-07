import { queryOptions } from "@tanstack/react-query";
import { api, data } from "../client";

/** Фабрики запросов: компоненты не знают путей API, только эти функции. */
export const q = {
  session: () =>
    queryOptions({
      queryKey: ["session"],
      queryFn: async () => data(await api.GET("/session")),
      staleTime: 5 * 60_000,
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
  graph: (p: { ref?: string; depth: number; project?: string; limit?: number }) =>
    queryOptions({
      queryKey: ["graph", p],
      queryFn: async () =>
        data(
          await api.GET("/graph", {
            params: { query: { ref: p.ref, depth: p.depth, project: p.project, limit: p.limit } },
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
