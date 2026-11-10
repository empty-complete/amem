// Вид и поля из текста (разд. 5.9): подсказка, а не приговор — плашка вида меняется одним нажатием.
import { unitLabel } from "../../ui/format";
import { LANGS, type LangString } from "../../ui/lang";

export type InferredKind = "question" | "decision" | "lesson" | "parameter" | "note";
export interface Property {
  code: string;
  label: LangString;
  unit?: string | null;
}
export interface ObjectHint {
  ref: string;
  label: string;
  codes?: string[];
}
export interface Inferred {
  kind: InferredKind;
  label: string;
  body: string;
  about: string[];
  tags: string[];
  quantity?: { label: string; amount: number; unit: string; property?: string };
}

const DECISION = /^(решили|решение|принято|договорились)(?=[\s:,.!—-]|$)/iu;
const LESSON = /^(урок|оказалось|вывод)(?=[\s:,.!—-]|$)/iu;
const NUM = "([−-]?\\d+(?:[.,]\\d+)?)";

/** Единицы, которые человек пишет руками: подписи ru/en и коды UCUM → код. */
function unitTable(props: Property[]) {
  const t = new Map<string, string>();
  const add = (code: string) => {
    t.set(code.toLowerCase(), code);
    t.set(unitLabel(code, "ru").toLowerCase(), code);
    t.set(unitLabel(code, "en").toLowerCase(), code);
  };
  for (const c of ["%", "Cel", "hPa", "kPa", "Pa", "s", "min", "h", "V", "A", "W", "m", "mm", "m/s"]) add(c);
  for (const p of props) if (p.unit) add(p.unit);
  t.set("°", "Cel");
  t.set("град", "Cel");
  t.delete("");
  return t;
}

const toNum = (s: string) => Number(s.replace("−", "-").replace(",", "."));

/** Найти величину по подписи: «Влажность в будке» → relative_humidity по совпадению слова и единицы; подписи
 * величины — на всех языках: человек пишет на своём, а не на языке интерфейса. */
function guessProperty(label: string, unit: string, props: Property[]) {
  const words = label.toLowerCase().split(/\s+/);
  const names = (p: Property) => LANGS.map((x) => p.label[x]?.toLowerCase() ?? "").filter(Boolean);
  return props.find(
    (p) =>
      p.unit === unit && words.some((w) => w.length > 3 && names(p).some((n) => n.includes(w.slice(0, 5)))),
  )?.code;
}

export function infer(text: string, ctx: { properties: Property[]; objects?: ObjectHint[] }): Inferred {
  const about: string[] = [];
  const tags: string[] = [];
  let t = text.replace(/#([\p{L}\p{N}_-]+)/gu, (_, tag: string) => {
    tags.push(tag.toLowerCase());
    return "";
  });
  t = t.replace(/@([\p{L}\p{N}._-]+)/gu, (m, word: string) => {
    const w = word.toLowerCase();
    const hit = ctx.objects?.find(
      (o) => o.codes?.some((c) => c.toLowerCase() === w) || o.label.toLowerCase().startsWith(w),
    );
    if (!hit) return m;
    if (!about.includes(hit.ref)) about.push(hit.ref);
    return word;
  });
  const lines = t.split("\n").map((l) => l.replace(/[ \t]+/g, " ").trim());
  const label = (lines[0] ?? "").trim();
  const body = lines.slice(1).join("\n").trim();
  const base = { label, body, about, tags };

  if (label.endsWith("?")) return { kind: "question", ...base };
  if (DECISION.test(label)) return { kind: "decision", ...base };
  if (LESSON.test(label)) return { kind: "lesson", ...base };

  const units = unitTable(ctx.properties);
  const m = label.match(new RegExp(`^(.+?)(?::\\s*|\\s+)${NUM}\\s*(°\\s?[CС]|\\S+)\\s*$`, "u"));
  if (m) {
    const raw = (m[3] ?? "").replace(/\s/g, "").replace("С", "C").toLowerCase();
    const unit = units.get(raw) ?? (raw.startsWith("°") ? "Cel" : undefined);
    if (unit) {
      const qlabel = (m[1] ?? "").trim();
      return {
        kind: "parameter",
        ...base,
        quantity: {
          label: qlabel,
          amount: toNum(m[2] ?? "0"),
          unit,
          property: guessProperty(qlabel, unit, ctx.properties),
        },
      };
    }
  }
  return { kind: "note", ...base };
}
