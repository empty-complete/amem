import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useRouterState, useSearch } from "@tanstack/react-router";
import {
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
  type RefObject,
  useEffect,
  useRef,
  useState,
} from "react";
import { type DropItem, type TextDropItem, useDrag, useDrop } from "react-aria";
import {
  Dialog,
  Heading,
  Menu,
  MenuItem,
  Modal,
  ModalOverlay,
  Popover,
  Separator,
} from "react-aria-components";
import { useTranslation } from "react-i18next";
import { ApiError } from "../../api/errors";
import { folderApi } from "../../api/folders";
import { q } from "../../api/queries";
import type { components } from "../../api/schema";
import { ExportForm } from "../../features/bundles/ExportForm";
import { recordPath } from "../../features/records/RecordList";
import { MoveDialog } from "../../features/write/MoveDialog";
import { useMoveRecord, useMoveRecords } from "../../features/write/move";
import { Icon } from "../../ui/icons";
import { applyTheme, readTheme, resolveTheme } from "../theme";
import { collapseAll, treePick, useOpen, useTreePick } from "./folderTree";
import { menuStore, useMenuOpen } from "./menu";

type Folder = components["schemas"]["Folder"];
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

/** Ссылки заметок дерева сверху вниз — для Shift-диапазона. */
const treeOrder = () =>
  [...document.querySelectorAll<HTMLElement>("#folders [data-ref]")].map((el) => el.dataset.ref ?? "");

/** Точка меню: у правого щелчка — курсор, у клавиши меню (Shift+F10) — под строкой. */
const pointOf = (e: MouseEvent) => {
  if (e.clientX || e.clientY) return { x: e.clientX, y: e.clientY };
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
  return { x: r.left + 16, y: r.bottom };
};

type Point = { x: number; y: number };
/** Что открыто правой кнопкой: пустое место панели, папка или выбранные заметки. */
type MenuAt =
  | { at: Point; on: "root" }
  | { at: Point; on: "folder"; f: Folder }
  | { at: Point; on: "records" };
/** Что правится на месте: имя папки или новая папка внутри (path null — в корне). */
type Edit = { path: string | null; mode: "rename" | "child" };

/** Меню в точке правого щелчка, как в Obsidian: опора — невидимая точка, пункты — React Aria Menu. */
function PointMenu({
  at,
  label,
  items,
  onAction,
  onClose,
}: {
  at: Point | null;
  label: string;
  items: ({ id: string; label: string; meta?: ReactNode } | "-")[];
  onAction: (key: string) => void;
  onClose: () => void;
}) {
  const anchorRef = useRef<HTMLSpanElement>(null);
  return (
    <>
      <span ref={anchorRef} aria-hidden="true" className="ctx__anchor" style={{ left: at?.x, top: at?.y }} />
      <Popover
        triggerRef={anchorRef}
        isOpen={!!at}
        onOpenChange={(o) => !o && onClose()}
        placement="bottom start"
        offset={4}
        className="palette ctxmenu"
      >
        <Menu
          aria-label={label}
          autoFocus="first"
          className="palette__list"
          onAction={(k) => {
            onClose();
            onAction(String(k));
          }}
        >
          {items.map((it, i) =>
            it === "-" ? (
              // biome-ignore lint/suspicious/noArrayIndexKey: разделители без своих ключей, порядок не меняется
              <Separator key={`sep${i}`} className="ctxmenu__sep" />
            ) : (
              <MenuItem key={it.id} id={it.id} textValue={it.label} className="palette__opt ctxmenu__opt">
                <span className="palette__label">{it.label}</span>
                {it.meta != null && <span className="palette__meta">{it.meta}</span>}
              </MenuItem>
            ),
          )}
        </Menu>
      </Popover>
    </>
  );
}

/** Перенос перетаскиванием на папку (to — путь, null — корень): одна заметка или все выбранные сразу. */
function useRecordDrop(ref: RefObject<HTMLElement | null>, to: string | null, name: string) {
  const { t } = useTranslation();
  const move = useMoveRecord();
  const moveMany = useMoveRecords();
  return useDrop({
    ref,
    getDropOperation: (types) => (types.has(RECORD_MIME) ? "move" : "cancel"),
    async onDrop(e) {
      const refs = await Promise.all(
        (e.items as DropItem[])
          .filter((it): it is TextDropItem => it.kind === "text" && it.types.has(RECORD_MIME))
          .map((it) => it.getText(RECORD_MIME)),
      );
      const [one] = refs;
      if (refs.length === 1 && one) move(one, to, t("folders.moved", { to: name }));
      else if (refs.length > 1) {
        moveMany(refs, to, t("folders.moved_many", { count: refs.length, to: name }));
        treePick.clear();
      }
    },
  });
}

