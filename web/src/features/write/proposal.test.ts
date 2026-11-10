import recs from "../../mocks/fixtures/records-b.json";
import templates from "../../mocks/fixtures/templates.json";
import { emptyDraft, fromPayload, issuesToFields, type Template, toProposal, withSummary } from "./proposal";

const T = (code: string) => (templates as Template[]).find((t) => t.code === code);
const E3 = "ent:0193b7c2-5e1a-7d40-9f2e-000000000003";

test("заметка: заголовок, тело, о чём, слово автора", () => {
  const d = { ...emptyDraft("note"), label: "Проверить мачту", body: "после ветра", values: { about: [E3] } };
  const { proposal } = toProposal(d, T("note"));
  expect(proposal).toEqual({
    target: "atom",
    record_id: null,
    payload: {
      kind: "note",
      ref: "@n0",
      label: { ru: "Проверить мачту" },
      body: { ru: "после ветра" },
      about: [E3],
      basis: "author",
    },
  });
});

test("параметр: величина по пути content.values с единицей шаблона", () => {
  const d = {
    ...emptyDraft("sensor_reading"),
    label: "Влажность 87 %",
    values: { about: [E3], relative_humidity: { amount: 87 }, valid_from: "2026-11-07" },
  };
  const p = toProposal(d, T("sensor_reading")).proposal.payload;
  expect(p.content).toEqual({ values: [{ property: "relative_humidity", amount: 87, unit: "%" }] });
  expect(p.valid_from).toBe("2026-11-07");
  expect(p.body).toBeUndefined();
});

test("ревизия: record_id, своё свойство в qualifiers, неизвестные поля тела сохраняются", () => {
  const A3 = "atm:0193b7c2-5e1a-7d40-9f2e-00000000000b";
  const base = recs[A3 as keyof typeof recs].payload as Record<string, unknown>;
  const d = fromPayload(base, T("parameter"), "atom");
  expect(d.extra).toContainEqual({ property: "maturity", label: "Зрелость", value: "🌱 росток" });
  d.label = "Погрешность В-2: ±2 % (уточнено)";
  const { proposal, links } = toProposal(d, T("parameter"), {
    recordId: A3,
    base,
    resolve: (l) => (l === "Точка росы" ? "atm:14" : undefined),
  });
  expect(proposal.record_id).toBe(A3.slice(4));
  expect(proposal.payload.confidence).toBe(0.82);
  expect(proposal.payload.qualifiers).toContainEqual({
    property: "maturity",
    label: { ru: "Зрелость" },
    value_text: "🌱 росток",
  });
  expect(links).toEqual([{ src: A3, dst: "atm:14", rel: "see_also" }]);
});

test("замечания проверки — к полям формы, источникам и заголовку", () => {
  const r = issuesToFields(
    [
      { code: "required", severity: "violation", message: "Нужен заголовок", path: "label.ru" },
      { code: "required", severity: "violation", message: "Нужно: значение", path: "content.values" },
      { code: "quote_not_found", severity: "violation", message: "Цитаты нет", path: "sources[0].quote" },
      { code: "x", severity: "violation", message: "Прочее", path: "rank" },
    ],
    T("parameter"),
  );
  expect(r).toEqual({
    label: "Нужен заголовок",
    fields: { value: "Нужно: значение" },
    sources: { 0: "Цитаты нет" },
    other: ["Прочее"],
  });
});

test("пояснение «простыми словами» по умолчанию — заголовок, только у атома и только если его нет", () => {
  const atom = (pl: object) => ({
    target: "atom" as const,
    record_id: null,
    payload: { kind: "note", ...pl },
  });
  const out = withSummary({
    proposals: [
      atom({ label: { ru: "Проверить мачту" } }),
      atom({ label: { ru: "Своё" }, summary_plain: { ru: "своё пояснение" } }),
      {
        target: "entity" as const,
        record_id: null,
        payload: { entity_class: "artifact", label: { ru: "Мачта" } },
      },
    ],
    links: [],
  });
  expect(out.proposals.map((p) => (p.payload as { summary_plain?: unknown }).summary_plain)).toEqual([
    { ru: "Проверить мачту" },
    { ru: "своё пояснение" },
    undefined,
  ]);
});

test("форма ядра: значение параметра — в content.values с кодом величины, у сущности нет part_of в теле", () => {
  const par = { ...emptyDraft("parameter"), label: "Ток потребления МС-1: 0,4 А" };
  par.values = { value: { property: "supply_current", amount: 0.4, unit: "A" } };
  const p = toProposal(par, T("parameter")).proposal.payload as { content?: { values: unknown[] } };
  expect(p.content?.values).toEqual([{ property: "supply_current", amount: 0.4, unit: "A" }]);
  const ent = { ...emptyDraft("artifact", "entity"), label: "Мачта М-3", values: { codes: ["м-3"] } };
  const e = toProposal(ent, T("artifact")).proposal.payload;
  expect(e).not.toHaveProperty("part_of");
  expect(e.codes).toEqual(["м-3"]);
});
