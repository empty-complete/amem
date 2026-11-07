import { slug } from "./slug";

test("транслит кода вида", () => {
  expect(slug("Обход площадки")).toBe("obkhod_ploshchadki");
  expect(slug("Журнал: щит №2")).toBe("zhurnal_shchit_2");
  expect(slug("2-й обход")).toBe("kind_2_j_obkhod");
});
