// Настройки разделами, как в Obsidian: слева поиск и разделы, справа строки «подпись — значение». Одна разметка —
// и в окне (кнопка внизу панели папок, Ctrl+,), и на странице /settings.
import { Button } from "@heroui/react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { type ReactNode, useId, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { auth, useAuthToken } from "../../api/auth";
import { q } from "../../api/queries";
import type { components } from "../../api/schema";
import { changeLocale, type Locale } from "../../app/i18n";
import { registry } from "../../app/registry-instance";
import { useNewNoteFolder } from "../../app/shell/folderTree";
import { applyTheme, readTheme, type Theme } from "../../app/theme";
import { agentName } from "../../ui/format";
import { Icon, type IconName } from "../../ui/icons";
import { MOD } from "../../ui/platform";
import { UpdatesSection } from "../updates/UpdatesSection";
import { CORE_PLUGINS, type CorePlugin, setCorePlugin, settingsWindow, useCorePlugin } from "./store";
import "./settings.css";

type Folder = components["schemas"]["Folder"];
const flat = (fs: Folder[]): string[] => fs.flatMap((f) => [f.path, ...flat(f.children)]);

/** Строка настройки: подпись и пояснение слева, значение справа. */
function Row({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="settings__row">
      <span>
        {label}
        {hint && <small className="muted">{hint}</small>}
      </span>
      <span className="settings__ctl">{children}</span>
    </div>
  );
}

function Language() {
  const { t, i18n } = useTranslation();
  return (
    <select
      className="fld"
      aria-label={t("settings.language")}
      value={i18n.language.startsWith("en") ? "en" : "ru"}
      onChange={(e) => changeLocale(e.target.value as Locale)}
    >
      <option value="ru">{t("lang.ru")}</option>
      <option value="en">{t("lang.en")}</option>
    </select>
  );
}

function ThemeSelect() {
  const { t } = useTranslation();
  const [theme, setTheme] = useState<Theme>(readTheme);
  return (
    <select
      className="fld"
      aria-label={t("settings.theme")}
      value={theme}
      onChange={(e) => {
        const v = e.target.value as Theme;
        setTheme(v);
        applyTheme(v);
      }}
    >
      {(["system", "light", "dark"] as const).map((v) => (
        <option key={v} value={v}>
          {t(`theme.${v}`)}
        </option>
      ))}
    </select>
  );
}

/** «Куда класть новые записи» — путь папки, как в Obsidian: пусто — корень; папки нет — служба заведёт её с первой
 * записью. Подсказки — пути уже заведённых папок; сохраняется по Enter и при уходе из поля. */
function NewInField() {
  const { t } = useTranslation();
  const [newIn, setNewIn] = useNewNoteFolder();
  const [text, setText] = useState(newIn);
  const tree = useQuery(q.folders());
  const list = useId();
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
    <>
      <input
        className="fld"
        aria-label={t("settings.new_in")}
        list={list}
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
      <datalist id={list}>
        {flat(tree.data?.folders ?? []).map((p) => (
          <option key={p} value={p} />
        ))}
      </datalist>
    </>
  );
}

function About() {
  const { t, i18n } = useTranslation();
  const session = useQuery(q.session());
  const token = useAuthToken();
  return (
    <>
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
        <div className="settings__leave">
          <Button variant="outline" onPress={() => auth.clear()}>
            {t("signin.leave")}
          </Button>
          <p className="muted">{t("signin.leave_hint")}</p>
        </div>
      )}
    </>
  );
}

function CoreToggle({ id }: { id: CorePlugin }) {
  const { t } = useTranslation();
  const on = useCorePlugin(id);
  return (
    <label className="settings__switch">
      <input
        type="checkbox"
        role="switch"
        aria-checked={on}
        checked={on}
        onChange={(e) => setCorePlugin(id, e.target.checked)}
      />
      <span className="sr-only">{t(`settings.core.${id}`)}</span>
    </label>
  );
}

function KindsLink() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  return (
    <Button
      variant="outline"
      onPress={() => {
        settingsWindow.close();
        void navigate({ to: "/kinds" });
      }}
    >
      {t("edit.kind_configure")}
    </Button>
  );
}

