import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

// разделы настроек — отдельным куском: основная часть приложения их не тянет
export const Route = createFileRoute("/settings")({
  component: lazyRouteComponent(() => import("../features/settings/SettingsPage")),
});
