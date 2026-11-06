import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { type FormEvent, useRef } from "react";
import { useTranslation } from "react-i18next";
import { q } from "../../api/queries";
import { Icon } from "../../ui/icons";
import { useHotkeys } from "../keys";
import { applyTheme, readTheme, resolveTheme } from "../theme";

export function TopBar() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const input = useRef<HTMLInputElement>(null);
  const base = useQuery(q.base());
  useHotkeys({ focusSearch: () => input.current?.focus() });

  function submit(e: FormEvent) {
    e.preventDefault();
    const v = input.current?.value.trim() ?? "";
    if (v) navigate({ to: "/search", search: { q: v, kind: [], status: [], limit: 10 } });
  }
  const toggleTheme = () => applyTheme(resolveTheme(readTheme()) === "dark" ? "light" : "dark");

  return (
    <header className="bar">
      <Link to="/" className="wordmark" aria-label={t("app.home")}>
        amem
      </Link>
      {/* biome-ignore lint/a11y/useSemanticElements: role=search on the form is the standard landmark; <search> is not yet in every reader */}
      <form role="search" onSubmit={submit} className="bar__search">
        <Icon name="search" />
        <input
          ref={input}
          type="search"
          name="q"
          placeholder={t("nav.search")}
          aria-label={t("nav.search")}
          autoComplete="off"
        />
        <kbd>⌘</kbd>
        <kbd>K</kbd>
      </form>
      <nav className="bar__end" aria-label={t("nav.sections")}>
        <Link to="/review" className="navlink hide-s">
          {t("nav.review")}
          {base.data?.review_open ? <span className="badge">{base.data.review_open}</span> : null}
        </Link>
        <Link to="/changes" className="navlink hide-s">
          {t("nav.changes")}
        </Link>
        <Link to="/new" className="navlink" title={`${t("nav.write")}, N`}>
          <Icon name="plus" />
          <span className="hide-s">{t("nav.write")}</span>
        </Link>
        <button type="button" className="iconbtn" aria-label={t("nav.theme")} onClick={toggleTheme}>
          <Icon name="theme" />
        </button>
        <Link to="/settings" className="iconbtn" aria-label={t("nav.settings")}>
          <Icon name="user" />
        </Link>
      </nav>
    </header>
  );
}
