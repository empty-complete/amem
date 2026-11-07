// Документ правки + шаблон вида → предложение check.submit (новая запись или ревизия) и обратно — замечания к полям.
import type { components } from "../../api/schema";

export type Template = components["schemas"]["TemplateView"];
export type FormField = components["schemas"]["FormField"];
export type CheckIssue = components["schemas"]["CheckIssue"];

export interface Quantity {
  amount?: number | null;
  lower_bound?: number | null;
  upper_bound?: number | null;
  value_text?: string | null;
  unit?: string | null;
  property?: string | null;
  value_state?: "unknown" | null;
}
export type FieldValue = string[] | string | Quantity | { from?: string; to?: string } | null | undefined;
export interface DraftSource {
  object: string;
  object_name?: string;
  object_version: number;
  media_type?: string | null;
  selectors: { type: string; value: string; label?: string }[];
  quote?: string | null;
}
export interface Draft {
  kind: string;
  target: "atom" | "entity";
  label: string;
  summary: string;
  body: string;
  values: Record<string, FieldValue>;
  extra: { property: string; label: string; value: string }[];
  sources: DraftSource[];
  folder?: string | null;
  basis?: "author" | "default" | "assumed";
  derived_from?: string[];
}
export interface Proposal {
  target: "atom" | "entity";
  payload: Record<string, unknown>;
  record_id: string | null;
}
export interface LinkProposal {
  src: string;
  dst: string;
  rel: string;
}

export const emptyDraft = (kind = "note", target: "atom" | "entity" = "atom"): Draft => ({
  kind,
  target,
  label: "",
  summary: "",
  body: "",
  values: {},
  extra: [],
  sources: [],
});

const ls = (ru: string) => ({ ru });
const WIKI = /\[\[([^\]\n]+)\]\]/g;
const propIn = (path: string) => path.match(/\[property=([^\]]+)\]/)?.[1] ?? null;

/** Значение формы — в тело записи по пути FormField.path. */
function put(payload: Record<string, unknown>, f: FormField, v: FieldValue) {
  const empty = v == null || v === "" || (Array.isArray(v) && v.length === 0);
  if (f.path.startsWith("content.values")) {
    const q = (v ?? {}) as Quantity;
    const has =
      q.amount != null || q.lower_bound != null || q.upper_bound != null || q.value_text || q.value_state;
    const content = (payload.content ?? {}) as { values?: Quantity[] };
    const property = q.property ?? f.property ?? propIn(f.path) ?? "value";
    const rest = (content.values ?? []).filter((x) => x.property !== property);
    content.values = has
      ? [...rest, { property, ...strip(q), unit: q.unit ?? f.unit ?? undefined } as Quantity]
      : rest;
    if (content.values.length) payload.content = content;
    else delete payload.content;
    return;
  }
  if (f.path.startsWith("qualifiers")) {
    const property = propIn(f.path) ?? f.key;
    const qs = ((payload.qualifiers ?? []) as { property: string; value_text?: string }[]).filter(
      (q) => q.property !== property,
    );
    if (!empty) qs.push({ property, value_text: String(v) });
    payload.qualifiers = qs;
    return;
  }
  if (f.type === "period") {
    const p = (v ?? {}) as { from?: string; to?: string };
    if (p.from) payload.valid_from = p.from;
    else delete payload.valid_from;
    if (p.to) payload.valid_to = p.to;
    else delete payload.valid_to;
    return;
  }
  if (empty) delete payload[f.path];
  else payload[f.path] = v;
}

const strip = (q: Quantity) =>
  Object.fromEntries(
    Object.entries(q).filter(([k, x]) => x != null && x !== "" && k !== "property"),
  ) as Quantity;

