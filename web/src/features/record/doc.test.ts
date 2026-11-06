import recs from "../../mocks/fixtures/records-b.json";
import { type AtomPayload, documentToRecord, recordToDocument } from "./doc";

const A3 = "atm:0193b7c2-5e1a-7d40-9f2e-00000000000b";
const rec = recs[A3 as keyof typeof recs];
const p = rec.payload as unknown as AtomPayload;
const doc = () => recordToDocument(p, rec.about, rec.sources as never);

test("запись → документ: шапка YAML и тело Markdown по правилам разд. 5.4", () => {
  const d = doc();
  expect(d.startsWith("---\nkind: parameter\n")).toBe(true);
  expect(d).toContain("about: [[Датчик влажности В-2]]\n");
  expect(d).toContain("page: \"12\"");
  expect(d).toContain("maturity: 🌱 росток");
  expect(d).toContain("\n---\n# Погрешность влажности В-2: ±2 %\n");
  expect(d).toContain("\n## Цитата\n> Погрешность ±2 % в диапазоне от 10 до 90 %\n");
});

test("документ → запись: заголовок, первый абзац, цитата, свои ключи, ссылки", () => {
  const r = documentToRecord(doc());
  expect(r.kind).toBe("parameter");
  expect(r.label).toBe("Погрешность влажности В-2: ±2 %");
  expect(r.summary_plain).toBe(p.summary_plain?.ru);
  expect(r.quote).toBe("Погрешность ±2 % в диапазоне от 10 до 90 %");
  expect(r.about).toEqual(["Датчик влажности В-2"]);
  expect(r.page).toBe("12");
  expect(r.tags).toEqual(["метрология", "зима"]);
  expect(r.qualifiers).toEqual({ maturity: "🌱 росток" });
  expect(r.body.startsWith("## Суть источника")).toBe(true);
  expect(r.links).toContainEqual({ rel: "see_also", label: "Нужен ли обогрев В-2 зимой?" });
});

test("туда и обратно — то же содержание", () => {
  const once = documentToRecord(doc());
  const back: AtomPayload = {
    kind: once.kind,
    label: { ru: once.label },
    summary_plain: { ru: once.summary_plain },
    body: { ru: once.body },
    tags: once.tags,
    qualifiers: Object.entries(once.qualifiers).map(([property, value_text]) => ({ property, value_text })),
  };
  const twice = documentToRecord(recordToDocument(back, rec.about, rec.sources as never));
  expect(twice).toEqual(once);
});

test("документ без шапки — заметка с заголовком", () => {
  const r = documentToRecord("# Мысль\n\nкороткая");
  expect(r).toMatchObject({ kind: "note", label: "Мысль", summary_plain: "короткая", body: "" });
});
