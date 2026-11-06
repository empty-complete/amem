import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRouter, RouterProvider } from "@tanstack/react-router";
import { useEffect } from "react";
import { I18nProvider } from "react-aria-components";
import { useTranslation } from "react-i18next";
import { routeTree } from "../routeTree.gen";
import { parseSearch, stringifySearch } from "./search-url";
import { watchSystemTheme } from "./theme";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 30_000 } } });
export const router = createRouter({
  routeTree,
  basepath: "/ui",
  defaultPreload: "intent",
  parseSearch,
  stringifySearch,
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

export function App() {
  const { i18n } = useTranslation();
  useEffect(() => watchSystemTheme(), []);
  return (
    <I18nProvider locale={i18n.language}>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </I18nProvider>
  );
}
