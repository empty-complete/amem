import { type Bridge, type Choices, type Progress, STAGES, type Stage } from "./bridge";

const GB = 1024 ** 3;
const MB = 1024 ** 2;

/** Заглушка моста для браузера, тестов и снимков. Параметры адреса:
 * - `lang=en` — язык по умолчанию;
 * - `step=data|docs|features|agents|install|done` — начать с шага (снимки);
 * - `freeze=<шаг установки>` — установка останавливается на этом шаге (снимок экрана установки);
 * - `fail=<шаг установки>` — шаг завершается ошибкой;
 * - `nonansi=1` — папка данных не открывается программами PostgreSQL (кириллица в английской Windows);
 * - `low=1` — места на томе меньше, чем нужно;
 * - `fast=1` — без пауз (тесты). */
export function mockBridge(params: URLSearchParams): Bridge {
  const fast = params.get("fast") === "1";
  const wait = (ms: number) => new Promise((r) => setTimeout(r, fast ? 0 : ms));
  const freeze = params.get("freeze") as Stage | null;
  const fail = params.get("fail") as Stage | null;
  let picked = 0;
  let failed = false; // ошибка — один раз: «Повторить» проходит
  return {
    inApp: false,
    async defaults() {
      return {
        lang: params.get("lang") === "en" ? "en" : "ru",
        dataDir:
          params.get("nonansi") === "1" ? "C:\\Users\\Анна\\amemo-data" : "C:\\Users\\anna\\amemo-data",
        docsDir: "C:\\Users\\anna\\Documents",
        agents: { claude: true, codex: false },
        version: "0.1.0a2",
      };
    },
    async checkFolder(path) {
      const ansiSafe = !(params.get("nonansi") === "1" && /[^\x20-\x7e]/.test(path));
      return {
        free: params.get("low") === "1" ? 0.6 * GB : 212 * GB,
        need: 1.4 * GB,
        ansiSafe,
        notEmpty: false,
        fallback: ansiSafe ? null : "C:\\amemo-data",
      };
    },
    async pickFolder() {
      picked += 1;
      return `D:\\amemo-${picked}`;
    },
    async install(choices: Choices, onProgress: (p: Progress) => void) {
      for (const stage of STAGES) {
        const skip =
          (stage === "ocr" && choices.ocr.length === 0) || (stage === "agents" && !choices.agents.length);
        if (skip) {
          onProgress({ stage, state: "skipped" });
          continue;
        }
        if (stage === "download") {
          const total = 420 * MB;
          for (let received = 0; received < total; received += 60 * MB) {
            onProgress({ stage, state: "running", received, total, rate: 18 * MB });
            if (freeze === stage && received >= 180 * MB) return new Promise(() => {});
            await wait(250);
          }
        } else {
          onProgress({ stage, state: "running" });
          if (freeze === stage) return new Promise(() => {});
          await wait(700);
        }
        if (fail === stage && !failed) {
          failed = true;
          const message =
            "pg_ctl start: код 1; журнал — C:\\Users\\anna\\amemo-data\\pg\\log\\postgresql.log";
          onProgress({ stage, state: "failed", message });
          throw new Error(message);
        }
        onProgress({ stage, state: "done" });
      }
    },
    async finish() {
      await wait(300);
    },
    window: { minimize() {}, toggleMaximize() {}, close() {} },
  };
}
