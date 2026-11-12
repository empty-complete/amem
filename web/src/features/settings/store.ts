// Окно настроек (как в Obsidian) и плагины ядра, которые можно выключить: состояние на этом устройстве.
import { useSyncExternalStore } from "react";

const subs = new Set<() => void>();
const emit = () => {
  for (const f of subs) f();
};
const subscribe = (f: () => void) => {
  subs.add(f);
  return () => subs.delete(f);
};

let open: string | null = null;

/** Открыть окно настроек на разделе (по умолчанию — «Общие»); null — закрыть. */
export const settingsWindow = {
  open(section = "general") {
    open = section;
    emit();
  },
  close() {
    open = null;
    emit();
  },
};

export const useSettingsWindow = () => useSyncExternalStore(subscribe, () => open);

/** Плагины ядра — части экрана, которые выключаются в настройках; граф («небо») — тоже плагин. */
export const CORE_PLUGINS = ["sky.home", "sky.record", "sky.entity"] as const;
export type CorePlugin = (typeof CORE_PLUGINS)[number];

const KEY = "amemo.core.off";
const readOff = (): Set<string> => {
  try {
    const v = JSON.parse(window.localStorage.getItem(KEY) ?? "[]");
    return new Set(Array.isArray(v) ? v.map(String) : []);
  } catch {
    return new Set();
  }
};
let off = readOff();

export function setCorePlugin(id: CorePlugin, on: boolean) {
  off = new Set(off);
  if (on) off.delete(id);
  else off.add(id);
  try {
    window.localStorage.setItem(KEY, JSON.stringify([...off]));
  } catch {
    // без хранилища выбор живёт до перезагрузки
  }
  emit();
}

/** Включён ли плагин ядра (по умолчанию — да). */
export const useCorePlugin = (id: CorePlugin) => useSyncExternalStore(subscribe, () => !off.has(id));
