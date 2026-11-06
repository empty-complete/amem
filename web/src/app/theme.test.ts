import { applyTheme, readTheme } from "./theme";

test("тема пишется в data-theme и класс html", () => {
  applyTheme("dark");
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(document.documentElement.classList.contains("dark")).toBe(true);
  expect(readTheme()).toBe("dark");
});

test("«как в системе» разрешается по prefers-color-scheme и не хранится", () => {
  applyTheme("system");
  expect(document.documentElement.dataset.theme).toBe("light");
  expect(readTheme()).toBe("system");
});

test("без localStorage тема — «как в системе», запись не падает", () => {
  const spy = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  expect(readTheme()).toBe("system");
  expect(() => applyTheme("dark")).not.toThrow();
  spy.mockRestore();
  set.mockRestore();
});