/** Запись в дереве: щелчок открывает её в рабочей области и выбирает; Ctrl/⌘ — добавить к выбору, Shift —
 * диапазон, правая кнопка — меню выбранного; строку (или все выбранные) можно перетащить на другую папку. */
function TreeRecord({
  r,
  current,
  picked,
  onMenu,
}: {
  r: Summary;
  current: boolean;
  picked: boolean;
  onMenu: (m: MenuAt) => void;
}) {
  const path = useRouterState({ select: (st) => st.location.pathname });
  const { dragProps, isDragging } = useDrag({
    getItems: () => {
      const sel = treePick.get();
      const refs = sel.has(r.ref) ? [...sel] : [r.ref];
      return refs.map((ref) => ({ [RECORD_MIME]: ref, "text/plain": ref === r.ref ? r.label : ref }));
    },
    // щелчок и клавиши по строке — открыть запись, а не начать перетаскивание с клавиатуры (иначе следующий
    // щелчок отменяет перетаскивание); мышью строку тянут как раньше, с клавиатуры — «Переместить в папку»
    hasDragButton: true,
  });
  return (
    <li
      {...dragProps}
      data-dragging={isDragging || undefined}
      data-ref={r.ref}
      data-picked={picked || undefined}
    >
      <Link
        className="frec"
        {...recordPath(r.ref)}
        aria-current={current ? "page" : undefined}
        title={r.label}
        onClick={(e) => {
          const add = e.ctrlKey || e.metaKey;
          if (e.shiftKey) {
            e.preventDefault();
            treePick.range(r.ref, treeOrder(), { add, from: path.split("/").pop() ?? null });
          } else if (add) {
            e.preventDefault();
            treePick.toggle(r.ref);
          } else treePick.set([r.ref]);
        }}
        onContextMenu={(e) => {
          e.preventDefault();
          e.stopPropagation();
          if (!treePick.get().has(r.ref)) treePick.set([r.ref]);
          onMenu({ at: pointOf(e), on: "records" });
        }}
      >
        <Icon name="file" size={14} />
        <span>{r.label}</span>
      </Link>
    </li>
  );
}

/** Записи раздела (без вложенных папок — они стоят своими ветками): грузятся при раскрытии, все страницы подряд —
 * «Показать ещё» в дереве нет. folder «-» — записи без папки, они стоят в корне под папками. */
