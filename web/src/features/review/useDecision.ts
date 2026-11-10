import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { apiFetch } from "../../api/auth";
import { langHeaders } from "../../api/client";
import { problemFromResponse } from "../../api/errors";
import { enqueue, usePending } from "../write/submitQueue";

export type Outcome = "confirmed" | "refuted";
const KEYS = [
  "review-items",
  "review-item",
  "review-stats",
  "base",
  "record",
  "records",
  "records-about",
  "changes",
  "graph",
];

/** Решение по пункту — та же очередь с окном отмены, что у записи (часть D): 6 с, keepalive при уходе. */
export function useDecision(onAlready: (who: string) => void) {
  const qc = useQueryClient();
  return useCallback(
    (itemId: string, outcome: Outcome, what: string, note?: string) =>
      enqueue({
        label: itemId,
        what,
        toast: what,
        kind: "review",
        about: [],
        body: { proposals: [], links: [] },
        run: async (keepalive) => {
          const res = await apiFetch(`${location.origin}/api/v1/review/items/${itemId}/resolve`, {
            method: "POST",
            headers: { "content-type": "application/json", ...langHeaders() },
            body: JSON.stringify({ outcome, ...(note?.trim() ? { note: note.trim() } : {}) }),
            keepalive,
          });
          if (res.status === 409) {
            const p = await problemFromResponse(res);
            onAlready(p.detail ?? "");
            return;
          }
          if (!res.ok) throw await problemFromResponse(res);
        },
        onDone: () => {
          for (const k of KEYS) qc.invalidateQueries({ queryKey: [k] });
        },
      }),
    [qc, onAlready],
  );
}

/** Пункты, решение по которым ждёт окна отмены: из списка они уже ушли, «Отменить» вернёт. */
export function usePendingDecisions(): Set<string> {
  const pending = usePending();
  return new Set(pending.filter((p) => p.kind === "review").map((p) => p.label));
}
