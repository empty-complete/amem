import { searchParams } from "../features/search/params";
import { parseSearch, stringifySearch } from "./search-url";

test("массивы — повтором ключа, умолчания и пустое не пишутся", () => {
  expect(stringifySearch({ q: "погрешность", kind: ["lesson", "fact"], status: [], limit: 10 })).toBe(
    "?q=%D0%BF%D0%BE%D0%B3%D1%80%D0%B5%D1%88%D0%BD%D0%BE%D1%81%D1%82%D1%8C&kind=lesson&kind=fact",
  );
  expect(stringifySearch({})).toBe("");
});

test("туда и обратно через схему параметров поиска", () => {
  const s = stringifySearch({ q: "x", kind: ["lesson"], status: [], limit: 30 });
  expect(searchParams.parse(parseSearch(s))).toEqual({ q: "x", kind: ["lesson"], status: [], limit: 30 });
});