function TreeRecords({ folder, onMenu }: { folder: string; onMenu: (m: MenuAt) => void }) {
  const { t } = useTranslation();
  const list = useInfiniteQuery(q.recordPages(folder, {}, folder === "-"));
  const path = useRouterState({ select: (st) => st.location.pathname });
  const picked = useTreePick();
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = list;
  useEffect(() => {
    if (hasNextPage && !isFetchingNextPage) void fetchNextPage();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);
  const items = list.data?.pages.flatMap((p) => p.items) ?? [];
  const root = folder === "-";
  if (list.isPending) return root ? null : <p className="frecs__note">{t("region.loading")}</p>;
  if (!items.length) return root ? null : <p className="frecs__note">{t("folders.empty")}</p>;
  return (
    <ul className={root ? "frecs frecs--root" : "frecs"}>
      {items.map((r) => (
        <TreeRecord
          key={r.ref}
          r={r}
          current={path.endsWith(`/${r.ref}`)}
          picked={picked.has(r.ref)}
          onMenu={onMenu}
        />
      ))}
      {isFetchingNextPage && <li className="frecs__note">{t("records.loading_more")}</li>}
    </ul>
  );
}

/** Окна для выбранных заметок: поделиться (подборка с исходными файлами) и перенести в папку. */
function TreeDialogs({
  sharing,
  moving,
  onClose,
}: {
  sharing: string[] | null;
  moving: string[] | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const moveMany = useMoveRecords();
  return (
    <>
      <ModalOverlay
        isOpen={sharing != null}
        onOpenChange={(o) => !o && onClose()}
        isDismissable
        className="modal-overlay"
      >
        <Modal className="modal modal--wide">
          <Dialog className="modal__in" aria-label={t("tree.share_title")}>
            <Heading slot="title">{t("tree.share_title")}</Heading>
            <p className="muted">{t("tree.share_hint")}</p>
            {sharing && <ExportForm refs={sharing} share />}
          </Dialog>
        </Modal>
      </ModalOverlay>
      <MoveDialog
        current={null}
        open={moving != null}
        onClose={onClose}
        onMove={(to, name) => {
          if (moving) moveMany(moving, to, t("folders.moved_many", { count: moving.length, to: name }));
          treePick.clear();
        }}
      />
    </>
  );
}

function FolderItem({
  f,
  current,
  edit,
  setEdit,
  error,
  onMenu,
}: {
  f: Folder;
  current: string | null;
  edit: Edit | null;
  setEdit: (e: Edit | null) => void;
  error: { path: string; text: string } | null;
  onMenu: (m: MenuAt) => void;
}) {
  const { t } = useTranslation();
  const [open, toggle] = useOpen(f.path);
  const qc = useQueryClient();
  const ref = useRef<HTMLLIElement>(null);
  const { dropProps, isDropTarget } = useRecordDrop(ref, f.path, f.name);
  const mode = edit?.path === f.path ? edit.mode : "idle";
  const listed = current === f.path;
  return (
    <li ref={ref} {...dropProps} data-drop={isDropTarget || undefined}>
      {mode === "rename" ? (
        <NameInput
          initial={f.name}
          label={t("folders.rename")}
          onCancel={() => setEdit(null)}
          onDone={async (name) => {
            const to = f.path.includes("/") ? `${f.path.slice(0, f.path.lastIndexOf("/"))}/${name}` : name;
            try {
              await folderApi.rename(f.path, to);
              setEdit(null);
              for (const k of ["folders", "records"]) qc.invalidateQueries({ queryKey: [k] });
              return null;
            } catch (e) {
              return problemText(e);
            }
          }}
        />
      ) : (
        <button
          type="button"
          className="frow-btn ftoggle"
          aria-expanded={open}
          data-listed={listed || undefined}
          onClick={toggle}
          onContextMenu={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onMenu({ at: pointOf(e), on: "folder", f });
          }}
        >
          <Icon name="chev" size={12} className="ftoggle__chev" />
          <Icon name="folder" />
          <span>{f.name}</span>
          <span className="n">{f.count}</span>
        </button>
      )}
      {error?.path === f.path && (
        <span className="fielderr" role="alert">
          {error.text}
        </span>
      )}
      {(f.children.length > 0 || mode === "child") && (
        <ul>
          {f.children.map((c) => (
            <FolderItem
              key={c.path}
              f={c}
              current={current}
              edit={edit}
              setEdit={setEdit}
              error={error}
              onMenu={onMenu}
            />
          ))}
          {mode === "child" && (
            <li>
              <NewFolder parent={f.path} onClose={() => setEdit(null)} />
            </li>
          )}
        </ul>
      )}
      {open && <TreeRecords folder={f.path} onMenu={onMenu} />}
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

/** Папки деревом, как в Obsidian (разд. 5.11): раздел раскрывается в панели и показывает свои записи, записи без
 * папки стоят в корне под папками; запись открывается в рабочей области. Действия — правой кнопкой: новая
 * заметка, папка, список, переименование, удаление; запись переносится перетаскиванием. */
export function Folders() {
  const { t } = useTranslation();
  const tree = useQuery(q.folders());
  const session = useQuery(q.session());
  const person = !!session.data?.agent.startsWith("person:");
  const search = useSearch({ strict: false }) as { folder?: string };
  const current = search.folder ?? null;
  const navigate = useNavigate();
  const qc = useQueryClient();
  const menuOpen = useMenuOpen();
  const href = useRouterState({ select: (st) => st.location.href });
  // biome-ignore lint/correctness/useExhaustiveDependencies: закрываем меню при каждом переходе
  useEffect(() => menuStore.set(false), [href]);
  const [menu, setMenu] = useState<MenuAt | null>(null);
  const [edit, setEdit] = useState<Edit | null>(null);
  const [error, setError] = useState<{ path: string; text: string } | null>(null);
  const [sharing, setSharing] = useState<string[] | null>(null);
  const [moving, setMoving] = useState<string[] | null>(null);
  const area = useRef<HTMLDivElement>(null);
  const { dropProps, isDropTarget } = useRecordDrop(area, null, t("folders.unfiled"));
  const base = useQuery(q.base());
  const count = useTreePick().size;
  const items = (() => {
    if (!menu) return [];
    if (menu.on === "records")
      return [
        { id: "share", label: t("tree.share"), meta: count },
        { id: "move", label: t("tree.move") },
        "-" as const,
        { id: "clear", label: t("tree.clear") },
      ];
    if (menu.on === "folder")
      return [
        { id: "note", label: t("folders.new_note") },
        ...(person ? [{ id: "child", label: t("folders.new_inside") }] : []),
        { id: "list", label: t("folders.open_list") },
        ...(person ? ["-" as const, { id: "rename", label: t("folders.rename") }] : []),
        ...(person ? [{ id: "delete", label: t("folders.delete") }] : []),
      ];
    return [
      { id: "note", label: t("folders.new_note") },
      ...(person ? [{ id: "child", label: t("folders.new") }] : []),
      "-" as const,
      { id: "all", label: t("folders.all_list") },
      { id: "import", label: t("tree.import") },
      { id: "collapse", label: t("folders.collapse"), meta: "⇧C" },
    ];
  })();
  const onAction = async (k: string) => {
    if (!menu) return;
    const f = menu.on === "folder" ? menu.f : null;
    setError(null);
    if (menu.on === "records") {
      const refs = [...treePick.get()];
      if (k === "share") setSharing(refs);
      if (k === "move") setMoving(refs);
      if (k === "clear") treePick.clear();
      return;
    }
    if (k === "note") navigate({ to: "/new", search: { folder: f?.path ?? "-" } as never });
    if (k === "child") setEdit({ path: f?.path ?? null, mode: "child" });
    if (k === "rename" && f) setEdit({ path: f.path, mode: "rename" });
    if (k === "list") navigate({ to: "/records", search: { folder: f?.path } as never });
    if (k === "all") navigate({ to: "/records" });
    if (k === "import") navigate({ to: "/bundles", search: { tab: "import" } as never });
    if (k === "collapse") collapseAll();
    if (k === "delete" && f) {
      try {
        await folderApi.remove(f.path);
        for (const key of ["folders", "records"]) qc.invalidateQueries({ queryKey: [key] });
      } catch (e) {
        setError({ path: f.path, text: problemText(e) });
      }
    }
  };
  const label =
    menu?.on === "folder"
      ? t("folders.menu", { name: menu.f.name })
      : menu?.on === "records"
        ? t("tree.menu", { count })
        : t("folders.root_menu");
  return (
    <nav id="folders" className="folders" aria-label={t("folders.title")} data-open={menuOpen || undefined}>
      {/* дерево, как в Obsidian: папки, под ними — записи без папки; правая кнопка по пустому месту — новая
          заметка, папка, импорт; перетаскивание сюда — в корень */}
      {/* biome-ignore lint/a11y/noStaticElementInteractions: правая кнопка по пустому месту — сокращение мышью; с клавиатуры то же — клавишей меню (Shift+F10) */}
      <div
        ref={area}
        {...dropProps}
        className="ftree"
        data-drop={isDropTarget || undefined}
        onContextMenu={(e) => {
          e.preventDefault();
          setMenu({ at: pointOf(e), on: "root" });
        }}
      >
        <ul>
          {tree.data?.folders.map((f) => (
            <FolderItem
              key={f.path}
              f={f}
              current={current}
              edit={edit}
              setEdit={setEdit}
              error={error}
              onMenu={setMenu}
            />
          ))}
          {edit?.mode === "child" && edit.path === null && (
            <li>
              <NewFolder parent={null} onClose={() => setEdit(null)} />
            </li>
          )}
        </ul>
        <TreeRecords folder="-" onMenu={setMenu} />
      </div>
      <div className="folders__actions">
        {/* импорт подборки, которую прислали: заметки вместе с исходными файлами */}
        <Link className="newf" to="/bundles" search={{ tab: "import" } as never}>
          <Icon name="inbox" size={12} />
          {t("tree.import")}
        </Link>
      </div>
      <PointMenu
        at={menu?.at ?? null}
        label={label}
        items={items}
        onAction={onAction}
        onClose={() => setMenu(null)}
      />
      <TreeDialogs
        sharing={sharing}
        moving={moving}
        onClose={() => {
          setSharing(null);
          setMoving(null);
        }}
      />
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