/** Клавиши: команды плагинов и клавиши редактора — справкой (переназначение — позже, как в Obsidian). */
function Hotkeys() {
  const { t, i18n } = useTranslation();
  const lang = i18n.language.startsWith("en") ? "en" : "ru";
  const editor: [string, string][] = [
    [`${MOD}+E`, t("settings.key_edit")],
    [`${MOD}+Enter`, t("settings.key_save")],
    [`${MOD}+K`, t("settings.key_search")],
    ["Shift+C", t("settings.key_collapse")],
  ];
  const rows: [string, string][] = [
    ...[...registry.commands.values()]
      .filter((c) => c.keys)
      .map((c) => [c.keys ?? "", c.title[lang]] as [string, string]),
    ...editor,
  ];
  return (
    <table className="settings__keys">
      <tbody>
        {rows.map(([keys, what]) => (
          <tr key={`${keys}-${what}`}>
            <td>{what}</td>
            <td>
              {keys.split(" ").map((k) => (
                <kbd key={k}>{k}</kbd>
              ))}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

type Item = { id: string; label: string; hint?: string; wide?: boolean; render: () => ReactNode };
type Section = { id: string; icon: IconName; title: string; items: Item[] };

function useSections(): Section[] {
  const { t } = useTranslation();
  return [
    {
      id: "general",
      icon: "user",
      title: t("settings.s_general"),
      items: [
        { id: "language", label: t("settings.language"), render: () => <Language /> },
        { id: "updates", label: t("updates.title"), wide: true, render: () => <UpdatesSection /> },
        { id: "about", label: t("settings.s_about"), wide: true, render: () => <About /> },
      ],
    },
    {
      id: "appearance",
      icon: "theme",
      title: t("settings.s_appearance"),
      items: [{ id: "theme", label: t("settings.theme"), render: () => <ThemeSelect /> }],
    },
    {
      id: "files",
      icon: "folder",
      title: t("settings.s_files"),
      items: [
        {
          id: "new_in",
          label: t("settings.new_in"),
          hint: t("settings.new_in_hint"),
          render: () => <NewInField />,
        },
      ],
    },
    {
      id: "kinds",
      icon: "stack",
      title: t("kinds.title"),
      items: [{ id: "kinds", label: t("kinds.title"), hint: t("kinds.intro"), render: () => <KindsLink /> }],
    },
    {
      id: "hotkeys",
      icon: "code",
      title: t("settings.s_hotkeys"),
      items: [{ id: "keys", label: t("settings.s_hotkeys"), wide: true, render: () => <Hotkeys /> }],
    },
    {
      id: "core",
      icon: "shield",
      title: t("settings.s_core"),
      items: CORE_PLUGINS.map((id) => ({
        id,
        label: t(`settings.core.${id}`),
        hint: t(`settings.core_hint.${id}`),
        render: () => <CoreToggle id={id} />,
      })),
    },
  ];
}

/** Настройки: поиск по подписям и пояснениям всех разделов; без поиска — выбранный раздел. */
export function SettingsView({ initial = "general", titleId }: { initial?: string; titleId?: string }) {
  const { t } = useTranslation();
  const sections = useSections();
  const [current, setCurrent] = useState(initial);
  const [query, setQuery] = useState("");
  const shown = useMemo(() => {
    const s = query.trim().toLowerCase();
    if (!s) return sections.filter((x) => x.id === current);
    return sections
      .map((x) => ({
        ...x,
        items: x.items.filter((it) => `${x.title} ${it.label} ${it.hint ?? ""}`.toLowerCase().includes(s)),
      }))
      .filter((x) => x.items.length);
  }, [sections, current, query]);
  return (
    <div className="setview">
      <nav className="setview__nav" aria-label={t("settings.sections")}>
        <input
          className="fld"
          type="search"
          aria-label={t("settings.search")}
          placeholder={t("settings.search")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <ul>
          {sections.map((x) => (
            <li key={x.id}>
              <button
                type="button"
                className="setview__sec"
                aria-current={!query && x.id === current ? "page" : undefined}
                onClick={() => {
                  setQuery("");
                  setCurrent(x.id);
                }}
              >
                <Icon name={x.icon} />
                {x.title}
              </button>
            </li>
          ))}
        </ul>
      </nav>
      <div className="setview__body">
        {!shown.length && <p className="muted">{t("settings.nothing")}</p>}
        {shown.map((x, i) => (
          <section
            key={x.id}
            className="settings__group"
            aria-labelledby={i === 0 && titleId ? titleId : `set-${x.id}`}
          >
            <h2 id={i === 0 && titleId ? titleId : `set-${x.id}`}>{x.title}</h2>
            {x.items.map((it) =>
              it.wide ? (
                <div key={it.id} className="settings__wide">
                  {it.render()}
                </div>
              ) : (
                <Row key={it.id} label={it.label} hint={it.hint}>
                  {it.render()}
                </Row>
              ),
            )}
          </section>
        ))}
      </div>
    </div>
  );
}
