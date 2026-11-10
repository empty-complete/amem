import { createHash } from "node:crypto";
import { chmodSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig, devices } from "@playwright/test";
import { TOKENS } from "./e2e/service/tokens";

// e2e против настоящей службы amemo (часть H): перед стартом — образец «метеостанция» в пустую базу AMEMO_DSN
// (tools/seed_sample.py), затем `python -m amemo.service`; сборка интерфейса — из python/amemo_web/dist (npm run build).
const PORT = Number(process.env.AMEMO_E2E_PORT ?? 8768);
const python = process.env.AMEMO_PYTHON ?? "python";
const state = join(tmpdir(), `amemo-e2e-${process.pid}`);
const env = {
  AMEMO_DSN: process.env.AMEMO_DSN ?? "",
  AMEMO_DATA: join(state, "objects"),
  AMEMO_DOCS: join(state, "docs"),
  AMEMO_STATE: join(state, "state"),
  AMEMO_BACKUPS: join(state, "backups"),
  AMEMO_BACKEND: "none",
  AMEMO_QUERY_LOG: "off",
  // пакет образца: классы датчиков с профилями — карточка сущности по профилю
  AMEMO_PACKS: join(process.cwd(), "..", "tools", "sample-pack", "meteo"),
};

// общая служба (AMEMO_TOKENS) — вторая служба на той же базе: вход по токену, cookie нет (e2e/service/token.spec.ts)
const TOKEN_PORT = PORT + 1;
const tokensFile = join(state, "tokens.toml");
mkdirSync(state, { recursive: true });
const hash = (t: string) => `sha256:${createHash("sha256").update(t).digest("hex")}`;
writeFileSync(
  tokensFile,
  `[[token]]\nhash = "${hash(TOKENS.writer)}"\nagent = "person:e2e"\nwrite = true\n\n` +
    `[[token]]\nhash = "${hash(TOKENS.reader)}"\nagent = "person:reader"\nwrite = false\n`,
);
chmodSync(tokensFile, 0o600);

export default defineConfig({
  testDir: "e2e/service",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI
    ? [["html", { open: "never", outputFolder: "playwright-report-service" }], ["github"]]
    : "list",
  use: { baseURL: `http://127.0.0.1:${PORT}/ui/`, trace: "retain-on-failure", locale: "ru-RU" },
  webServer: [
    {
      command: `${python} ../tools/seed_sample.py && ${python} -m amemo.service --port ${PORT}`,
      url: `http://127.0.0.1:${PORT}/health`,
      env,
      reuseExistingServer: false,
      timeout: 180_000,
    },
    {
      // та же база, уже с образцом (первая служба пишет его до старта): только вход по токену
      command: `${python} -m amemo.service --port ${TOKEN_PORT}`,
      url: `http://127.0.0.1:${TOKEN_PORT}/health`,
      env: { ...env, AMEMO_TOKENS: tokensFile },
      reuseExistingServer: false,
      timeout: 180_000,
    },
  ],
  projects: [
    {
      name: "service",
      testIgnore: /token\.spec/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
    {
      // после основного: общая служба смотрит в ту же базу
      name: "token",
      testMatch: /token\.spec/,
      dependencies: ["service"],
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1280, height: 800 },
        baseURL: `http://127.0.0.1:${TOKEN_PORT}/ui/`,
      },
    },
  ],
});
