import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";
import { BundlesPage } from "../features/bundles/BundlesPage";

export const Route = createFileRoute("/bundles")({
  validateSearch: z.object({ tab: z.enum(["export", "import"]).optional().catch(undefined) }),
  component: function Bundles() {
    const { tab } = Route.useSearch();
    return <BundlesPage tab={tab} />;
  },
});
