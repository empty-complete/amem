import { createFileRoute } from "@tanstack/react-router";
import { searchParams } from "../features/search/params";
import { SearchResults } from "../features/search/SearchResults";

export const Route = createFileRoute("/search")({
  validateSearch: searchParams,
  component: () => <SearchResults params={Route.useSearch()} />,
});
