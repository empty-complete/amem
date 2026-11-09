import { familyFrom } from "./families";

const kinds = [
  { code: "fact", family: "source" as const },
  { code: "note", family: "work" as const },
  { code: "norm", family: "source" as const },
  { code: "lesson" },
];

test("семья — из словаря: вид пакета области, вид без family, класс сущности из пакета", () => {
  expect(familyFrom(kinds, "norm", "atom")).toBe("source");
  expect(familyFrom(kinds, "note")).toBe("work");
  expect(familyFrom(kinds, "lesson", "atom")).toBe("work");
  expect(familyFrom(kinds, "standard")).toBe("object");
  expect(familyFrom(kinds, "fact", "entity")).toBe("object");
  expect(familyFrom(kinds, "unknown_kind", "atom")).toBe("work");
});

test("словаря ещё нет — запасной список", () => {
  expect(familyFrom(undefined, "fact")).toBe("source");
  expect(familyFrom(undefined, "artifact")).toBe("object");
});
