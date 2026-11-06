import en from "./en.json";
import ru from "./ru.json";

const flat = (o: object, p = ""): string[] =>
  Object.entries(o).flatMap(([k, v]) => (typeof v === "object" && v ? flat(v, `${p}${k}.`) : [`${p}${k}`]));

test("ru и en имеют одинаковые ключи", () => {
  expect(flat(en).sort()).toEqual(flat(ru).sort());
});
