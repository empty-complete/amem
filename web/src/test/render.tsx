import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
} from "@tanstack/react-router";
import { act, render } from "@testing-library/react";
import type { ReactNode } from "react";

/** Отрисовать компонент внутри роутера и клиента запросов (без повторов). */
export async function renderWithApp(ui: ReactNode, path = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const root = createRootRoute({ component: () => <Outlet /> });
  const routes = [
    "/",
    "/bundles",
    "/search",
    "/atom/$ref",
    "/entity/$ref",
    "/object/$id",
    "/changes",
    "/review",
    "/review/$itemId",
    "/base",
    "/new",
  ].map((p) => createRoute({ getParentRoute: () => root, path: p, component: () => <>{ui}</> }));
  const router = createRouter({
    routeTree: root.addChildren(routes),
    history: createMemoryHistory({ initialEntries: [path] }),
  });
  await act(() => router.load());
  const result = render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { ...result, router };
}
