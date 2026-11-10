import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../styles/app.css";
import "./setup.css";
import { bridge } from "./bridge";
import { setupI18n } from "./i18n";
import { Wizard } from "./Wizard";

/** Мастер первого запуска приложения amemo для Windows (setup.html). */
async function boot() {
  const b = await bridge();
  const defaults = await b.defaults();
  await setupI18n(defaults.lang);
  if (b.inApp) document.documentElement.dataset.app = "tauri";
  const root = document.getElementById("root");
  if (root)
    createRoot(root).render(
      <StrictMode>
        <Wizard bridge={b} defaults={defaults} />
      </StrictMode>,
    );
}
void boot();
