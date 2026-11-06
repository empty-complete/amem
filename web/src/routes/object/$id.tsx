import { createFileRoute } from "@tanstack/react-router";
import { ObjectPage } from "../../features/source/ObjectPage";

export const Route = createFileRoute("/object/$id")({
  component: function ObjectRoute() {
    const { id } = Route.useParams();
    return <ObjectPage objectId={id} />;
  },
});
