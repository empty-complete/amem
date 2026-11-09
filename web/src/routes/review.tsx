import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";
import { ReviewPage } from "../features/review/ReviewPage";

export const reviewSearch = z.object({
  reason: z.string().optional().catch(undefined),
  state: z.enum(["open", "done"]).optional().catch(undefined),
  group: z.enum(["source"]).optional().catch(undefined),
  object: z.string().optional().catch(undefined),
  about: z.string().optional().catch(undefined),
});

export const Route = createFileRoute("/review")({
  validateSearch: reviewSearch,
  component: function ReviewRoute() {
    const s = Route.useSearch();
    return (
      <ReviewPage
        reason={s.reason}
        state={s.state ?? "open"}
        group={s.group}
        object={s.object}
        about={s.about}
      />
    );
  },
});
