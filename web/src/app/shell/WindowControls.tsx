import { useTranslation } from "react-i18next";

/** Окно приложения amemo для Windows (desktop/, Tauri) — без системной рамки: веб-интерфейс, открытый в нём,
 * показывает кнопки окна в правом конце верхней панели, а пустое место панели перетаскивает окно
 * (data-tauri-drag-region). Признак — window.__TAURI__; в браузере их нет. Странице службы приложение разрешает
 * только команды окна (desktop/src-tauri/capabilities/service.json). */

interface TauriWindow {
  minimize(): Promise<void>;
  toggleMaximize(): Promise<void>;
  close(): Promise<void>;
}

function tauriWindow(): TauriWindow | null {
  const t = (window as unknown as { __TAURI__?: { window?: { getCurrentWindow(): TauriWindow } } }).__TAURI__;
  return t?.window?.getCurrentWindow() ?? null;
}

export const inApp = typeof window !== "undefined" && tauriWindow() !== null;

/** Атрибут перетаскивания окна для панели — только в приложении. */
export const dragRegion = inApp ? { "data-tauri-drag-region": "" } : {};

export function WindowControls() {
  const { t } = useTranslation();
  const win = inApp ? tauriWindow() : null;
  if (!win) return null;
  return (
    <div className="winctl">
      <button type="button" aria-label={t("window.minimize")} onClick={() => void win.minimize()}>
        <svg viewBox="0 0 10 10" aria-hidden="true">
          <path d="M1 5h8" />
        </svg>
      </button>
      <button type="button" aria-label={t("window.maximize")} onClick={() => void win.toggleMaximize()}>
        <svg viewBox="0 0 10 10" aria-hidden="true">
          <rect x="1.5" y="1.5" width="7" height="7" />
        </svg>
      </button>
      <button
        type="button"
        className="winctl__close"
        aria-label={t("window.close")}
        onClick={() => void win.close()}
      >
        <svg viewBox="0 0 10 10" aria-hidden="true">
          <path d="M2 2l6 6M8 2l-6 6" />
        </svg>
      </button>
    </div>
  );
}
