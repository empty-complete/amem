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
};
