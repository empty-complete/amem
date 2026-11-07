// Папки: пути вносит в контракт служба (часть 4a); до слияния — прямой fetch с тем же разбором problem+json.
import { problemFromResponse } from "./errors";

const base = () => `${typeof location === "undefined" ? "http://localhost" : location.origin}/api/v1`;

async function call(method: string, path: string, body?: unknown) {
  const res = await globalThis.fetch(`${base()}${path}`, {
    method,
    headers: body ? { "content-type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    credentials: "same-origin",
  });
  if (!res.ok) throw await problemFromResponse(res);
}

const enc = (p: string) => encodeURIComponent(p);

export const folderApi = {
  create: (path: string) => call("POST", "/folders", { path }),
  rename: (from: string, to: string) => call("PATCH", `/folders/${enc(from)}`, { path: to }),
  remove: (path: string) => call("DELETE", `/folders/${enc(path)}`),
};
