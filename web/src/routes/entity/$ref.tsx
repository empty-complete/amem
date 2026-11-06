import { createFileRoute } from "@tanstack/react-router";
import { CardPage } from "../../features/card/CardPage";

export const Route = createFileRoute("/entity/$ref")({
  component: function EntityRoute() {
    const { ref } = Route.useParams();
    return <CardPage key={ref} entityRef={ref} />;
  },
});
