import { createRootRoute, Outlet } from "@tanstack/react-router";
import { Folders } from "../app/shell/Folders";
import { TopBar } from "../app/shell/TopBar";
import "../app/shell/shell.css";

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
    </div>
  ),
});
