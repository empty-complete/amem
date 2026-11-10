import createClient, { type Middleware } from "openapi-fetch";
import { i18n } from "../app/i18n";
import { langOf } from "../ui/lang";
import { auth, authHeaders } from "./auth";
import { offlineError, problemFromResponse } from "./errors";
import type { paths } from "./schema";

/** Заголовки языка для запросов к службе: подписи и фрагменты ответа — на языке интерфейса (с заменой). */
export function langHeaders(): Record<string, string> {
  return { "Accept-Language": langOf(i18n.language) };
}

const language: Middleware = {
  onRequest({ request }) {
    request.headers.set("Accept-Language", langOf(i18n.language));
    return request;
  },
};

const problems: Middleware = {
  // общая служба: токен в каждом запросе (локальная — cookie, заголовка нет)
  onRequest({ request }) {
    for (const [k, v] of Object.entries(authHeaders())) request.headers.set(k, v);
    return request;
  },
  async onResponse({ response }) {
    if (response.status === 401) auth.require();
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
api.use(language, problems);

/** Достать данные ответа openapi-fetch или бросить ApiError. */
export function data<T>(r: { data?: T; error?: unknown }): T {
  if (r.error !== undefined || r.data === undefined) throw r.error ?? new Error("пустой ответ");
  return r.data;
}
