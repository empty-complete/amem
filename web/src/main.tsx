import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles/app.css";
import "./app/registry-instance";
import { App } from "./app/App";
import { setupI18n } from "./app/i18n";

async function boot() {
  if (import.meta.env.DEV && import.meta.env.VITE_MOCK === "1") {
    const { worker } = await import("./mocks/browser");
    await worker.start({
      serviceWorker: { url: `${import.meta.env.BASE_URL}mockServiceWorker.js` },
      onUnhandledFrame: "bypass",
      quiet: true,
    });
  }
  await setupI18n();
  const root = document.getElementById("root");
  if (root)
    createRoot(root).render(
      <StrictMode>
        <App />
      </StrictMode>,
    );
}
void boot();
