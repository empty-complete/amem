import { Button, Dropdown, Label } from "@heroui/react";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useRouterState, useSearch } from "@tanstack/react-router";
import { type KeyboardEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { type DropItem, useDrag, useDrop } from "react-aria";
import { useTranslation } from "react-i18next";
import { ApiError } from "../../api/errors";
import { folderApi } from "../../api/folders";
import { q } from "../../api/queries";
import type { components } from "../../api/schema";
import { recordPath } from "../../features/records/RecordList";
import { useMoveRecord } from "../../features/write/move";
import { ColumnGrip } from "../../ui/ColumnGrip";
import { Icon, type IconName } from "../../ui/icons";
import { applyTheme, readTheme, resolveTheme } from "../theme";
import { useOpen } from "./folderTree";
import { menuStore, useMenuOpen } from "./menu";

type Folder = components["schemas"]["Folder"];
const TOP_ICON: Record<string, IconName> = { Архив: "archive" };
export const RECORD_MIME = "application/x-amemo-ref";
const toggleTheme = () => applyTheme(resolveTheme(readTheme()) === "dark" ? "light" : "dark");

/** Имя папки на месте: Enter — готово, Esc — отмена; ошибки службы словами под полем. */
function NameInput({
  initial,
  label,
  onDone,
  onCancel,
}: {
  initial: string;
  label: string;
  onDone: (v: string) => Promise<string | null>;
  onCancel: () => void;
}) {
  const [v, setV] = useState(initial);
  const [err, setErr] = useState<string | null>(null);
  const onKey = async (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") onCancel();
    if (e.key !== "Enter") return;
    e.preventDefault();
    const name = v.trim();
    if (!name) return onCancel();
    setErr(await onDone(name));
  };
  return (
    <span className="fname">
      <input
        className="fld"
        // biome-ignore lint/a11y/noAutofocus: поле появилось по нажатию «+ Папка» или «Переименовать»
        autoFocus
        aria-label={label}
        value={v}
        onChange={(e) => setV(e.target.value)}
        onKeyDown={onKey}
        onBlur={() => !v.trim() && onCancel()}
      />
      {err && (
        <span className="fielderr" role="alert">
          {err}
        </span>
      )}
    </span>
  );
}

const problemText = (e: unknown) => (e instanceof ApiError ? (e.detail ?? e.title) : String(e));

type Summary = components["schemas"]["RecordSummary"];

/** Запись в дереве: щелчок открывает её в рабочей области; строку можно перетащить на другую папку. */
function TreeRecord({ r, current }: { r: Summary; current: boolean }) {
  const { dragProps, isDragging } = useDrag({
    getItems: () => [{ [RECORD_MIME]: r.ref, "text/plain": r.label }],
    // щелчок и клавиши по строке — открыть запись, а не начать перетаскивание с клавиатуры (иначе следующий
    // щелчок отменяет перетаскивание); мышью строку тянут как раньше, с клавиатуры — «Переместить в папку»
    hasDragButton: true,
  });
  return (
    <li {...dragProps} data-dragging={isDragging || undefined}>
      <Link
        className="frec"
        {...recordPath(r.ref)}
        aria-current={current ? "page" : undefined}
        title={r.label}
      >
        <Icon name="file" size={14} />
        <span>{r.label}</span>
      </Link>
    </li>
  );
}

/** Записи раздела (без вложенных папок — они стоят своими ветками): грузятся при раскрытии, страницами. */
function TreeRecords({ folder }: { folder: string | null }) {
  const { t } = useTranslation();
  const list = useInfiniteQuery(q.recordPages(folder, {}, folder === null || folder === "-"));
  const path = useRouterState({ select: (st) => st.location.pathname });
  const items = list.data?.pages.flatMap((p) => p.items) ?? [];
  if (list.isPending) return <p className="frecs__note">{t("region.loading")}</p>;
  if (!items.length) return <p className="frecs__note">{t("folders.empty")}</p>;
  return (
    <ul className="frecs">
      {items.map((r) => (
        <TreeRecord key={r.ref} r={r} current={path.endsWith(`/${r.ref}`)} />
      ))}
      {list.hasNextPage && (
        <li>
          <button
            type="button"
            className="frow-btn frecs__more"
            disabled={list.isFetchingNextPage}
            onClick={() => void list.fetchNextPage()}
          >
            <span />
            <span>{list.isFetchingNextPage ? t("records.loading_more") : t("records.more")}</span>
          </button>
        </li>
      )}
    </ul>
  );
}

/** Строка раздела: стрелка и имя раскрывают записи в панели; значок справа открывает раздел списком. */
function TreeRow({
  open,
  onToggle,
  icon,
  name,
  count,
  list,
  listed,
  children,
}: {
  open: boolean;
  onToggle: () => void;
  icon: IconName;
  name: string;
  count?: number | string;
  list: { folder?: string };
  listed: boolean;
  children?: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <span className="frow">
      <button type="button" className="frow-btn ftoggle" aria-expanded={open} onClick={onToggle}>
        <Icon name="chev" size={12} className="ftoggle__chev" />
        <Icon name={icon} />
        <span>{name}</span>
        <span className="n">{count}</span>
      </button>
      <Link
        className="flist"
        to="/records"
        search={list}
        aria-label={t("folders.as_list", { name })}
        title={t("folders.as_list", { name })}
        aria-current={listed ? "page" : undefined}
      >
        <Icon name="stack" size={14} />
      </Link>
      {children}
    </span>
  );
}

function FolderItem({
  f,
  current,
  person,
  depth = 0,
}: {
  f: Folder;
  current: string | null;
  person: boolean;
  depth?: number;
}) {
  const { t } = useTranslation();
  const [open, toggle] = useOpen(f.path);
  const qc = useQueryClient();
  const move = useMoveRecord();
  const [mode, setMode] = useState<"idle" | "rename" | "child">("idle");
  const [err, setErr] = useState<string | null>(null);
  const ref = useRef<HTMLLIElement>(null);
  const { dropProps, isDropTarget } = useDrop({
    ref,
    getDropOperation: (types) => (types.has(RECORD_MIME) ? "move" : "cancel"),
    async onDrop(e) {
      for (const it of e.items as DropItem[]) {
        if (it.kind !== "text" || !it.types.has(RECORD_MIME)) continue;
        const r = await it.getText(RECORD_MIME);
        move(r, f.path, t("folders.moved", { to: f.name }));
      }
    },
  });
  const refresh = () => {
    for (const k of ["folders", "records"]) qc.invalidateQueries({ queryKey: [k] });
  };
  return (
    <li ref={ref} {...dropProps} data-drop={isDropTarget || undefined}>
      {mode === "rename" ? (
        <NameInput
          initial={f.name}
          label={t("folders.rename")}
          onCancel={() => setMode("idle")}
          onDone={async (name) => {
            const to = f.path.includes("/") ? `${f.path.slice(0, f.path.lastIndexOf("/"))}/${name}` : name;
            try {
              await folderApi.rename(f.path, to);
              setMode("idle");
              refresh();
              return null;
            } catch (e) {
              return problemText(e);
            }
          }}
        />
      ) : (
        <TreeRow
          open={open}
          onToggle={toggle}
          icon={TOP_ICON[f.path] ?? "folder"}
          name={f.name}
          count={f.count}
          list={{ folder: f.path }}
          listed={current === f.path}
        >
          {person && (
            <Dropdown>
              <Button
                isIconOnly
                size="sm"
                variant="ghost"
                className="fmenu"
                aria-label={t("folders.menu", { name: f.name })}
              >
                <Icon name="more" />
              </Button>
              <Dropdown.Popover>
                <Dropdown.Menu
                  onAction={async (k) => {
                    setErr(null);
                    if (k === "child") setMode("child");
                    if (k === "rename") setMode("rename");
                    if (k === "delete") {
                      try {
                        await folderApi.remove(f.path);
                        refresh();
                      } catch (e) {
                        setErr(problemText(e));
                      }
                    }
                  }}
                >
                  <Dropdown.Item id="child" textValue={t("folders.new_inside")}>
                    <Label>{t("folders.new_inside")}</Label>
                  </Dropdown.Item>
                  <Dropdown.Item id="rename" textValue={t("folders.rename")}>
                    <Label>{t("folders.rename")}</Label>
                  </Dropdown.Item>
                  <Dropdown.Item id="delete" textValue={t("folders.delete")}>
                    <Label>{t("folders.delete")}</Label>
                  </Dropdown.Item>
                </Dropdown.Menu>
              </Dropdown.Popover>
            </Dropdown>
          )}
        </TreeRow>
      )}
      {err && (
        <span className="fielderr" role="alert">
          {err}
        </span>
      )}
      {open && <TreeRecords folder={f.path} />}
      {(f.children.length > 0 || mode === "child") && (
        <ul>
          {f.children.map((c) => (
            <FolderItem key={c.path} f={c} current={current} person={person} depth={depth + 1} />
          ))}
          {mode === "child" && (
            <li>
              <NewFolder parent={f.path} onClose={() => setMode("idle")} />
            </li>
          )}
        </ul>
      )}
    </li>
  );
}

function NewFolder({ parent, onClose }: { parent: string | null; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  return (
    <NameInput
      initial=""
      label={t("folders.new_name")}
      onCancel={onClose}
      onDone={async (name) => {
        try {
          await folderApi.create(parent ? `${parent}/${name}` : name);
          qc.invalidateQueries({ queryKey: ["folders"] });
          onClose();
          return null;
        } catch (e) {
          return problemText(e);
        }
      }}
    />
  );
}

/** Папки деревом, как в Obsidian (разд. 5.11): раздел раскрывается в панели и показывает свои записи, запись
 * открывается в рабочей области; человек создаёт, переименовывает и удаляет пустые папки; запись переносится
 * перетаскиванием. Широкий список — по значку справа от раздела (и результаты поиска и фильтра). */
export function Folders() {
  const { t } = useTranslation();
  const tree = useQuery(q.folders());
  const base = useQuery(q.base());
  const session = useQuery(q.session());
  const person = !!session.data?.agent.startsWith("person:");
  const search = useSearch({ strict: false }) as { folder?: string };
  const current = search.folder ?? null;
  const onRecords = useRouterState({ select: (st) => st.location.pathname === "/records" });
  const [adding, setAdding] = useState(false);
  const [allOpen, toggleAll] = useOpen("*");
  const [unfiledOpen, toggleUnfiled] = useOpen("-");
  const move = useMoveRecord();
  const menuOpen = useMenuOpen();
  const href = useRouterState({ select: (st) => st.location.href });
  // biome-ignore lint/correctness/useExhaustiveDependencies: закрываем меню при каждом переходе
  useEffect(() => menuStore.set(false), [href]);
  const unfiled = useRef<HTMLLIElement>(null);
  const { dropProps, isDropTarget } = useDrop({
    ref: unfiled,
    getDropOperation: (types) => (types.has(RECORD_MIME) ? "move" : "cancel"),
    async onDrop(e) {
      for (const it of e.items as DropItem[])
        if (it.kind === "text" && it.types.has(RECORD_MIME))
          move(await it.getText(RECORD_MIME), null, t("folders.moved", { to: t("folders.unfiled") }));
    },
  });
  return (
    <nav id="folders" className="folders" aria-label={t("folders.title")} data-open={menuOpen || undefined}>
      <ColumnGrip name="--folders-w" label={t("folders.width")} min={180} max={520} initial={248} />
      <ul>
        {tree.data?.folders.map((f) => (
          <FolderItem key={f.path} f={f} current={current} person={person} />
        ))}
        {adding && (
          <li>
            <NewFolder parent={null} onClose={() => setAdding(false)} />
          </li>
        )}
      </ul>
      <ul className="sep">
        <li>
          <TreeRow
            open={allOpen}
            onToggle={toggleAll}
            icon="stack"
            name={t("folders.all")}
            count={tree.data?.total ?? ""}
            list={{}}
            listed={current === null && onRecords}
          />
          {allOpen && <TreeRecords folder={null} />}
        </li>
        <li ref={unfiled} {...dropProps} data-drop={isDropTarget || undefined}>
          <TreeRow
            open={unfiledOpen}
            onToggle={toggleUnfiled}
            icon="inbox"
            name={t("folders.unfiled")}
            count={tree.data?.unfiled ?? ""}
            list={{ folder: "-" }}
            listed={current === "-"}
          />
          {unfiledOpen && <TreeRecords folder="-" />}
        </li>
      </ul>
      {person && (
        <button type="button" className="newf" onClick={() => setAdding(true)}>
          <Icon name="plus" size={12} />
          {t("folders.new")}
        </button>
      )}
      <ul className="sep show-s">
        <li>
          <Link to="/review">
            <Icon name="check" />
            <span>{t("nav.review")}</span>
            <span className="n">{base.data?.review_open || ""}</span>
          </Link>
        </li>
        <li>
          <Link to="/changes">
            <Icon name="history" />
            <span>{t("nav.changes")}</span>
          </Link>
        </li>
        <li>
          <Link to="/base">
            <Icon name="shield" />
            <span>{t("nav.base")}</span>
          </Link>
        </li>
        <li>
          <Link to="/bundles">
            <Icon name="archive" />
            <span>{t("nav.bundles")}</span>
          </Link>
        </li>
        <li>
          <Link to="/settings">
            <Icon name="user" />
            <span>{t("nav.settings")}</span>
          </Link>
        </li>
        <li>
          <button type="button" className="frow-btn" onClick={toggleTheme}>
            <Icon name="theme" />
            <span>{t("nav.theme")}</span>
          </button>
        </li>
      </ul>
    </nav>
  );
}
