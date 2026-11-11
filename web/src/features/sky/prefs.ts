// Настройки неба на этом устройстве: предел длины подписи и последний выбор фильтров главной.
import { useSyncExternalStore } from "react";

const LABEL = "amemo.sky.label";
const SCOPE = "amemo.sky.scope";
/** Подпись звезды на небе — не длиннее стольких знаков; полное название — в карточке звезды. */
export const LABEL_DEFAULT = 32;
export const LABEL_CHOICES = [24, 32, 48] as const;

/** Фильтры неба на главной: теги (все сразу), вид или класс, папка. */
export type SkyScope = { tag?: string[]; kind?: string; folder?: string };

const read = <T>(key: string, fallback: T): T => {
  try {
    const v = window.localStorage.getItem(key);
    return v == null ? fallback : (JSON.parse(v) as T);
  } catch {
    return fallback;
  }
};
const write = (key: string, v: unknown) => {
  try {
    window.localStorage.setItem(key, JSON.stringify(v));
  } catch {
    // нет хранилища — просто не запомнится
  }
};

let label = read<number>(LABEL, LABEL_DEFAULT);
const subs = new Set<() => void>();
const subscribe = (f: () => void) => {
  subs.add(f);
  return () => subs.delete(f);
};

export function useLabelMax(): [number, (n: number) => void] {
  const n = useSyncExternalStore(subscribe, () => label);
  return [
    n,
    (v) => {
      label = Math.max(12, Math.min(120, Math.round(v)));
      write(LABEL, label);
      for (const f of subs) f();
    },
  ];
}

/** Подпись в пределах max знаков: длиннее — обрезана по слову, с многоточием. */
export function clip(text: string, max: number) {
  if (text.length <= max) return text;
  const cut = text.slice(0, max - 1);
  const space = cut.lastIndexOf(" ");
  return `${(space > max * 0.6 ? cut.slice(0, space) : cut).trimEnd()}…`;
}

export const savedScope = () => read<SkyScope>(SCOPE, {});
export const saveScope = (s: SkyScope) => write(SCOPE, s);
export const hasScope = (s: SkyScope) => !!(s.tag?.length || s.kind || s.folder);
