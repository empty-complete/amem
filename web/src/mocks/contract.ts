// Сверка ответов моков с контрактом во время тестов (Vitest, Node): путь и метод → операция OpenAPI →
// схема ответа по коду. Фикстуры сверяет tests/contract.test.ts; здесь — то, что обработчики собирают сами
// (после правок в db, ответы POST, problem+json). Служба сверяет свои ответы с тем же файлом.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import Ajv2020, { type ValidateFunction } from "ajv/dist/2020.js";
import addFormats from "ajv-formats";
import { parse } from "yaml";

type Json = Record<string, unknown>;
type Op = { method: string; re: RegExp; template: string; responses: Json };

const spec = parse(readFileSync(resolve(process.cwd(), "../docs/api/http-v1.openapi.yaml"), "utf8")) as Json;
const ajv = new Ajv2020({ strict: false, allErrors: true });
addFormats(ajv);
ajv.addSchema({ $id: "openapi", ...spec });

const BASE = ((spec.servers as { url: string }[] | undefined)?.[0]?.url ?? "").replace(/\/$/, "");
const METHODS = ["get", "post", "put", "patch", "delete"];
const pointer = (...parts: string[]) =>
  parts.map((p) => p.replaceAll("~", "~0").replaceAll("/", "~1")).join("/");

const ops: Op[] = [];
for (const [template, item] of Object.entries(spec.paths as Record<string, Json>)) {
  const re = new RegExp(`^${template.replace(/[.*+?^$()|[\]\\]/g, "\\$&").replace(/\{[^}]+\}/g, "[^/]+")}$`);
  for (const method of METHODS) {
    const op = item[method] as Json | undefined;
    if (op) ops.push({ method: method.toUpperCase(), re, template, responses: (op.responses ?? {}) as Json });
  }
}
// точные пути раньше шаблонных: /records/{ref} не должен поймать /records/move
ops.sort((a, b) => (a.template.match(/\{/g)?.length ?? 0) - (b.template.match(/\{/g)?.length ?? 0));

const cache = new Map<string, ValidateFunction | null>();

/** Схема JSON-ответа операции по коду (или default); нет её в контракте — null. */
function validator(op: Op, status: number, type: string): ValidateFunction | null {
  const key = `${op.method} ${op.template} ${status} ${type}`;
  if (cache.has(key)) return cache.get(key) ?? null;
  const code = String(status) in op.responses ? String(status) : "default";
  let at = ["paths", op.template, op.method.toLowerCase(), "responses", code];
  let resp = op.responses[code] as Json | undefined;
  const ref = resp?.$ref as string | undefined;
  if (ref?.startsWith("#/")) {
    at = ref.slice(2).split("/");
    resp = at.reduce<Json | undefined>((o, k) => o?.[k] as Json | undefined, spec);
  }
  const content = resp?.content as Record<string, Json> | undefined;
  const media = content?.[type] ? type : content?.["application/json"] ? "application/json" : undefined;
  const fn =
    media && content?.[media]?.schema
      ? ajv.compile({ $ref: `openapi#/${pointer(...at, "content", media, "schema")}` })
      : null;
  cache.set(key, fn);
  return fn;
}

/** Ошибки сверки одного ответа мока; пустой список — ответ по контракту. */
export async function checkResponse(request: Request, response: Response): Promise<string[]> {
  const url = new URL(request.url);
  if (!url.pathname.startsWith(`${BASE}/`)) return [];
  const type = (response.headers.get("content-type") ?? "").split(";")[0]?.trim() ?? "";
  if (!type.endsWith("json")) return [];
  const path = url.pathname.slice(BASE.length);
  const where = `${request.method} ${path} → ${response.status}`;
  const op = ops.find((o) => o.method === request.method && o.re.test(path));
  if (!op) return [`${where}: нет в контракте`];
  if (!(String(response.status) in op.responses) && !("default" in op.responses))
    return [`${where}: код не описан в контракте`];
  const fn = validator(op, response.status, type);
  if (!fn) return [`${where}: у ответа нет JSON-схемы в контракте`];
  const body = await response.clone().json();
  return fn(body) ? [] : [`${where}: ${ajv.errorsText(fn.errors, { dataVar: "ответ" })}`];
}
