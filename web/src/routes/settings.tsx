import { Button } from "@heroui/react";
import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { auth, useAuthToken } from "../api/auth";
import { q } from "../api/queries";
import type { components } from "../api/schema";
import { changeLocale, type Locale } from "../app/i18n";
import { useNewNoteFolder } from "../app/shell/folderTree";
import { UpdatesSection } from "../features/updates/UpdatesSection";
import { agentName } from "../ui/format";
import "../features/records/records.css";
import "../features/settings/settings.css";

export const Route = createFileRoute("/settings")({ component: Settings });

type Folder = components["schemas"]["Folder"];
const flat = (fs: Folder[], depth = 0): { path: string; name: string; depth: number }[] =>
  fs.flatMap((f) => [{ path: f.path, name: f.name, depth }, ...flat(f.children, depth + 1)]);

/** «Куда класть новые записи» — путь папки, как в Obsidian: пусто — корень; папки нет — служба заведёт её с первой
 * записью. Подсказки — пути уже заведённых папок; сохраняется по Enter и при уходе из поля. */
function NewInField() {
  const { t } = useTranslation();
  const [newIn, setNewIn] = useNewNoteFolder();
  const [text, setText] = useState(newIn);
  const tree = useQuery(q.folders());
  const paths = flat(tree.data?.folders ?? []).map((f) => f.path);
  const save = () => {
    const path = text
      .split("/")
      .map((x) => x.trim())
      .filter(Boolean)
      .join("/");
    setText(path);
    if (path !== newIn) setNewIn(path);
  };
  return (
    <label className="settings__row">
      <span>
        {t("settings.new_in")}
        <small className="muted">{t("settings.new_in_hint")}</small>
      </span>
      <input
        className="fld"
        list="settings-folders"
        value={text}
        placeholder={t("settings.new_in_root")}
        spellCheck={false}
        onChange={(e) => setText(e.target.value)}
        onBlur={save}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            save();
          }
        }}
      />
      <datalist id="settings-folders">
        {paths.map((p) => (
          <option key={p} value={p} />
        ))}
      </datalist>
    </label>
  );
}

/** Настройки — только то, что меняют: язык, куда класть новые записи, обновления; о службе — справкой.
 * Тема — кнопкой в шапке; вложенность папок не ограничена. */
function Settings() {
  const { t, i18n } = useTranslation();
  const session = useQuery(q.session());
  const token = useAuthToken();
  return (
    <section className="settings" aria-labelledby="settings-title">
      <div className="page-head">
        <h1 id="settings-title">{t("settings.title")}</h1>
      </div>

      <div className="settings__group">
        <label className="settings__row">
          <span>{t("settings.language")}</span>
          <select
            className="fld"
            value={i18n.language.startsWith("en") ? "en" : "ru"}
            onChange={(e) => changeLocale(e.target.value as Locale)}
          >
            <option value="ru">{t("lang.ru")}</option>
            <option value="en">{t("lang.en")}</option>
          </select>
        </label>
        <NewInField />
        <div className="settings__row">
          <span>
            {t("kinds.title")}
            <small className="muted">{t("kinds.intro")}</small>
          </span>
          <Link className="navlink" to="/kinds">
            {t("edit.kind_configure")}
          </Link>
        </div>
      </div>

      <UpdatesSection />

      {session.data && (
        <dl className="settings__about">
          <dt>{t("settings.who")}</dt>
          <dd>{agentName(session.data.agent, i18n.language)}</dd>
          <dt>{t("settings.service")}</dt>
          <dd>{session.data.base_name || t("settings.base_unnamed")}</dd>
          <dt>{t("settings.version")}</dt>
          <dd>{session.data.amem_version}</dd>
        </dl>
      )}
      {token && (
        <div>
          <Button variant="outline" onPress={() => auth.clear()}>
            {t("signin.leave")}
          </Button>
          <p className="muted">{t("signin.leave_hint")}</p>
        </div>
      )}
    </section>
  );
}
