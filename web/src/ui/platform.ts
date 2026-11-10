// Подписи клавиш по системе: на macOS — ⌘, на Windows и Linux — Ctrl. Сами сочетания ловят и Meta, и Ctrl.
const platform =
  typeof navigator === "undefined"
    ? ""
    : ((navigator as Navigator & { userAgentData?: { platform?: string } }).userAgentData?.platform ??
      navigator.platform ??
      "");

export const isMac = /mac|iphone|ipad|ipod/i.test(platform);

/** Модификатор перед клавишей в подписи: «⌘K» или «Ctrl+K». */
export const MOD = isMac ? "⌘" : "Ctrl+";

/** Модификатор отдельной клавишей (<kbd>): «⌘» или «Ctrl». */
export const MOD_KEY = isMac ? "⌘" : "Ctrl";
