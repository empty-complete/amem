import { Button, Label, Radio, RadioGroup } from "@heroui/react";
import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { auth, useAuthToken } from "../api/auth";
import { q } from "../api/queries";
import type { components } from "../api/schema";
import { changeLocale, type Locale } from "../app/i18n";
import { useFolderDepth, useNewNoteFolder } from "../app/shell/folderTree";
import { applyTheme, readTheme, type Theme } from "../app/theme";
import { kindsStore } from "../features/kinds/store";
import { LABEL_CHOICES, useLabelMax } from "../features/sky/prefs";
import { UpdatesSection } from "../features/updates/UpdatesSection";
import { agentName } from "../ui/format";
import "../features/records/records.css";

export const Route = createFileRoute("/settings")({ component: Settings });

type Folder = components["schemas"]["Folder"];
const flat = (fs: Folder[], depth = 0): { path: string; name: string; depth: number }[] =>
  fs.flatMap((f) => [{ path: f.path, name: f.name, depth }, ...flat(f.children, depth + 1)]);

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
  const token = useAuthToken();
  const [labelMax, setLabelMax] = useLabelMax();
  const [depth, setDepth] = useFolderDepth();
  const [newIn, setNewIn] = useNewNoteFolder();
  const tree = useQuery(q.folders());
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
      <div>
        <Choice
          label={t("settings.folder_depth")}
          value={String(depth)}
          options={[
            ["1", t("settings.depth_1")],
            ["2", t("settings.depth_2")],
            ["3", t("settings.depth_3")],
          ]}
          onChange={(v) => setDepth(Number(v))}
        />
        <p className="muted">{t("settings.folder_depth_hint")}</p>
      </div>
      <div>
        <Choice
          label={t("settings.sky_label")}
          value={String(labelMax)}
          options={LABEL_CHOICES.map(
            (n) => [String(n), t("settings.sky_label_n", { n })] as [string, string],
          )}
          onChange={(v) => setLabelMax(Number(v))}
        />
        <p className="muted">{t("settings.sky_label_hint")}</p>
      </div>
      <label className="fl" style={{ display: "grid", gap: 6 }}>
        <span>{t("settings.new_in")}</span>
        <select
          className="fld"
          value={newIn}
          onChange={(e) => setNewIn(e.target.value)}
          style={{ maxWidth: 320 }}
        >
          <option value="">{t("settings.new_in_root")}</option>
          {flat(tree.data?.folders ?? []).map((f) => (
            <option key={f.path} value={f.path}>
              {"  ".repeat(f.depth)}
              {f.name}
            </option>
          ))}
        </select>
        <span className="muted">{t("settings.new_in_hint")}</span>
      </label>
      {token && (
        <div>
          <Button variant="outline" onPress={() => auth.clear()}>
            {t("signin.leave")}
          </Button>
          <p className="muted">{t("signin.leave_hint")}</p>
        </div>
      )}
      <UpdatesSection />
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
          <dd style={{ margin: 0 }}>{agentName(session.data.agent, i18n.language)}</dd>
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
