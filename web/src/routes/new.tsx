import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";
import { NewRecord } from "../features/write/NewRecord";

export const Route = createFileRoute("/new")({
  validateSearch: z.object({
    about: z.string().optional().catch(undefined),
    kind: z.string().optional().catch(undefined),
    related: z.string().optional().catch(undefined),
    issue: z.string().optional().catch(undefined),
  }),
  component: function NewRoute() {
    const s = Route.useSearch();
    return <NewRecord about={s.about} kind={s.kind} related={s.related} issue={s.issue} />;
  },
});
