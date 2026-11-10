// Документ правки + шаблон вида → предложение check.submit (новая запись или ревизия) и обратно — замечания к полям.
// Текст — в слот языка (ui/lang): правка — в тот слот, из которого текст показан, новое — в язык интерфейса.
import type { components } from "../../api/schema";
import { i18n } from "../../app/i18n";
import { editSlot, hasText, type LangString, pickText, withText } from "../../ui/lang";

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

/** Текст value в поле key тела: в слот правки; пустой — слот убирается, а без текста в слотах — и поле. */
function putText(payload: Record<string, unknown>, key: string, value: string, lang: string) {
  const cur = payload[key] as LangString | null | undefined;
  const next = withText(cur && typeof cur === "object" ? cur : null, value, lang);
  if (!value) delete next[editSlot(cur, lang)];
  if (hasText(next)) payload[key] = next;
  else delete payload[key];
}
/** Имя новой записи внутри пакета (`@[a-z0-9_]+`). */
export const NEW_REF = "@n0";
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

/** Документ → Proposal. base — текущее тело при правке: неизвестные форме поля и другие языковые слоты
 * сохраняются; lang — язык правки (по умолчанию — интерфейса). */
export function toProposal(
  d: Draft,
  t: Template | undefined,
  opts: {
    recordId?: string | null;
    base?: Record<string, unknown>;
    resolve?: (label: string) => string | undefined;
    lang?: string;
  } = {},
): { proposal: Proposal; links: LinkProposal[] } {
  const lang = opts.lang ?? i18n.language;
  const payload: Record<string, unknown> = structuredClone(opts.base ?? {});
  if (d.target === "entity") payload.entity_class = d.kind;
  else payload.kind = d.kind;
  putText(payload, "label", d.label.trim(), lang);
  putText(payload, "summary_plain", d.summary.trim(), lang);
  putText(payload, "body", t?.body !== "none" ? d.body.trim() : "", lang);
  // без шаблона (ещё не загрузился) простые ключи — это и есть пути в теле: about, tags, valid_from
  const form = t?.form ?? Object.keys(d.values).map((k) => ({ key: k, path: k, type: "text" }) as FormField);
  for (const f of form) if (f.key in d.values) put(payload, f, d.values[f.key]);
  if (d.extra.length) {
    const own = new Set(d.extra.map((x) => x.property));
    const all = (payload.qualifiers ?? []) as { property: string; label?: LangString }[];
    const before = new Map(all.map((q) => [q.property, q.label]));
    payload.qualifiers = [
      ...all.filter((q) => !own.has(q.property)),
      ...d.extra
        .filter((x) => x.value.trim())
        .map((x) => ({
          property: x.property,
          label: withText(before.get(x.property), x.label, lang),
          value_text: x.value.trim(),
        })),
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
  // новой записи — имя в пакете: связи ссылаются на него, проверка ищет его в payload.ref
  if (!opts.recordId) payload.ref = NEW_REF;
  else delete payload.ref;
  const src = opts.recordId ?? NEW_REF;
  const links = [...d.body.matchAll(WIKI)]
    .map((m) => opts.resolve?.(m[1] as string))
    .filter((x): x is string => !!x)
    .map((dst) => ({ src, dst, rel: dst.startsWith("ent:") ? "about" : "see_also" }));
  // record_id в /submit — UUID записи без приставки atm:/ent: (контракт 4a)
  const recordId = opts.recordId ? opts.recordId.replace(/^(atm|ent):/, "") : null;
  return { proposal: { target: d.target, payload, record_id: recordId }, links };
}

/** Пояснение «простыми словами» ядро требует у каждого атома (шаблон has_label). Где человек его не дал —
 * заметка одной строкой, значение из карточки, — им становится заголовок: это и есть его слова.
 * Зовётся перед каждой отправкой /submit, чтобы правило жило в одном месте. */
export function withSummary<T extends { proposals: Proposal[] }>(body: T): T {
  return {
    ...body,
    proposals: body.proposals.map((p) => {
      const pl = p.payload as { label?: LangString; summary_plain?: LangString };
      if (p.target !== "atom" || hasText(pl.summary_plain) || !hasText(pl.label)) return p;
      return { ...p, payload: { ...p.payload, summary_plain: { ...pl.label } } };
    }),
  };
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

/** Тело записи → документ правки по форме шаблона (обратный путь для правки своей записи); текст — на языке
 * lang с заменой (по умолчанию — интерфейса), тот же слот toProposal потом и правит. */
export function fromPayload(
  p: Record<string, unknown>,
  t: Template | undefined,
  target: "atom" | "entity",
  lang: string = i18n.language,
): Draft {
  const s = (x: unknown) => pickText(x as LangString | null | undefined, lang);
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
  d.extra = ((p.qualifiers ?? []) as { property: string; label?: LangString; value_text?: string }[])
    .filter((q) => !known.has(q.property))
    .map((q) => ({ property: q.property, label: s(q.label) || q.property, value: q.value_text ?? "" }));
  d.sources = ((p.sources ?? []) as DraftSource[]).map((x) => ({ ...x, selectors: x.selectors ?? [] }));
  d.basis = p.basis as Draft["basis"];
  return d;
}
