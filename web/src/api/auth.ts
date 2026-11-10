// Вход в общую службу (AMEMO_TOKENS): API — только по `Authorization: Bearer`, cookie нет. Локальная служба входит
// по cookie сама — токена нет, заголовка нет. Токен по умолчанию живёт до закрытия вкладки (sessionStorage);
// «Запомнить на этом устройстве» — localStorage. Сам токен не попадает ни в адрес, ни в журналы.
import { useEffect, useState, useSyncExternalStore } from "react";

const KEY = "amemo.token";
let token: string | null = read();
let needed = false;
const subs = new Set<() => void>();
const emit = () => {
  for (const s of subs) s();
};

function read(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(KEY) ?? window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export const auth = {
  token: () => token,
  /** Сохранить токен: на вкладку или, с remember, на этом устройстве. Снимает «нужен вход». */
  set(value: string, remember: boolean) {
    token = value.trim() || null;
    needed = false;
    try {
      window.sessionStorage.removeItem(KEY);
      window.localStorage.removeItem(KEY);
      if (token) (remember ? window.localStorage : window.sessionStorage).setItem(KEY, token);
    } catch {
      // хранилище недоступно (приватное окно): токен живёт в памяти до перезагрузки
    }
    emit();
  },
  /** Выйти: стереть токен отовсюду. */
  clear() {
    auth.set("", false);
  },
  /** Служба ответила 401: показать вход. */
  require() {
    if (needed) return;
    needed = true;
    emit();
  },
  needed: () => needed,
  subscribe(fn: () => void) {
    subs.add(fn);
    return () => subs.delete(fn);
  },
};

/** Заголовки для запросов к API: с токеном — Authorization, без него — ничего (локальная служба, cookie). */
export function authHeaders(): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** fetch к API с токеном (если он есть); ответ 401 — показать вход. Для запросов мимо openapi-fetch: keepalive,
 * multipart, решения очереди. */
export async function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const res = await globalThis.fetch(input, {
    ...init,
    headers: { ...(init.headers as Record<string, string> | undefined), ...authHeaders() },
    credentials: "same-origin",
  });
  if (res.status === 401) auth.require();
  return res;
}

export const useAuthNeeded = () => useSyncExternalStore(auth.subscribe, auth.needed, auth.needed);
export const useAuthToken = () => useSyncExternalStore(auth.subscribe, auth.token, auth.token);

/** Адрес файла API для <img>: без токена — как есть; с токеном — blob-адрес по запросу с заголовком. */
export function useAuthedSrc(url: string | null | undefined): string | undefined {
  const tok = useAuthToken();
  const [src, setSrc] = useState<string | undefined>(tok ? undefined : (url ?? undefined));
  useEffect(() => {
    if (!url) return setSrc(undefined);
    if (!tok) return setSrc(url);
    let live = true;
    let made: string | null = null;
    globalThis
      .fetch(url, { headers: authHeaders(), credentials: "same-origin" })
      .then((r) => (r.ok ? r.blob() : Promise.reject(r)))
      .then((b) => {
        made = URL.createObjectURL(b);
        if (live) setSrc(made);
      })
      .catch(() => live && setSrc(undefined));
    return () => {
      live = false;
      if (made) URL.revokeObjectURL(made);
    };
  }, [url, tok]);
  return src;
}

// во вкладке открываем только то, что браузер показывает сам и не исполняет; HTML и прочее — файлом: blob-адрес
// живёт в нашем источнике и потерял бы CSP sandbox, с которой служба отдаёт файлы базы
const SHOWN = /^(application\/pdf|image\/(png|jpeg|gif|webp|avif)|text\/plain)\b/;

/** Открыть или скачать файл API с токеном (обычная ссылка заголовок не несёт). Без токена — false: пусть сработает ссылка. */
export async function openAuthed(url: string, opts: { download?: boolean } = {}): Promise<boolean> {
  if (!token) return false;
  const r = await globalThis.fetch(url, { headers: authHeaders(), credentials: "same-origin" });
  if (r.status === 401) {
    auth.require();
    return true;
  }
  if (!r.ok) return true;
  const blob = await r.blob();
  const href = URL.createObjectURL(blob);
  const type = (r.headers.get("content-type") ?? blob.type).split(";")[0]?.trim() ?? "";
  if (!opts.download && SHOWN.test(type)) window.open(href, "_blank", "noopener");
  else {
    const a = document.createElement("a");
    a.href = href;
    a.download = nameFrom(r.headers.get("content-disposition")) ?? "amemo-file";
    a.click();
  }
  setTimeout(() => URL.revokeObjectURL(href), 60_000);
  return true;
}

/** Имя файла из Content-Disposition: filename* (UTF-8) важнее простого filename. */
export function nameFrom(cd: string | null): string | undefined {
  if (!cd) return undefined;
  const star = cd.match(/filename\*=UTF-8''([^;]+)/i);
  if (star?.[1]) return decodeURIComponent(star[1]);
  return cd.match(/filename="?([^";]+)"?/i)?.[1];
}
