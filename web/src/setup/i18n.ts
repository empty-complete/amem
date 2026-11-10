import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import type { Lang } from "./bridge";
import en from "./i18n/en.json";
import ru from "./i18n/ru.json";

/** Тексты мастера — свои (src/setup/i18n), не тексты веб-интерфейса: точка входа setup собирается отдельно. */
export async function setupI18n(lang: Lang) {
  await i18n.use(initReactI18next).init({
    resources: { ru: { translation: ru }, en: { translation: en } },
    lng: lang,
    fallbackLng: "ru",
    interpolation: { escapeValue: false },
  });
  document.documentElement.lang = lang;
  document.title = i18n.t("title");
}

export async function setLang(lang: Lang) {
  await i18n.changeLanguage(lang);
  document.documentElement.lang = lang;
  document.title = i18n.t("title");
}
