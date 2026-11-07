import { createFileRoute } from "@tanstack/react-router";
import { BundlesPage } from "../features/bundles/BundlesPage";

export const Route = createFileRoute("/bundles")({ component: BundlesPage });