/** Документ → Proposal. base — текущее тело при правке: неизвестные форме поля сохраняются. */
export function toProposal(
  d: Draft,
  t: Template | undefined,
  opts: {
    recordId?: string | null;
    base?: Record<string, unknown>;
    resolve?: (label: string) => string | undefined;
  } = {},
): { proposal: Proposal; links: LinkProposal[] } {
  const payload: Record<string, unknown> = structuredClone(opts.base ?? {});
  if (d.target === "entity") payload.entity_class = d.kind;
  else payload.kind = d.kind;
  payload.label = ls(d.label.trim());
  if (d.summary.trim()) payload.summary_plain = ls(d.summary.trim());
  else delete payload.summary_plain;
  if (d.body.trim() && t?.body !== "none") payload.body = ls(d.body.trim());
  else delete payload.body;
  for (const f of t?.form ?? []) if (f.key in d.values) put(payload, f, d.values[f.key]);
  if (d.extra.length) {
    const own = new Set(d.extra.map((x) => x.property));
    const qs = ((payload.qualifiers ?? []) as { property: string }[]).filter((q) => !own.has(q.property));
    payload.qualifiers = [
      ...qs,
      ...d.extra
        .filter((x) => x.value.trim())
        .map((x) => ({ property: x.property, label: ls(x.label), value_text: x.value.trim() })),
    ];
  }
  if (d.sources.length) {
    payload.sources = d.sources.map((s) => ({
      object: s.object,
      object_version: s.object_version,
      selectors: s.selectors,
      ...(s.quote ? { quote: s.quote } : {}),
    }));
    if (payload.basis === "author") delete payload.basis;
  } else {
    delete payload.sources;
    payload.basis = d.basis ?? (payload.basis as string | undefined) ?? "author";
  }
  if (d.derived_from?.length) payload.derived_from = d.derived_from;
  if (d.folder !== undefined)
    payload.scope = { ...((payload.scope as object) ?? {}), folder: d.folder ?? undefined };
  const src = opts.recordId ?? "@0";
  const links = [...d.body.matchAll(WIKI)]
    .map((m) => opts.resolve?.(m[1] as string))
    .filter((x): x is string => !!x)
    .map((dst) => ({ src, dst, rel: dst.startsWith("ent:") ? "about" : "see_also" }));
  return { proposal: { target: d.target, payload, record_id: opts.recordId ?? null }, links };
}

export interface FieldIssues {
  label?: string;
  body?: string;
  fields: Record<string, string>;
  sources: Record<number, string>;
  other: string[];
}

/** Замечания проверки → к полям формы: путь внутри предложения сопоставляется с FormField.path. */
export function issuesToFields(issues: CheckIssue[], t: Template | undefined): FieldIssues {
  const out: FieldIssues = { fields: {}, sources: {}, other: [] };
  for (const i of issues) {
    const p = i.path ?? "";
    const src = p.match(/^sources\[(\d+)\]/);
    const field = t?.form.find(
      (f) =>
        p === f.path ||
        p.startsWith(f.path) ||
        (p.startsWith("content.values") && f.path.startsWith("content.values")),
    );
    if (p.startsWith("label")) out.label = i.message;
    else if (p.startsWith("body") || p.startsWith("summary_plain")) out.body = i.message;
    else if (src) out.sources[Number(src[1])] = i.message;
    else if (field) out.fields[field.key] = i.message;
    else out.other.push(i.message);
  }
  return out;
}

/** Тело записи → документ правки по форме шаблона (обратный путь для правки своей записи). */
export function fromPayload(
  p: Record<string, unknown>,
  t: Template | undefined,
  target: "atom" | "entity",
): Draft {
  const s = (x: unknown) => ((x as { ru?: string } | undefined)?.ru ?? "") as string;
  const d = emptyDraft(String(p.kind ?? p.entity_class ?? "note"), target);
  d.label = s(p.label);
  d.summary = s(p.summary_plain ?? p.description);
  d.body = s(p.body);
  for (const f of t?.form ?? []) {
    if (f.path.startsWith("content.values")) {
      const vals = ((p.content as { values?: Quantity[] } | undefined)?.values ?? []) as Quantity[];
      const want = f.property ?? propIn(f.path);
      const v = want ? vals.find((x) => x.property === want) : vals[0];
      if (v) d.values[f.key] = v;
    } else if (f.path.startsWith("qualifiers")) {
      const q = ((p.qualifiers ?? []) as { property: string; value_text?: string }[]).find(
        (x) => x.property === (propIn(f.path) ?? f.key),
      );
      if (q) d.values[f.key] = q.value_text ?? "";
    } else if (f.type === "period") {
      d.values[f.key] = { from: p.valid_from as string | undefined, to: p.valid_to as string | undefined };
    } else if (p[f.path] != null) d.values[f.key] = p[f.path] as FieldValue;
  }
  const known = new Set(
    (t?.form ?? []).filter((f) => f.path.startsWith("qualifiers")).map((f) => propIn(f.path) ?? f.key),
  );
  d.extra = ((p.qualifiers ?? []) as { property: string; label?: { ru: string }; value_text?: string }[])
    .filter((q) => !known.has(q.property))
    .map((q) => ({ property: q.property, label: q.label?.ru ?? q.property, value: q.value_text ?? "" }));
  d.sources = ((p.sources ?? []) as DraftSource[]).map((x) => ({ ...x, selectors: x.selectors ?? [] }));
  d.basis = p.basis as Draft["basis"];
  return d;
}
