import { searchParams } from "./params";

test("параметры поиска валидны и переживают ссылку", () => {
  expect(
    searchParams.parse({ q: "погрешность", kind: ["parameter"], status: "verified", limit: "10" }),
  ).toEqual({
    q: "погрешность",
    kind: ["parameter"],
    status: ["verified"],
    limit: 10,
  });
  expect(searchParams.parse({ q: "x", limit: "999" }).limit).toBe(100);
  expect(searchParams.parse({})).toEqual({ q: "", kind: [], status: [], limit: 10 });
});
