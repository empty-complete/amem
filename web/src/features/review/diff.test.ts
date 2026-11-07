import { fieldDiff, wordDiff } from "./diff";

test("пословно: из частей собираются обе версии, добавленное помечено", () => {
  const a = "Хомуты верхний и средний.";
  const b = "Хомуты верхний, средний и нижний.";
  const d = wordDiff(a, b);
  expect(
    d
      .filter((p) => p.op !== "add")
      .map((p) => p.text)
      .join(""),
  ).toBe(a);
  expect(
    d
      .filter((p) => p.op !== "del")
      .map((p) => p.text)
      .join(""),
  ).toBe(b);
  expect(
    d
      .filter((p) => p.op === "add")
      .map((p) => p.text.trim())
      .join(" "),
  ).toContain("нижний");
  expect(d[0]).toEqual({ text: "Хомуты верхний", op: "same" });
});

test("по полям: только изменённые, заголовок раньше тела", () => {
  const r = fieldDiff(
    { label: { ru: "Проверить мачту" }, body: { ru: "раз" }, tags: ["зима"] },
    { label: { ru: "Проверить мачту после ветра" }, body: { ru: "раз" }, tags: ["зима"], ref: "@n0" },
  );
  expect(r.map((x) => x.field)).toEqual(["label"]);
  expect(r[0]?.pieces.at(-1)).toEqual({ text: " после ветра", op: "add" });
});
