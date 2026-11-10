import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig, devices } from "@playwright/test";

// e2e против настоящей службы amem (часть H): перед стартом — образец «метеостанция» в пустую базу AMEM_DSN
// (tools/seed_sample.py), затем `python -m amem.service`; сборка интерфейса — из python/amem_web/dist (npm run build).
const PORT = Number(process.env.AMEM_E2E_PORT ?? 8768);
const python = process.env.AMEM_PYTHON ?? "python";
const state = join(tmpdir(), `amem-e2e-${process.pid}`);
const env = {
  AMEM_DSN: process.env.AMEM_DSN ?? "",
  AMEM_DATA: join(state, "objects"),
  AMEM_DOCS: join(state, "docs"),
  AMEM_STATE: join(state, "state"),
  AMEM_BACKUPS: join(state, "backups"),
  AMEM_BACKEND: "none",
  AMEM_QUERY_LOG: "off",
  // пакет образца: классы датчиков с профилями — карточка сущности по профилю
  AMEM_PACKS: join(process.cwd(), "..", "tools", "sample-pack", "meteo"),
};

export default defineConfig({
  testDir: "e2e/service",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI
    ? [["html", { open: "never", outputFolder: "playwright-report-service" }], ["github"]]
    : "list",
  use: { baseURL: `http://127.0.0.1:${PORT}/ui/`, trace: "retain-on-failure", locale: "ru-RU" },
  webServer: {
    command: `${python} ../tools/seed_sample.py && ${python} -m amem.service --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/health`,
    env,
    reuseExistingServer: false,
    timeout: 180_000,
  },
  projects: [
    { name: "service", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } } },
  ],
});
