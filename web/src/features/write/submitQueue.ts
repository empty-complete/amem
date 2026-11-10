// Очередь записи с окном отмены (разд. 5.9): пакет уходит через 6 с, при уходе со страницы — сразу с keepalive.
// Обратимые действия (перенос в папку, apply) выполняются сразу, а «Отменить» делает обратное (revert): обновление
// страницы в окне отмены их не теряет, и тост «Перенесено» говорит правду.
import { useSyncExternalStore } from "react";
import { apiFetch } from "../../api/auth";
import { langHeaders } from "../../api/client";
import { ApiError, problemFromResponse } from "../../api/errors";
import type { components } from "../../api/schema";
import { skyBus } from "../sky/bus";
import type { Star } from "../sky/model";
import { type LinkProposal, type Proposal, withSummary } from "./proposal";

type Submitted = components["schemas"]["Submitted"];
type CheckIssue = components["schemas"]["CheckIssue"];

export const UNDO_MS = 6000;

export interface Pending {
  id: string;
  label: string;
  what: string;
  about: string[];
  kind: string;
  body: { proposals: Proposal[]; links: LinkProposal[] };
  /** Текст тоста целиком («Подтверждено», «Перенесено в «Архив»»); без него — «Записано: <what>». */
  toast?: string;
  /** Не запись, а действие (перенос в папку): выполняется после окна отмены вместо /submit. */
  run?: (keepalive: boolean) => Promise<void>;
  /** Обратимое действие: выполняется сразу; «Отменить» — revert. */
  apply?: () => Promise<void>;
  revert?: () => Promise<void>;
  /** Идущее apply: «Отменить» ждёт его, чтобы обратное действие не обогнало прямое. */
  applying?: Promise<boolean>;
  timer: ReturnType<typeof setTimeout> | null;
  onDone?: (r: Submitted) => void;
  onIssues?: (issues: CheckIssue[], message: string) => void;
}

let items: Pending[] = [];
const subs = new Set<() => void>();
const emit = () => {
  items = [...items];
  for (const s of subs) s();
};

const url = () => `${typeof location === "undefined" ? "http://localhost" : location.origin}/api/v1/submit`;

async function send(p: Pending, keepalive = false) {
  items = items.filter((x) => x.id !== p.id);
  emit();
  if (p.run) {
    try {
      await p.run(keepalive);
      p.onDone?.({} as Submitted);
    } catch (e) {
      const err = e instanceof ApiError ? e : null;
      p.onIssues?.([], err?.detail ?? err?.title ?? "Нет связи со службой amemo");
    }
    return;
  }
  try {
    const res = await apiFetch(url(), {
      method: "POST",
      headers: { "content-type": "application/json", ...langHeaders() },
      body: JSON.stringify(withSummary(p.body)),
      keepalive,
    });
    if (!res.ok) throw await problemFromResponse(res);
    const r = (await res.json()) as Submitted;
    p.onDone?.(r);
  } catch (e) {
    const err = e instanceof ApiError ? e : null;
    skyBus.retract(p.id);
    p.onIssues?.(err?.issues ?? [], err?.detail ?? err?.title ?? "Нет связи со службой amemo");
  }
}

/** Поставить пакет: тост «Записано · Отменить», вспышка звезды, отправка по истечении окна. */
export function enqueue(p: Omit<Pending, "id" | "timer">, star?: Omit<Star, "id">) {
  const id = `@new-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
  const item: Pending = { ...p, id, timer: null };
  if (item.apply) {
    item.applying = act(item, item.apply);
    item.timer = setTimeout(() => drop(item.id), UNDO_MS);
    items.push(item);
    emit();
    return id;
  }
  item.timer = setTimeout(() => send(item), UNDO_MS);
  items.push(item);
  if (star) {
    skyBus.emit({
      star: { ...star, id },
      links: p.about.map((a) => ({ source: id, target: a, rel: "about" })),
    });
  }
  emit();
  return id;
}

/** Обратимое действие: выполнить, по успеху — onDone; сбой — тост убрать и сказать словами. */
async function act(p: Pending, fn: () => Promise<void>): Promise<boolean> {
  try {
    await fn();
    p.onDone?.({} as Submitted);
    return true;
  } catch (e) {
    drop(p.id);
    const err = e instanceof ApiError ? e : null;
    p.onIssues?.([], err?.detail ?? err?.title ?? "Нет связи со службой amemo");
    return false;
  }
}

function drop(id: string) {
  const p = items.find((x) => x.id === id);
  if (p?.timer) clearTimeout(p.timer);
  items = items.filter((x) => x.id !== id);
  emit();
}

export function undo(id: string) {
  const p = items.find((x) => x.id === id);
  if (!p) return;
  drop(id);
  if (p.apply) {
    const revert = p.revert;
    // обратное — только после прямого и только если оно удалось
    if (revert) void p.applying?.then((ok) => ok && act(p, revert));
    return;
  }
  skyBus.retract(id);
}

/** Всё, что ждёт окна, — сейчас и с keepalive: уход со страницы не теряет записанное. */
export function flushAll() {
  // обратимые действия уже выполнены — отправлять нечего
  for (const p of items.filter((x) => !x.apply)) {
    if (p.timer) clearTimeout(p.timer);
    void send(p, true);
  }
}

if (typeof window !== "undefined") {
  window.addEventListener("pagehide", flushAll);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flushAll();
  });
}

const subscribe = (fn: () => void) => {
  subs.add(fn);
  return () => subs.delete(fn);
};

export function usePending() {
  return useSyncExternalStore(
    subscribe,
    () => items,
    () => items,
  );
}

/** Для тестов: очистить очередь без отправки. */
export function resetQueue() {
  for (const p of items) if (p.timer) clearTimeout(p.timer);
  items = [];
  emit();
}
