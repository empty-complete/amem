/** Мост мастера к приложению для Windows (desktop/, Tauri): что мастер спрашивает у машины и что просит сделать.
 *
 * В приложении это команды Rust (`invoke`, desktop/src-tauri); в браузере, в тестах и в
 * снимках — заглушка `mock.ts`. Мастер знает только этот интерфейс. */

export type Lang = "ru" | "en";

/** Языки распознавания сканов, которые предлагает мастер (коды tesseract). */
export const OCR_LANGS = ["rus", "eng", "ukr", "deu", "fra", "spa"] as const;
export type OcrLang = (typeof OCR_LANGS)[number];

export type AgentId = "claude" | "codex";

/** отказ start(), когда фон на паузе */
export const PAUSED = "paused";

export interface Defaults {
  lang: Lang;
  /** %USERPROFILE%\amemo-data */
  dataDir: string;
  /** папка, которую стоит предложить для документов (Документы пользователя), или null */
  docsDir: string | null;
  /** найденные на машине агенты */
  agents: Record<AgentId, boolean>;
  /** версия устанавливаемого amemo */
  version: string;
  /** "setup" — мастер; "start" — мастер уже пройден: экран запуска, пока поднимаются база и служба */
  mode: "setup" | "start";
}

export interface FolderCheck {
  /** свободно на томе, байт */
  free: number;
  /** сколько нужно amemo: комплект, модель и место под базу, байт */
  need: number;
  /** путь открывается программами PostgreSQL (кодовая страница ANSI или короткие имена 8.3) */
  ansiSafe: boolean;
  /** папка уже есть и в ней что-то лежит (не прежняя установка amemo) */
  notEmpty: boolean;
  /** запасной путь для PostgreSQL, когда ansiSafe = false */
  fallback: string | null;
}

export interface Choices {
  lang: Lang;
  dataDir: string;
  docsDir: string | null;
  ocr: OcrLang[];
  agents: AgentId[];
}

/** Шаги экрана установки, по порядку. */
export const STAGES = ["download", "database", "store", "search", "ocr", "agents"] as const;
export type Stage = (typeof STAGES)[number];

export type StageState = "waiting" | "running" | "done" | "skipped" | "failed";

export interface Progress {
  stage: Stage;
  state: StageState;
  /** загрузка: получено и всего байт, скорость байт/с */
  received?: number;
  total?: number;
  rate?: number;
  /** ошибка шага словами (failed) */
  message?: string;
}

/** Плагин amemo для приложения Claude: zip, который человек загружает сам (Customize → Plugins → Add → Upload
 * plugin), и загружен ли он уже — его видно в Claude Code как amemo@synced. */
export interface PluginInfo {
  path: string;
  synced: boolean;
}

export interface Finish {
  desktopShortcut: boolean;
  autostart: boolean;
}

export interface Bridge {
  /** в приложении — свой заголовок окна; в браузере — нет */
  readonly inApp: boolean;
  defaults(): Promise<Defaults>;
  checkFolder(path: string): Promise<FolderCheck>;
  /** системный выбор папки; null — человек передумал */
  pickFolder(initial: string | null): Promise<string | null>;
  /** установка по выбору; onProgress — каждое изменение шага; ошибка шага — отказ промиса */
  install(choices: Choices, onProgress: (p: Progress) => void): Promise<void>;
  /** шаг «плагин»: где zip и загружен ли плагин (приложение заодно снимает прямую установку в Claude Code) */
  plugin(): Promise<PluginInfo>;
  /** открыть приложение Claude */
  openClaude(): Promise<void>;
  /** показать файл в Проводнике */
  showFile(path: string): Promise<void>;
  /** ярлык, автозапуск и переход в окно amemo */
  finish(options: Finish): Promise<void>;
  /** экран запуска: дождаться базы и службы — окно само перейдёт в amemo. resume — снять паузу. Отказ — текст
   * ошибки или PAUSED (фон на паузе из значка в области уведомлений) */
  start(resume: boolean): Promise<void>;
  window: { minimize(): void; toggleMaximize(): void; close(): void };
}

interface TauriGlobal {
  core: { invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> };
  event: { listen<T>(name: string, cb: (e: { payload: T }) => void): Promise<() => void> };
  window: { getCurrentWindow(): { minimize(): void; toggleMaximize(): void; close(): void } };
}

function tauri(): TauriGlobal | undefined {
  return (window as unknown as { __TAURI__?: TauriGlobal }).__TAURI__;
}

/** Команды приложения (desktop/src-tauri/src/setup.rs и main.rs): setup_defaults, setup_check_folder,
 * setup_pick_folder, setup_install (события setup://progress), setup_plugin, setup_open_claude, setup_show_file,
 * setup_finish, app_start, app_resume. */
function tauriBridge(t: TauriGlobal): Bridge {
  const win = t.window.getCurrentWindow();
  return {
    inApp: true,
    defaults: () => t.core.invoke<Defaults>("setup_defaults"),
    checkFolder: (path) => t.core.invoke<FolderCheck>("setup_check_folder", { path }),
    pickFolder: (initial) => t.core.invoke<string | null>("setup_pick_folder", { initial }),
    async install(choices, onProgress) {
      const stop = await t.event.listen<Progress>("setup://progress", (e) => onProgress(e.payload));
      try {
        await t.core.invoke("setup_install", { choices });
      } finally {
        stop();
      }
    },
    plugin: () => t.core.invoke<PluginInfo>("setup_plugin"),
    openClaude: () => t.core.invoke("setup_open_claude"),
    showFile: (path) => t.core.invoke("setup_show_file", { path }),
    finish: (options) => t.core.invoke("setup_finish", { options }),
    start: (resume) => t.core.invoke(resume ? "app_resume" : "app_start"),
    window: {
      minimize: () => win.minimize(),
      toggleMaximize: () => win.toggleMaximize(),
      close: () => win.close(),
    },
  };
}

export async function bridge(): Promise<Bridge> {
  const t = tauri();
  if (t) return tauriBridge(t);
  const { mockBridge } = await import("./mock");
  return mockBridge(new URLSearchParams(window.location.search));
}
