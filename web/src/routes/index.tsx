import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";
import { HomeSky } from "../features/home/HomeSky";

const FAMILIES = ["source", "work", "object"] as const;

export const Route = createFileRoute("/")({
  validateSearch: z.object({
    f: z
      .string()
      .optional()
      .catch(undefined)
      .transform(
        (v) =>
          v
            ?.split(",")
            .filter((x) => (FAMILIES as readonly string[]).includes(x))
            .join(",") || undefined,
      ),
    pending: z.coerce.boolean().optional().catch(undefined),
    center: z.string().optional().catch(undefined),
    project: z.string().optional().catch(undefined),
  }),
  component: function Home() {
    const s = Route.useSearch();
    return <HomeSky families={s.f} pending={!!s.pending} center={s.center} project={s.project} />;
  },
});
