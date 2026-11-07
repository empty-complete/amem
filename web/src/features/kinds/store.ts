import { useSyncExternalStore } from "react";

let open = false;
let edit: string | null = null;
const subs = new Set<() => void>();
const emit = () => {
  for (const s of subs) s();
};

/** Конструктор видов открывается из любого места: «Настроить виды» в списке видов и «Настройки → Мои виды». */
export const kindsStore = {
  open(code: string | null = null) {
    open = true;
    edit = code;
    emit();
  },
  close() {
    open = false;
    emit();
  },
};
const sub = (f: () => void) => {
  subs.add(f);
  return () => subs.delete(f);
};
export const useKindsOpen = () =>
  useSyncExternalStore(
    sub,
    () => open,
    () => open,
  );
export const useKindsEdit = () =>
  useSyncExternalStore(
    sub,
    () => edit,
    () => edit,
  );
