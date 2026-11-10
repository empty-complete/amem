// Черновики записи в localStorage: только удобство одного браузера; хранилище может быть недоступно.
import type { Draft } from "./proposal";

const PREFIX = "amemo.draft:";

export const draftKey = (mode: "new" | "edit", id: string | null) => `${PREFIX}${mode}:${id ?? "none"}`;

export function loadDraft(key: string): Draft | null {
  try {
    const v = window.localStorage.getItem(key);
    return v ? (JSON.parse(v) as Draft) : null;
  } catch {
    return null;
  }
}

export function saveDraft(key: string, d: Draft) {
  try {
    window.localStorage.setItem(key, JSON.stringify(d));
  } catch {
    // хранилище недоступно — черновик живёт до закрытия окна
  }
}

export function dropDraft(key: string) {
  try {
    window.localStorage.removeItem(key);
  } catch {
    // хранилище недоступно
  }
}
