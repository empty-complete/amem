import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useRef } from "react";
import { useTranslation } from "react-i18next";
import { q } from "../../api/queries";
import { CommandField } from "../../features/palette/CommandField";
import { UpdateBadge } from "../../features/updates/UpdateBadge";
import { placeStore, useQuickOpen } from "../../features/write/place";
import { QuickWrite } from "../../features/write/QuickWrite";
import { Icon } from "../../ui/icons";
import { useHotkeys } from "../keys";
import { applyTheme, readTheme, resolveTheme } from "../theme";
import { menuStore, useMenuOpen } from "./menu";
import { dragRegion, inApp, WindowControls } from "./WindowControls";

export function TopBar() {
  const { t } = useTranslation();
  const input = useRef<HTMLInputElement>(null);
  const base = useQuery(q.base());
  const writeBtn = useRef<HTMLButtonElement>(null);
  const quickOpen = useQuickOpen();
  const menuOpen = useMenuOpen();
  useHotkeys({ focusSearch: () => input.current?.focus() });

  const toggleTheme = () => applyTheme(resolveTheme(readTheme()) === "dark" ? "light" : "dark");

  return (
    <header className="bar" data-app={inApp ? "tauri" : undefined} {...dragRegion}>
      <button
        type="button"
        className="iconbtn show-s"
        aria-label={t("nav.menu")}
        aria-expanded={menuOpen}
        aria-controls="folders"
        onClick={() => menuStore.set(!menuOpen)}
      >
        <Icon name={menuOpen ? "cross" : "menu"} />
      </button>
      <Link to="/" className="wordmark" aria-label={t("app.home")}>
        amemo
      </Link>
      {/* biome-ignore lint/a11y/useSemanticElements: role=search — стандартный ориентир; <search> ещё не во всех чтецах */}
      <div role="search" className="bar__searchwrap">
        <CommandField ref={input} />
      </div>
      <nav className="bar__end" aria-label={t("nav.sections")}>
        <Link to="/review" className="navlink hide-s">
          {t("nav.review")}
          {base.data?.review_open ? <span className="badge">{base.data.review_open}</span> : null}
        </Link>
        <Link to="/changes" className="navlink hide-s">
          {t("nav.changes")}
        </Link>
        <button
          ref={writeBtn}
          type="button"
          className="navlink navbtn"
          title={`${t("nav.write")}, N`}
          aria-expanded={quickOpen}
          onClick={() => placeStore.openQuick(!quickOpen)}
        >
          <Icon name="plus" />
          <span className="hide-s">{t("nav.write")}</span>
        </button>
        <QuickWrite trigger={writeBtn} />
        <button type="button" className="iconbtn hide-s" aria-label={t("nav.theme")} onClick={toggleTheme}>
          <Icon name="theme" />
        </button>
        <UpdateBadge />
        <Link to="/settings" className="iconbtn hide-s" aria-label={t("nav.settings")}>
          <Icon name="user" />
        </Link>
      </nav>
      <WindowControls />
    </header>
  );
}
