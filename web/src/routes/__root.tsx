import { createRootRoute, Outlet } from "@tanstack/react-router";
import { lazy, Suspense } from "react";
import { useTranslation } from "react-i18next";
import { Folders } from "../app/shell/Folders";
import { SignIn } from "../app/shell/SignIn";
import { TopBar } from "../app/shell/TopBar";
import { useKindsOpen } from "../features/kinds/store";
import { ReloadBanner } from "../features/updates/ReloadBanner";
import { UndoToasts } from "../features/write/UndoToast";
import { ColumnGrip } from "../ui/ColumnGrip";
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

/** Край панели папок: тянется мышью или стрелками, ширина запоминается. */
function FoldersGrip() {
  const { t } = useTranslation();
  return (
    <ColumnGrip
      name="--folders-w"
      label={t("folders.width")}
      min={180}
      max={520}
      initial={248}
      className="foldersgrip"
    />
  );
}

export const Route = createRootRoute({
  component: () => (
    <div className="shell">
      <TopBar />
      <ReloadBanner />
      <div className="body">
        <Folders />
        <FoldersGrip />
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
