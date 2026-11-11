import { createFileRoute } from "@tanstack/react-router";
import { ReviewPage } from "../features/review/ReviewPage";
import { reviewSearch } from "./review";

export const Route = createFileRoute("/review_/$itemId")({
  validateSearch: reviewSearch,
  component: function ReviewItemRoute() {
    const { itemId } = Route.useParams();
    const s = Route.useSearch();
    return (
      <ReviewPage
        itemId={itemId}
        reason={s.reason}
        state={s.state ?? "open"}
        group={s.group}
        object={s.object}
        about={s.about}
        who={s.who}
      />
    );
  },
});
