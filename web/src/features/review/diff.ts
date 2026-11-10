// Пословное сравнение ревизий: LCS по словам (знаки препинания — отдельные токены, пробелы сохраняются).
import { LANGS, type Lang, type LangString } from "../../ui/lang";

export type Op = "same" | "del" | "add";
export interface Piece {
  text: string;
  op: Op;
}

const tokens = (s: string) => s.match(/\s+|[\p{L}\p{N}]+|[^\s\p{L}\p{N}]/gu) ?? [];

export function wordDiff(a: string, b: string): Piece[] {
  const x = tokens(a);
  const y = tokens(b);
  const n = x.length;
  const m = y.length;
  // таблица длин LCS с конца — O(n·m), поля записей короткие
  const t: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      (t[i] as number[])[j] =
        x[i] === y[j]
          ? ((t[i + 1] as number[])[j + 1] as number) + 1
          : Math.max((t[i + 1] as number[])[j] as number, (t[i] as number[])[j + 1] as number);
  const out: Piece[] = [];
  const push = (text: string, op: Op) => {
    const last = out[out.length - 1];
    if (last && last.op === op) last.text += text;
    else out.push({ text, op });
  };
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (x[i] === y[j]) {
      push(x[i] as string, "same");
      i++;
      j++;
    } else if (((t[i + 1] as number[])[j] as number) >= ((t[i] as number[])[j + 1] as number))
      push(x[i++] as string, "del");
    else push(y[j++] as string, "add");
  }
  while (i < n) push(x[i++] as string, "del");
  while (j < m) push(y[j++] as string, "add");
  return out;
}

type Payload = Record<string, unknown>;
/** LangString (только ключи ru, en): один слот — его текст, несколько — каждый со своей приставкой, чтобы правка
 * любого языка была видна в сравнении. */
function langText(v: object): string | null {
  const keys = Object.keys(v);
  if (!keys.length || !keys.every((k) => (LANGS as readonly string[]).includes(k))) return null;
  const s = v as LangString;
  const filled = LANGS.filter((x) => typeof s[x] === "string" && (s[x] as string).trim());
  if (filled.length === 1) return s[filled[0] as Lang] as string;
  return filled.map((x) => `${x}: ${s[x]}`).join("\n");
}

const text = (v: unknown): string => {
  if (v == null) return "";
  if (typeof v === "string") return v;
  if (typeof v === "object" && !Array.isArray(v)) {
    const t = langText(v);
    if (t !== null) return t;
  }
  return JSON.stringify(v);
};

export interface FieldChange {
  field: string;
  pieces: Piece[];
}

const ORDER = [
  "label",
  "summary_plain",
  "body",
  "content",
  "about",
  "tags",
  "valid_from",
  "valid_to",
  "qualifiers",
  "sources",
];

/** Только изменённые поля, в порядке, в котором их читает человек. */
export function fieldDiff(current: Payload, proposed: Payload): FieldChange[] {
  const keys = [...new Set([...Object.keys(current), ...Object.keys(proposed)])].filter((k) => k !== "ref");
  keys.sort((a, b) => (ORDER.indexOf(a) + 1 || 99) - (ORDER.indexOf(b) + 1 || 99));
  return keys
    .map((k) => ({ field: k, a: text(current[k]), b: text(proposed[k]) }))
    .filter((x) => x.a !== x.b)
    .map((x) => ({ field: x.field, pieces: wordDiff(x.a, x.b) }));
}
