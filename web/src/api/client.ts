import createClient, { type Middleware } from "openapi-fetch";
import { offlineError, problemFromResponse } from "./errors";
import type { paths } from "./schema";

const problems: Middleware = {
  async onResponse({ response }) {
    if (!response.ok) throw await problemFromResponse(response.clone());
    return response;
  },
  onError({ error }) {
    return offlineError(error);
  },
};

/** Клиент контракта v1; компоненты к нему не обращаются напрямую, только через api/queries. */
const origin = typeof location === "undefined" ? "http://localhost" : location.origin;
// fetch берётся при каждом запросе: моки и обёртки, поставленные позже, тоже работают
export const api = createClient<paths>({
  baseUrl: `${origin}/api/v1`,
  fetch: (req) => globalThis.fetch(req),
});
api.use(problems);

/** Достать данные ответа openapi-fetch или бросить ApiError. */
export function data<T>(r: { data?: T; error?: unknown }): T {
  if (r.error !== undefined || r.data === undefined) throw r.error ?? new Error("пустой ответ");
  return r.data;
}
