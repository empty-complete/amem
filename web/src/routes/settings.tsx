import { Button, Label, Radio, RadioGroup } from "@heroui/react";
import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { q } from "../api/queries";
import { changeLocale, type Locale } from "../app/i18n";
import { applyTheme, readTheme, type Theme } from "../app/theme";
import { kindsStore } from "../features/kinds/store";
import "../features/records/records.css";

export const Route = createFileRoute("/settings")({ component: Settings });

function Choice({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: [string, string][];
  onChange: (v: string) => void;
}) {
  return (
    <RadioGroup value={value} onChange={onChange} name={label}>
      <Label>{label}</Label>
      {options.map(([v, text]) => (
        <Radio key={v} value={v}>
          <Radio.Content>
            <Radio.Control>
              <Radio.Indicator />
            </Radio.Control>
            {text}
          </Radio.Content>
        </Radio>
      ))}
    </RadioGroup>
  );
}

function Settings() {
  const { t, i18n } = useTranslation();
  const [theme, setTheme] = useState<Theme>(readTheme());
  const session = useQuery(q.session());
  return (
    <section aria-labelledby="settings-title" style={{ display: "grid", gap: 24, maxWidth: 520 }}>
      <div className="page-head">
        <h1 id="settings-title">{t("settings.title")}</h1>
      </div>
      <Choice
        label={t("settings.theme")}
        value={theme}
        options={[
          ["system", t("theme.system")],
          ["light", t("theme.light")],
          ["dark", t("theme.dark")],
        ]}
        onChange={(v) => {
          setTheme(v as Theme);
          applyTheme(v as Theme);
        }}
      />
      <Choice
        label={t("settings.language")}
        value={i18n.language.startsWith("en") ? "en" : "ru"}
        options={[
          ["ru", t("lang.ru")],
          ["en", t("lang.en")],
        ]}
        onChange={(v) => changeLocale(v as Locale)}
      />
      {session.data && (
        <dl
          style={{
            display: "grid",
            gridTemplateColumns: "max-content 1fr",
            gap: "8px 24px",
            fontSize: "var(--t-label)",
            margin: 0,
          }}
        >
          <dt style={{ color: "var(--muted)" }}>{t("settings.who")}</dt>
          <dd style={{ margin: 0 }}>{session.data.agent}</dd>
          <dt style={{ color: "var(--muted)" }}>{t("settings.service")}</dt>
          <dd style={{ margin: 0 }}>{session.data.base_name ?? session.data.base}</dd>
          <dt style={{ color: "var(--muted)" }}>{t("settings.version")}</dt>
          <dd style={{ margin: 0 }}>{session.data.amem_version}</dd>
        </dl>
      )}
      <h2 style={{ fontSize: "var(--t-label)", color: "var(--muted)", marginTop: "var(--s-lg)" }}>
        {t("kinds.title")}
      </h2>
      <p className="muted">{t("kinds.intro")}</p>
      <div>
        <Button variant="outline" onPress={() => kindsStore.open()}>
          {t("edit.kind_configure")}
        </Button>
      </div>
    </section>
  );
}
