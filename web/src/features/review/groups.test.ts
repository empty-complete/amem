import { arrange, facets, filterItems, groupKey, type Item, nextAfter } from "./groups";

const names = { none: "Без источника", entities: "Сущности" };
const item = (n: number, doc: string | null, about: string[] = [], ref = `atm:${n}`): Item =>
  ({
    id: `i${n}`,
    ref,
    reason: "semantic",
    state: "queued",
    created_at: `2026-11-09T10:${String(n % 60).padStart(2, "0")}:00Z`,
    source: doc ? { object: `o-${doc}`, object_name: `${doc}.pdf` } : null,
    about: about.map((a) => ({ ref: a, label: a })),
  }) as Item;

// очередь в сотни пунктов: три документа, без источника и сущности
const big = [
  ...Array.from({ length: 70 }, (_, n) => item(n, "СП", ["ent:a"])),
  ...Array.from({ length: 40 }, (_, n) => item(100 + n, "ГОСТ", ["ent:b"])),
  ...Array.from({ length: 10 }, (_, n) => item(200 + n, null)),
  item(300, null, [], "ent:x"),
];

test("по документам: больше пунктов — выше, «Сущности» и «Без источника» последними", () => {
  const { rows, ordered } = arrange(big, "source", names);
  const heads = rows
    .filter((r) => r.kind === "head")
    .map((r) => (r.kind === "head" ? [r.name, r.count] : []));
  expect(heads).toEqual([
    ["СП.pdf", 70],
    ["ГОСТ.pdf", 40],
    ["Сущности", 1],
    ["Без источника", 10],
  ]);
  expect(ordered).toHaveLength(big.length);
  expect(groupKey(ordered[0] as Item)).toBe("o-СП");
});

test("по времени — как пришло, без заголовков", () => {
  const { rows } = arrange(big, "time", names);
  expect(rows.every((r) => r.kind === "item")).toBe(true);
});

test("следующий после решения — в той же группе, у последнего в группе — предыдущий в ней же", () => {
  const { ordered } = arrange(big, "source", names);
  const sp = ordered.filter((i) => groupKey(i) === "o-СП");
  expect(nextAfter(ordered, sp[0] as Item, "source")).toBe(sp[1]);
  expect(nextAfter(ordered, sp.at(-1) as Item, "source")).toBe(sp.at(-2));
  expect(nextAfter(ordered, ordered[0] as Item, "time")).toBe(ordered[1]);
});

test("фильтры документа и объекта; счётчики для выбора", () => {
  expect(filterItems(big, { object: "o-ГОСТ" })).toHaveLength(40);
  expect(filterItems(big, { about: "ent:a" })).toHaveLength(70);
  expect(filterItems(big, { about: "ent:x" })).toHaveLength(1);
  const f = facets(big, names);
  expect(f.docs.map((d) => [d.name, d.count])).toEqual([
    ["СП.pdf", 70],
    ["ГОСТ.pdf", 40],
    ["Без источника", 10],
    ["Сущности", 1],
  ]);
  expect(f.about[0]).toMatchObject({ key: "ent:a", count: 70 });
});
