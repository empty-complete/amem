import type { Command, DataSource, Plugin, Slot, Widget } from "./plugin";

export function createRegistry() {
  const plugins = new Map<string, Plugin>();
  const widgets = new Map<string, Widget>();
  const commands = new Map<string, Command>();
  const dataSources = new Map<string, DataSource>();

  function check<T extends { id: string }>(map: Map<string, T>, items: T[] | undefined, owner: string) {
    for (const it of items ?? []) {
      if (map.has(it.id)) throw new Error(`плагин ${owner}: id ${it.id} уже зарегистрирован`);
    }
  }

  return {
    plugins,
    widgets,
    commands,
    dataSources,
    register(p: Plugin) {
      if (plugins.has(p.id)) throw new Error(`плагин ${p.id} уже зарегистрирован`);
      check(widgets, p.widgets, p.id);
      check(commands, p.commands, p.id);
      check(dataSources, p.dataSources, p.id);
      for (const w of p.widgets ?? []) widgets.set(w.id, w);
      for (const c of p.commands ?? []) commands.set(c.id, c);
      for (const d of p.dataSources ?? []) dataSources.set(d.id, d);
      plugins.set(p.id, p);
    },
    widgetsFor(slot: Slot): Widget[] {
      return [...widgets.values()].filter((w) => w.slots.includes(slot));
    },
  };
}

export type Registry = ReturnType<typeof createRegistry>;
