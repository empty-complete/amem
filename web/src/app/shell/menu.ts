import { useSyncExternalStore } from "react";

/** Меню на телефоне: папки и разделы прячутся за кнопкой, чтобы первый экран занимала запись. */
let open = false;
const subs = new Set<() => void>();

export const menuStore = {
  set(v: boolean) {
    if (open === v) return;
    open = v;
    for (const s of subs) s();
  },
  get: () => open,
  subscribe(fn: () => void) {
    subs.add(fn);
    return () => subs.delete(fn);
  },
};

export const useMenuOpen = () => useSyncExternalStore(menuStore.subscribe, menuStore.get, menuStore.get);
