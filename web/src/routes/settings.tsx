import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { SettingsView } from "../features/settings/SettingsView";
import "../features/records/records.css";

export const Route = createFileRoute("/settings")({ component: Settings });

/** Страница настроек — те же разделы, что в окне настроек (ссылки на /settings не ломаются). */
function Settings() {
  const { t } = useTranslation();
  return (
    <section className="settings" aria-labelledby="settings-title">
      <div className="page-head">
        <h1 id="settings-title">{t("settings.title")}</h1>
      </div>
      <SettingsView />
    </section>
  );
}
