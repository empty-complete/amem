import base from "../../mocks/fixtures/graph-base.json";
import { arrowNeighbour, buildSky, dimmed, labelOrder, placeLabels, visibleLabels } from "./model";

const E3 = "ent:0193b7c2-5e1a-7d40-9f2e-000000000003";
const A3 = "atm:0193b7c2-5e1a-7d40-9f2e-00000000000b";
const sky = () => buildSky(base as never);
const overlap = (a: { x: number; y: number; w: number; h: number }, b: typeof a) =>
  a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

test("звёзды: объекты крупнее и растут со степенью, атомы — точки; ждущие помечены", () => {
  const s = sky();
  const e3 = s.byId.get(E3);
  const a3 = s.byId.get(A3);
  expect(e3?.object).toBe(true);
  expect(e3?.r).toBeGreaterThan(a3?.r ?? 99);
  expect(a3?.pending).toBe(true);
  expect(s.neighbours.get(A3)?.has(E3)).toBe(true);
  expect(s.total).toBe(31);
});

test("фильтр приглушает, а не убирает", () => {
  const s = sky();
  const d = dimmed(s, { families: new Set(["object"]), pendingOnly: false });
  expect(d.has(A3)).toBe(true);
  expect(d.has(E3)).toBe(false);
  expect(s.nodes).toHaveLength(31);
  const p = dimmed(s, { families: new Set(), pendingOnly: true });
  expect(p.has(A3)).toBe(false);
  expect(p.has(E3)).toBe(true);
});

test("подписи: у объектов всегда, у атомов — у выбранного и его соседей", () => {
  const s = sky();
  expect(visibleLabels(s, null).has(A3)).toBe(false);
  expect(visibleLabels(s, null).has(E3)).toBe(true);
  expect(visibleLabels(s, A3).has(A3)).toBe(true);
  expect(labelOrder(s, A3, visibleLabels(s, A3))[0]?.id).toBe(A3);
});

test("раскладка подписей: справа, слева, под, над — без наложений, иначе прячет", () => {
  const stars = [
    { id: "a", x: 0, y: 0, r: 4, w: 60, h: 14 },
    { id: "b", x: 20, y: 0, r: 4, w: 60, h: 14 },
    { id: "c", x: 10, y: 2, r: 4, w: 60, h: 14 },
    { id: "d", x: 500, y: 500, r: 4, w: 60, h: 14 },
  ];
  const placed = placeLabels(stars, 2);
  const boxes = [...placed.values()].filter((b) => b !== null);
  for (const p of boxes) for (const q of boxes) if (p !== q) expect(overlap(p, q)).toBe(false);
  expect(placed.get("a")).not.toBeNull();
  expect(placed.get("d")?.side).toBe("right");
  expect(boxes.length).toBeGreaterThanOrEqual(2);
});

test("стрелки: ближайший сосед в направлении нажатия", () => {
  const pos = new Map([
    ["c", { x: 0, y: 0 }],
    ["r", { x: 10, y: 1 }],
    ["l", { x: -10, y: 0 }],
    ["u", { x: 0, y: -10 }],
  ]);
  const nb = new Set(["r", "l", "u"]);
  expect(arrowNeighbour("c", nb, pos, "ArrowRight")).toBe("r");
  expect(arrowNeighbour("c", nb, pos, "ArrowUp")).toBe("u");
  expect(arrowNeighbour("c", nb, pos, "ArrowDown")).toBeNull();
  expect(arrowNeighbour("c", new Set(), pos, "ArrowUp")).toBeNull();
});
