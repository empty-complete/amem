import props from "../../mocks/fixtures/vocab-property.json";
import { infer } from "./infer";

const ctx = { properties: props as never };
const cases: [string, Record<string, unknown>][] = [
  ["Нужен ли обогрев В-2 зимой?", { kind: "question", label: "Нужен ли обогрев В-2 зимой?" }],
  ["Решили ставить мачту на 2 м", { kind: "decision" }],
  ["Принято: опрос раз в минуту", { kind: "decision" }],
  ["Оказалось, иней искажает показания", { kind: "lesson" }],
  ["Урок: проверять отвес после ветра", { kind: "lesson" }],
  [
    "Влажность в будке: 87 %",
    {
      kind: "parameter",
      quantity: { label: "Влажность в будке", amount: 87, unit: "%", property: "relative_humidity" },
    },
  ],
  [
    "Температура −3,5 °C",
    {
      kind: "parameter",
      quantity: { label: "Температура", amount: -3.5, unit: "Cel", property: "air_temperature" },
    },
  ],
  ["Давление 1012 гПа", { kind: "parameter", quantity: { amount: 1012, unit: "hPa" } }],
  [
    "Проверить крепление мачты\nхомуты верхний и средний",
    { kind: "note", label: "Проверить крепление мачты", body: "хомуты верхний и средний" },
  ],
  ["Купить 2 хомута", { kind: "note" }],
];

test.each(cases)("%s", (text, want) => {
  expect(infer(text, ctx)).toMatchObject(want);
});

test("@объект и #тег вынимаются из текста, но текст не портится", () => {
  const r = infer("Обогрев @В-2 нужен с ноября #зима", {
    properties: [],
    objects: [{ ref: "ent:3", label: "Датчик влажности В-2", codes: ["В-2"] }],
  });
  expect(r.about).toEqual(["ent:3"]);
  expect(r.tags).toEqual(["зима"]);
  expect(r.label).toBe("Обогрев В-2 нужен с ноября");
});

test("неизвестный @ остаётся как есть", () => {
  expect(infer("Спросить @Петра", ctx).label).toBe("Спросить @Петра");
});
