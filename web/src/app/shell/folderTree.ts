// Состояние дерева папок на этом устройстве: какие разделы раскрыты и сколько уровней вложенности разрешено.
import { useSyncExternalStore } from "react";

const OPEN = "amemo.folders.open";
const NEW_IN = "amemo.folders.new";
const DEPTH = "amemo.folders.depth";
/** По умолчанию — один уровень: папку внутри папки не создают (уже созданные показываются как есть). */
export const DEPTH_DEFAULT = 1;

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
    // нет хранилища — состояние просто не запомнится
  }
};

let open = new Set<string>(read<string[]>(OPEN, []));
let depth = read<number>(DEPTH, DEPTH_DEFAULT);
let newIn = read<string>(NEW_IN, "");
const subs = new Set<() => void>();
const emit = () => {
  for (const f of subs) f();
};
const subscribe = (f: () => void) => {
  subs.add(f);
  return () => subs.delete(f);
};

/** Раскрыт ли раздел дерева; key — путь папки, «*» — все записи, «-» — без папки. */
export function useOpen(key: string): [boolean, () => void] {
  const isOpen = useSyncExternalStore(subscribe, () => open.has(key));
  return [
    isOpen,
    () => {
      open = new Set(open);
      if (open.has(key)) open.delete(key);
      else open.add(key);
      write(OPEN, [...open]);
      emit();
    },
  ];
}

export function useFolderDepth(): [number, (n: number) => void] {
  const n = useSyncExternalStore(subscribe, () => depth);
  return [
    n,
    (v: number) => {
      depth = Math.max(1, Math.min(9, Math.round(v)));
      write(DEPTH, depth);
      emit();
    },
  ];
}

/** Куда класть новые записи этого интерфейса, как в Obsidian: «» — корень (без папки), иначе путь папки. */
export const newNoteFolder = () => newIn;

export function setNewNoteFolder(path: string) {
  newIn = path;
  write(NEW_IN, path);
  emit();
}

export function useNewNoteFolder(): [string, (path: string) => void] {
  return [useSyncExternalStore(subscribe, () => newIn), setNewNoteFolder];
}

/** Свернуть все разделы дерева (Shift+C). */
export function collapseAll() {
  open = new Set();
  write(OPEN, []);
  emit();
}

// выбор заметок в дереве: щелчок — одна, Ctrl/⌘ — добавить или снять, Shift — диапазон по порядку в панели
let picked = new Set<string>();
let anchor: string | null = null;
const pickSubs = new Set<() => void>();
const pickEmit = () => {
  for (const f of pickSubs) f();
};
const pickSub = (f: () => void) => {
  pickSubs.add(f);
  return () => pickSubs.delete(f);
};

export const treePick = {
  get: () => picked,
  set(refs: string[], last: string | null = refs[refs.length - 1] ?? null) {
    picked = new Set(refs);
    anchor = last;
    pickEmit();
  },
  toggle(ref: string) {
    picked = new Set(picked);
    if (picked.has(ref)) picked.delete(ref);
    else picked.add(ref);
    anchor = ref;
    pickEmit();
  },
  /** Диапазон от прошлой выбранной до ref — по порядку строк в панели (order — ссылки сверху вниз). */
  range(ref: string, order: string[]) {
    const a = anchor ? order.indexOf(anchor) : -1;
    const b = order.indexOf(ref);
    if (a < 0 || b < 0) return treePick.set([ref]);
    const [lo, hi] = a < b ? [a, b] : [b, a];
    picked = new Set([...picked, ...order.slice(lo, hi + 1)]);
    pickEmit();
  },
  clear() {
    if (!picked.size) return;
    picked = new Set();
    anchor = null;
    pickEmit();
  },
};

export const useTreePick = () => useSyncExternalStore(pickSub, () => picked);
