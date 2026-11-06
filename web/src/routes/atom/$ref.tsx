import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";
import { RecordPage } from "../../features/record/RecordPage";

export const Route = createFileRoute("/atom/$ref")({
  validateSearch: z.object({ view: z.enum(["human", "source", "agent"]).catch("human") }),
  component: function AtomRoute() {
    const { ref } = Route.useParams();
    const { view } = Route.useSearch();
    return <RecordPage recordRef={ref} view={view} />;
  },
});
