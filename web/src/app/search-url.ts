/** Параметры в URL читаемо: массивы — повтором ключа (kind=a&kind=b), пустые и значения по умолчанию не пишутся. */
const DEFAULTS: Record<string, unknown> = { limit: 10 };

export function stringifySearch(search: Record<string, unknown>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(search)) {
    if (v === undefined || v === null || v === "" || DEFAULTS[k] === v) continue;
    if (Array.isArray(v)) for (const x of v) p.append(k, String(x));
    else p.append(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

export function parseSearch(searchStr: string): Record<string, unknown> {
  const p = new URLSearchParams(searchStr.startsWith("?") ? searchStr.slice(1) : searchStr);
  const out: Record<string, unknown> = {};
  for (const k of new Set(p.keys())) {
    const all = p.getAll(k);
    out[k] = all.length > 1 ? all : all[0];
  }
  return out;
}
