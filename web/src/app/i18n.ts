import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";

export type Locale = "ru" | "en";
const KEY = "amemo.locale";

export function readLocale(lang = typeof navigator === "undefined" ? "ru" : navigator.language): Locale {
  try {
    const v = window.localStorage.getItem(KEY);
    if (v === "ru" || v === "en") return v;
  } catch {
    // хранилище недоступно
  }
  return lang.toLowerCase().startsWith("en") ? "en" : "ru";
}

export async function setupI18n(locale: Locale = readLocale()) {
  if (!i18n.isInitialized) {
    await i18n.use(initReactI18next).init({
      resources: { ru: { translation: ru }, en: { translation: en } },
      lng: locale,
      fallbackLng: "ru",
      interpolation: { escapeValue: false },
    });
  }
  document.documentElement.lang = locale;
  return i18n;
}

export async function changeLocale(locale: Locale) {
  try {
    window.localStorage.setItem(KEY, locale);
  } catch {
    // хранилище недоступно
  }
  await i18n.changeLanguage(locale);
  document.documentElement.lang = locale;
}

export { i18n };
