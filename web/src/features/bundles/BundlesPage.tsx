import { Tabs } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { ExportForm } from "./ExportForm";
import { ImportFlow } from "./ImportFlow";
import "../kinds/kinds.css";
import "../review/review.css";
import "../write/write.css";
import "./bundles.css";

/** Подборки (разд. 5.10): экспорт с антологией и импорт по шагам. */
export function BundlesPage() {
  const { t } = useTranslation();
  return (
    <section className="bundles" aria-labelledby="bundles-title">
      <div className="page-head">
        <h1 id="bundles-title">{t("bundles.title")}</h1>
      </div>
      <p className="muted">{t("bundles.intro")}</p>
      <Tabs defaultSelectedKey="export">
        <Tabs.ListContainer>
          <Tabs.List aria-label={t("bundles.title")}>
            <Tabs.Tab id="export">
              {t("bundles.tab_export")}
              <Tabs.Indicator />
            </Tabs.Tab>
            <Tabs.Tab id="import">
              {t("bundles.tab_import")}
              <Tabs.Indicator />
            </Tabs.Tab>
          </Tabs.List>
        </Tabs.ListContainer>
        <Tabs.Panel id="export">
          <ExportForm />
        </Tabs.Panel>
        <Tabs.Panel id="import">
          <ImportFlow />
        </Tabs.Panel>
      </Tabs>
    </section>
  );
}
