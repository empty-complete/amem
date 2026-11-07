import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { skyBus } from "../sky/bus";
import type { Family } from "../sky/model";
import type { LinkProposal, Proposal } from "./proposal";
import { enqueue, type Pending } from "./submitQueue";

/** Записать пакет с окном отмены; по успеху — перечитать всё, что могло измениться, и заменить временную звезду. */
export function useSubmit() {
  const qc = useQueryClient();
  return useCallback(
    (
      body: { proposals: Proposal[]; links?: LinkProposal[] },
      meta: {
        label: string;
        what: string;
        kind: string;
        about: string[];
        family?: Family;
        onDone?: Pending["onDone"];
        onIssues?: Pending["onIssues"];
      },
    ) => {
      let id = "";
      id = enqueue(
        {
          label: meta.label,
          what: meta.what,
          kind: meta.kind,
          about: meta.about,
          body: { proposals: body.proposals, links: body.links ?? [] },
          onDone: (r) => {
            skyBus.retract(id);
            for (const k of [
              "records",
              "records-about",
              "record",
              "graph",
              "card",
              "folders",
              "changes",
              "history",
              "base",
              "search",
            ])
              qc.invalidateQueries({ queryKey: [k] });
            meta.onDone?.(r);
          },
          onIssues: meta.onIssues,
        },
        meta.about.length
          ? {
              label: meta.label,
              kind: meta.kind,
              family: meta.family ?? "work",
              status: "verified",
              pending: false,
              object: false,
              degree: meta.about.length,
              depth: 1,
              r: 2.6,
            }
          : undefined,
      );
      return id;
    },
    [qc],
  );
}
