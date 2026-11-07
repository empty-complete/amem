import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { api } from "../../api/client";
import { enqueue } from "./submitQueue";

const KEYS = ["records", "records-about", "record", "folders", "changes"];

/** Перенос записи в папку с окном отмены: «Перенесено в Архив · Отменить». */
export function useMoveRecord() {
  const qc = useQueryClient();
  return useCallback(
    (ref: string, folder: string | null, what: string) =>
      enqueue({
        label: ref,
        what,
        toast: what,
        kind: "move",
        about: [],
        body: { proposals: [], links: [] },
        run: async () => {
          await api.PATCH("/records/{ref}/folder", { params: { path: { ref } }, body: { folder } });
        },
        onDone: () => {
          for (const k of KEYS) qc.invalidateQueries({ queryKey: [k] });
        },
      }),
    [qc],
  );
}
