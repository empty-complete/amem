// Обновления amemo (спецификация обновлений, разд. 3–4): статус службы, переключатель, проверка и установка.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";
import { api, data } from "../../api/client";
import { ApiError } from "../../api/errors";
import { q } from "../../api/queries";
import type { components } from "../../api/schema";

export type UpdateStatus = components["schemas"]["UpdateStatus"];

/** Сама служба ставит только из pipx, uv и pip; Docker и исходники обновляет человек. */
export const canInstall = (s: UpdateStatus) =>
  s.install === "pipx" || s.install === "uv" || s.install === "pip";

/** Как часто спрашивать: пока что-то идёт — часто, ждём перезапуска — раз в 5 с, иначе раз в 10 минут. */
export function pollEvery(s: UpdateStatus | undefined): number {
  if (!s) return 10 * 60_000;
  if (s.state === "checking" || s.state === "installing") return 2_000;
  if (s.state === "ready" || s.state === "restarting") return 5_000;
  return 10 * 60_000;
}

// версия, с которой открыта страница: первая увиденная. Сменилась — служба перезапустилась на новой.
let opened: string | null = null;
const subs = new Set<() => void>();
export function noteVersion(v: string) {
  if (opened === null) {
    opened = v;
    for (const s of subs) s();
  }
}
export const resetOpened = () => {
  opened = null;
};
export const useOpenedVersion = () =>
  useSyncExternalStore(
    (fn) => {
      subs.add(fn);
      return () => subs.delete(fn);
    },
    () => opened,
    () => opened,
  );

/** Статус обновлений. Старая служба без /updates (404) — undefined, тихо и без повторов. */
export function useUpdates() {
  return useQuery({
    ...q.updates(),
    refetchInterval: (query) => pollEvery(query.state.data),
    refetchOnWindowFocus: true,
    retry: (n, err) => !(err instanceof ApiError && err.status === 404) && n < 2,
    select: (s) => {
      noteVersion(s.current);
      return s;
    },
  });
}

export function useUpdateActions() {
  const qc = useQueryClient();
  const put = (s: UpdateStatus) => qc.setQueryData(["updates"], s);
  return {
    toggle: useMutation({
      mutationFn: async (auto: boolean) => data(await api.PUT("/updates", { body: { auto } })),
      onSuccess: put,
    }),
    check: useMutation({
      mutationFn: async () => data(await api.POST("/updates/check")),
      onSuccess: put,
    }),
    install: useMutation({
      mutationFn: async () => data(await api.POST("/updates/install")),
      onSuccess: put,
    }),
  };
}
