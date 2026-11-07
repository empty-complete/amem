// Место записи (разд. 5.9): о чём будет новая запись — выбранная звезда, объект страницы или то, о чём открытая запись.
import { useRouterState } from "@tanstack/react-router";
import { useSyncExternalStore } from "react";

let star: { ref: string; label: string } | null = null;
let quickOpen = false;
const subs = new Set<() => void>();
const emit = () => {
  for (const s of subs) s();
};
const sub = (fn: () => void) => {
  subs.add(fn);
  return () => subs.delete(fn);
};

export const placeStore = {
  setStar(s: { ref: string; label: string } | null) {
    star = s;
    emit();
  },
  openQuick(open = true) {
    quickOpen = open;
    emit();
  },
};

export const useQuickOpen = () =>
  useSyncExternalStore(
    sub,
    () => quickOpen,
    () => quickOpen,
  );
const useStar = () =>
  useSyncExternalStore(
    sub,
    () => star,
    () => star,
  );

/** ref, о котором писать по умолчанию: звезда → объект страницы → «о чём» открытой записи (её ref; подпись — в окне). */
export function useWritePlace(): { ref: string | null; label: string | null } {
  const s = useStar();
  const path = useRouterState({ select: (st) => decodeURIComponent(st.location.pathname) });
  if (s) return s;
  const ent = path.match(/^\/entity\/(ent:[^/]+)/);
  if (ent) return { ref: ent[1] ?? null, label: null };
  const atom = path.match(/^\/atom\/(atm:[^/]+)/);
  if (atom) return { ref: atom[1] ?? null, label: null };
  return { ref: null, label: null };
}
