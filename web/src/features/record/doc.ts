// Документ записи: шапка YAML (поля и свои ключи) + тело Markdown — правила разд. 5.4 спецификации.
import { parse, stringify } from "yaml";
import { type LangString, pickText } from "../../ui/lang";

type Qualifier = { property: string; label?: LangString; value_text?: string | null };
export interface AtomPayload {
  kind?: string;
  entity_class?: string;
  label: LangString;
  summary_plain?: LangString | null;
  description?: LangString | null;
  body?: LangString | null;
  tags?: string[];
  basis?: string | null;
  qualifiers?: Qualifier[];
}
export interface RefLabel {
  ref: string;
  label: string;
}
export interface SourceLike {
  object_name?: string;
  quote?: string | null;
  selectors?: { type: string; value?: unknown; label?: string }[];
}
export interface DocRecord {
  kind: string;
  label: string;
  summary_plain: string;
  body: string;
  about: string[];
  tags: string[];
  basis?: string;
  quote?: string;
  source?: string;
  page?: string;
  qualifiers: Record<string, string>;
  links: { rel: "see_also"; label: string }[];
}

const KNOWN = new Set(["kind", "about", "source", "page", "tags", "basis"]);
const WIKI = /\[\[([^\]\n]+)\]\]/g;

const wikiLabels = (s: string) => [...s.matchAll(WIKI)].map((m) => m[1] as string);

export function recordToDocument(
  p: AtomPayload,
  about: RefLabel[] = [],
  sources: SourceLike[] = [],
  lang = "ru",
): string {
  const head: Record<string, unknown> = { kind: p.kind ?? p.entity_class ?? "note" };
  // у атома «о чём» и теги в шапке всегда, пустые тоже: видно, что их можно заполнить
  const atom = !p.entity_class;
  if (about.length) head.about = about.map((a) => `[[${a.label}]]`).join(", ");
  else if (atom) head.about = null;
  const s = sources[0];
  if (s?.object_name) {
    head.source = s.object_name;
    const page = s.selectors?.find((x) => x.type === "page");
    if (page) head.page = page.label ?? String(page.value);
  }
  if (p.tags?.length) head.tags = p.tags;
  else if (atom) head.tags = [];
  if (p.basis) head.basis = p.basis;
  for (const q of p.qualifiers ?? []) if (q.value_text) head[q.property] = q.value_text;
  // [[…]] в YAML — строка в кавычках; в документе их не видно, как в Obsidian.
  const yaml = stringify(head, { lineWidth: 0 })
    .replace(/"(\[\[[^"]+\]\](?:, \[\[[^"]+\]\])*)"/g, "$1")
    .replace(/^about: null$/m, "about:");
  const summary = pickText(p.summary_plain ?? p.description, lang);
  const quote = s?.quote ? `\n## Цитата\n> ${s.quote}\n` : "";
  const body = pickText(p.body, lang);
  return `---\n${yaml}---\n# ${pickText(p.label, lang)}\n${summary ? `\n${summary}\n` : ""}${quote}${body ? `\n${body}\n` : ""}`;
}

export function documentToRecord(doc: string): DocRecord {
  const m = doc.match(/^---\n([\s\S]*?)\n?---\n([\s\S]*)$/);
  const rawHead = (m?.[1] ?? "").replace(
    /^(\w+): (\[\[.*\]\])\s*$/gm,
    (_, k, v) => `${k}: ${JSON.stringify(v)}`,
  );
  const head = ((m ? parse(rawHead) : null) ?? {}) as Record<string, unknown>;
  const lines = (m ? (m[2] ?? "") : doc).replace(/^\n+/, "").split("\n");
  const label = (lines[0] ?? "").replace(/^#\s+/, "").trim();
  let rest = lines.slice(1).join("\n").trim();
  let quote: string | undefined;
  const qm = rest.match(/(?:^|\n)##\s*Цитата\s*\n((?:>.*(?:\n|$))+)/);
  if (qm) {
    quote = (qm[1] ?? "").replace(/^>\s?/gm, "").replace(/\n/g, " ").trim();
    rest = rest.replace(qm[0], "\n").trim();
  }
  const first = rest.split(/\n\s*\n/)[0] ?? "";
  const isPara = first && !/^(#|>|-|\*|\d+\.|\$\$|```)/.test(first.trimStart());
  const summary_plain = isPara ? first.trim() : "";
  const body = (isPara ? rest.slice(first.length) : rest).trim();
  const qualifiers: Record<string, string> = {};
  for (const [k, v] of Object.entries(head)) if (!KNOWN.has(k) && v != null) qualifiers[k] = String(v);
  return {
    kind: String(head.kind ?? "note"),
    label,
    summary_plain,
    body,
    about: wikiLabels(String(head.about ?? "")),
    tags: Array.isArray(head.tags) ? head.tags.map(String) : [],
    basis: head.basis ? String(head.basis) : undefined,
    quote,
    source: head.source ? String(head.source) : undefined,
    page: head.page != null ? String(head.page) : undefined,
    qualifiers,
    links: wikiLabels(body).map((l) => ({ rel: "see_also" as const, label: l })),
  };
}
