import { createRootRoute, Outlet } from "@tanstack/react-router";
import { lazy, Suspense } from "react";
import { Folders } from "../app/shell/Folders";
import { SignIn } from "../app/shell/SignIn";
import { TopBar } from "../app/shell/TopBar";
import { useKindsOpen } from "../features/kinds/store";
import { UndoToasts } from "../features/write/UndoToast";
import "../app/shell/shell.css";

const KindDrawer = lazy(() =>
  import("../features/kinds/KindDrawer").then((m) => ({ default: m.KindDrawer })),
);

/** Конструктор видов грузится, только когда его открыли. */
function KindsLazy() {
  const open = useKindsOpen();
  return open ? (
    <Suspense fallback={null}>
      <KindDrawer />
    </Suspense>
  ) : null;
}

export const Route = createRootRoute({
  component: () => (
    <div className="shell">
      <TopBar />
      <div className="body">
        <Folders />
        <main className="main" id="main">
          <div className="main__in">
            <Outlet />
          </div>
        </main>
      </div>
      <UndoToasts />
      <KindsLazy />
      <SignIn />
    </div>
  ),
});
