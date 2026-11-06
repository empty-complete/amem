import { groupByDay } from "./group";

test("события по дням: Сегодня, Вчера, дата; новые сверху", () => {
  const now = new Date(2026, 10, 7, 15, 0);
  const at = (d: number, h: number) => new Date(2026, 10, d, h, 0).toISOString();
  const g = groupByDay(
    [{ at: at(4, 8) }, { at: at(7, 9) }, { at: at(6, 20) }, { at: at(7, 11) }] as never,
    now,
    "ru",
  );
  expect(g.map((x) => x.title)).toEqual(["Сегодня", "Вчера", "4 ноября"]);
  expect(g[0]?.events.map((e) => e.at)).toEqual([at(7, 11), at(7, 9)]);
});

test("другой год — с годом", () => {
  const g = groupByDay([{ at: new Date(2025, 0, 3).toISOString() }] as never, new Date(2026, 10, 7), "ru");
  expect(g[0]?.title).toBe("3 января 2025 г.");
});
