import type { Plugin, Widget } from "./plugin";
import { createRegistry } from "./registry";

const plugin: Plugin = {
  id: "test",
  widgets: [
    { id: "test.hello", title: { ru: "Привет", en: "Hello" }, slots: ["side"], component: () => null },
  ],
  commands: [{ id: "test.say", title: { ru: "Сказать", en: "Say" }, run: () => {} }],
  dataSources: [{ id: "test.data", kind: "records", search: async () => ({ items: [] }) }],
};

test("плагин регистрирует виджеты, команды и источники данных", () => {
  const r = createRegistry();
  r.register(plugin);
  expect(r.widgets.get("test.hello")?.slots).toContain("side");
  expect(r.commands.get("test.say")).toBeDefined();
  expect(r.dataSources.get("test.data")?.kind).toBe("records");
});

test("повторная регистрация того же плагина — ошибка", () => {
  const r = createRegistry();
  r.register(plugin);
  expect(() => r.register(plugin)).toThrow(/test/);
});

test("чужой виджет с занятым id не регистрирует плагин наполовину", () => {
  const r = createRegistry();
  r.register(plugin);
  const clash: Plugin = {
    id: "other",
    commands: [{ id: "other.x", title: { ru: "x", en: "x" }, run: () => {} }],
    widgets: plugin.widgets ? [{ ...plugin.widgets[0] } as Widget] : [],
  };
  expect(() => r.register(clash)).toThrow(/test.hello/);
  expect(r.commands.has("other.x")).toBe(false);
  expect(r.plugins.has("other")).toBe(false);
});

test("widgetsFor отдаёт виджеты слота в порядке регистрации", () => {
  const r = createRegistry();
  r.register(plugin);
  expect(r.widgetsFor("side").map((w) => w.id)).toEqual(["test.hello"]);
  expect(r.widgetsFor("main")).toEqual([]);
});
