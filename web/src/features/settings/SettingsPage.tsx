// Страница /settings — те же разделы, что в окне настроек (ссылки на /settings не ломаются); грузится лениво.
import { useTranslation } from "react-i18next";
import { SettingsView } from "./SettingsView";
import "../records/records.css";

export default function SettingsPage() {
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
