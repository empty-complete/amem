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
