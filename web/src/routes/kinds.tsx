import { createFileRoute } from "@tanstack/react-router";
import { lazy, Suspense } from "react";
import { RegionState } from "../ui/RegionState";

const KindDrawer = lazy(() =>
  import("../features/kinds/KindDrawer").then((m) => ({ default: m.KindDrawer })),
);

/** «Мои виды» — отдельной страницей, как раздел настроек; конструктор грузится лениво. */
export const Route = createFileRoute("/kinds")({
  component: () => (
    <Suspense fallback={<RegionState state="loading" />}>
      <KindDrawer page />
    </Suspense>
  ),
});
