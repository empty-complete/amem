import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";
import { ChangesPage } from "../features/changes/ChangesPage";

export const Route = createFileRoute("/changes")({
  validateSearch: z.object({
    who: z.enum(["all", "person", "model"]).optional().catch(undefined),
    since: z.enum(["7", "30", "ever"]).optional().catch(undefined),
  }),
  component: function ChangesRoute() {
    const { who, since } = Route.useSearch();
    return <ChangesPage who={who ?? "all"} since={since ?? "7"} />;
  },
});
