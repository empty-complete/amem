import { clip } from "./prefs";

test("подпись в пределах: короткая — как есть, длинная — по слову и с многоточием", () => {
  expect(clip("Датчик ветра", 32)).toBe("Датчик ветра");
  const long = "Диапазон температуры Т-1 по паспорту 2019 года: −30…+50 °C";
  const cut = clip(long, 32);
  expect(cut.length).toBeLessThanOrEqual(32);
  expect(cut.endsWith("…")).toBe(true);
  expect(long.startsWith(cut.slice(0, -1))).toBe(true);
  expect(clip("Одно_очень_длинное_слово_без_пробелов_совсем", 12)).toBe("Одно_очень_…");
});
