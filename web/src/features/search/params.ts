import { z } from "zod";

const list = z.preprocess(
  (v) => (v == null ? [] : Array.isArray(v) ? v.map(String) : [String(v)]),
  z.array(z.string()),
);

/** Параметры поиска в URL: проверены схемой, переживают перезагрузку и ссылку. */
export const searchParams = z.object({
  q: z.preprocess((v) => (v == null ? "" : String(v)), z.string()),
  kind: list,
  status: list,
  limit: z.preprocess((v) => (v == null ? 10 : Number(v)), z.number().int().min(1).max(100).catch(100)),
});
export type SearchParams = z.infer<typeof searchParams>;
