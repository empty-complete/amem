import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { api, data } from "../../api/client";
import { enqueue } from "./submitQueue";

const KEYS = ["records", "records-about", "record", "folders", "changes"];

/** Перенос записи в папку: уходит сразу, «Перенесено в Архив · Отменить» возвращает в прежнюю папку. */
export function useMoveRecord() {
  const qc = useQueryClient();
  return useCallback(
    (ref: string, folder: string | null, what: string) => {
      // прежняя папка — для «Отменить»; узнаём у службы, а не из кэша: перетаскивают и из списков без папки
      let before: string | null | undefined;
      const patch = (to: string | null) =>
        api.PATCH("/records/{ref}/folder", { params: { path: { ref } }, body: { folder: to } });
      return enqueue({
        label: ref,
        what,
        toast: what,
        kind: "move",
        about: [],
        body: { proposals: [], links: [] },
        apply: async () => {
          before = data(await api.GET("/records/{ref}", { params: { path: { ref } } })).folder ?? null;
          await patch(folder);
        },
        revert: async () => {
          if (before !== undefined) await patch(before);
        },
        onDone: () => {
          for (const k of KEYS) qc.invalidateQueries({ queryKey: [k] });
        },
      });
    },
    [qc],
  );
}

/** Перенос списком (выбор в списке): один запрос службе и одна строка «Отменить» — каждая запись вернётся в свою
 * прежнюю папку. refs — ссылки или обещание их (все отобранные фильтром — по страницам у службы). */
export function useMoveRecords() {
  const qc = useQueryClient();
  return useCallback(
    (refs: string[] | (() => Promise<string[]>), folder: string | null, what: string) => {
      let moved: { ref: string; from: string | null; moved: boolean }[] = [];
      return enqueue({
        label: what,
        what,
        toast: what,
        kind: "move",
        about: [],
        body: { proposals: [], links: [] },
        apply: async () => {
          const list = typeof refs === "function" ? await refs() : refs;
          moved = data(await api.POST("/records/move", { body: { refs: list, folder } })).moved;
        },
        revert: async () => {
          const back = new Map<string | null, string[]>();
          for (const m of moved.filter((x) => x.moved))
            back.set(m.from, [...(back.get(m.from) ?? []), m.ref]);
          for (const [from, list] of back)
            await api.POST("/records/move", { body: { refs: list, folder: from } });
        },
        onDone: () => {
          for (const k of KEYS) qc.invalidateQueries({ queryKey: [k] });
        },
      });
    },
    [qc],
  );
}
