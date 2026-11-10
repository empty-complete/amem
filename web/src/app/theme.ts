export type Theme = "system" | "light" | "dark";
const KEY = "amemo.theme";
const dark = () => window.matchMedia("(prefers-color-scheme: dark)");

/** Выбор человека; без localStorage (приватное окно, запрет) — «как в системе». */
export function readTheme(): Theme {
  try {
    const t = window.localStorage.getItem(KEY);
    return t === "light" || t === "dark" ? t : "system";
  } catch {
    return "system";
  }
}

export function resolveTheme(t: Theme): "light" | "dark" {
  return t === "system" ? (dark().matches ? "dark" : "light") : t;
}

/** Ставит data-theme и класс на <html> (HeroUI читает оба) и запоминает выбор. */
export function applyTheme(t: Theme) {
  const root = document.documentElement;
  const r = resolveTheme(t);
  root.dataset.theme = r;
  root.classList.remove("light", "dark");
  root.classList.add(r);
  try {
    if (t === "system") window.localStorage.removeItem(KEY);
    else window.localStorage.setItem(KEY, t);
  } catch {
    // хранилище недоступно: выбор живёт до перезагрузки
  }
}

/** При «как в системе» следить за сменой темы ОС. */
export function watchSystemTheme(): () => void {
  const mq = dark();
  const on = () => {
    if (readTheme() === "system") applyTheme("system");
  };
  mq.addEventListener("change", on);
  return () => mq.removeEventListener("change", on);
}
