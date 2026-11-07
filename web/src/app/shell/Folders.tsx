import { useQuery } from "@tanstack/react-query";
import { Link, useRouterState, useSearch } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { q } from "../../api/queries";
import type { components } from "../../api/schema";
import { Icon, type IconName } from "../../ui/icons";

type Folder = components["schemas"]["Folder"];
const TOP_ICON: Record<string, IconName> = { Архив: "archive" };

function FolderItem({ f, current }: { f: Folder; current: string | null }) {
  return (
    <li>
      <Link to="/records" search={{ folder: f.path }} aria-current={current === f.path ? "page" : undefined}>
        <Icon name={TOP_ICON[f.path] ?? "folder"} />
        <span>{f.name}</span>
        <span className="n">{f.count}</span>
      </Link>
      {f.children.length > 0 && (
        <ul>
          {f.children.map((c) => (
            <FolderItem key={c.path} f={c} current={current} />
          ))}
        </ul>
      )}
    </li>
  );
}

/** Папки, как в Obsidian: новая база приходит с PARA, дальше люди ведут их сами (создание и перенос — часть D). */
export function Folders() {
  const { t } = useTranslation();
  const tree = useQuery(q.folders());
  const search = useSearch({ strict: false }) as { folder?: string };
  const current = search.folder ?? null;
  const onRecords = useRouterState({ select: (st) => st.location.pathname === "/records" });
  return (
    <nav className="folders" aria-label={t("folders.title")}>
      <ul>
        {tree.data?.folders.map((f) => (
          <FolderItem key={f.path} f={f} current={current} />
        ))}
      </ul>
      <ul className="sep">
        <li>
          <Link to="/records" search={{}} aria-current={current === null && onRecords ? "page" : undefined}>
            <Icon name="stack" />
            <span>{t("folders.all")}</span>
            <span className="n">{tree.data?.total ?? ""}</span>
          </Link>
        </li>
        <li>
          <Link to="/records" search={{ folder: "-" }} aria-current={current === "-" ? "page" : undefined}>
            <Icon name="inbox" />
            <span>{t("folders.unfiled")}</span>
            <span className="n">{tree.data?.unfiled ?? ""}</span>
          </Link>
        </li>
      </ul>
      <button type="button" className="newf" disabled title={t("stub.later")}>
        <Icon name="plus" size={12} />
        {t("folders.new")}
      </button>
    </nav>
  );
}
