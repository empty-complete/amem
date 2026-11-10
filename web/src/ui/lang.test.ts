import { editSlot, hasText, langOf, langString, order, pickText, slotOf, withText } from "./lang";

const BOTH = { ru: "Погрешность влажности", en: "Humidity accuracy" };

test("язык интерфейса → слот и порядок замены, как у службы", () => {
  expect([langOf("en-GB"), langOf("EN"), langOf("ru"), langOf("de"), langOf(undefined)]).toEqual([
    "en",
    "en",
    "ru",
    "ru",
    "ru",
  ]);
  expect(order("en")).toEqual(["en", "ru"]);
  expect(order()).toEqual(["ru", "en"]);
});

test("текст на языке интерфейса, иначе из другого слота; пустой слот — как отсутствие", () => {
  expect(pickText(BOTH, "en")).toBe("Humidity accuracy");
  expect(pickText(BOTH, "ru")).toBe("Погрешность влажности");
  expect(pickText({ en: "Mast" }, "ru")).toBe("Mast");
  expect(pickText({ ru: "  ", en: "Mast" }, "ru")).toBe("Mast");
  expect(pickText({ ru: "Мачта" }, "en")).toBe("Мачта");
  expect(pickText(null, "en")).toBe("");
  expect(pickText("строка", "en")).toBe("строка");
  expect(slotOf({ ru: "Мачта" }, "en")).toBe("ru");
  expect(hasText({ ru: "", en: " " })).toBe(false);
});

test("правка — в показанный слот, новое — в язык интерфейса, другие слоты остаются", () => {
  expect(withText({ ru: "Мачта" }, "Мачта 10 м", "en")).toEqual({ ru: "Мачта 10 м" });
  expect(withText(BOTH, "Sensor humidity accuracy", "en")).toEqual({
    ...BOTH,
    en: "Sensor humidity accuracy",
  });
  expect(withText({}, "M", "en")).toEqual({ en: "M" });
  // стёртый целиком слот остаётся слотом правки: набранное заново не уходит в другой язык
  expect(editSlot({ ru: "" }, "en")).toBe("ru");
  expect(withText(withText({ ru: "Мачта" }, "", "en"), "Опора", "en")).toEqual({ ru: "Опора" });
  expect(langString("Mast", "en-US")).toEqual({ en: "Mast" });
});
