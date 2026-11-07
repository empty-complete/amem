import { Button, Dropdown, Label } from "@heroui/react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useRouterState, useSearch } from "@tanstack/react-router";
import { type KeyboardEvent, useRef, useState } from "react";
import { type DropItem, useDrop } from "react-aria";
import { useTranslation } from "react-i18next";
import { ApiError } from "../../api/errors";
import { folderApi } from "../../api/folders";
import { q } from "../../api/queries";
import type { components } from "../../api/schema";
import { useMoveRecord } from "../../features/write/move";
import { Icon, type IconName } from "../../ui/icons";

type Folder = components["schemas"]["Folder"];
const TOP_ICON: Record<string, IconName> = { Архив: "archive" };
export const RECORD_MIME = "application/x-amem-ref";

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

function FolderItem({ f, current, person }: { f: Folder; current: string | null; person: boolean }) {
  const { t } = useTranslation();
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
        <span className="frow">
          <Link
            to="/records"
            search={{ folder: f.path }}
            aria-current={current === f.path ? "page" : undefined}
          >
            <Icon name={TOP_ICON[f.path] ?? "folder"} />
            <span>{f.name}</span>
            <span className="n">{f.count}</span>
          </Link>
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
        </span>
      )}
      {err && (
        <span className="fielderr" role="alert">
          {err}
        </span>
      )}
      {(f.children.length > 0 || mode === "child") && (
        <ul>
          {f.children.map((c) => (
            <FolderItem key={c.path} f={c} current={current} person={person} />
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

/** Папки, как в Obsidian (разд. 5.11): человек создаёт, переименовывает и удаляет пустые; запись переносится перетаскиванием. */
export function Folders() {
  const { t } = useTranslation();
  const tree = useQuery(q.folders());
  const session = useQuery(q.session());
  const person = !!session.data?.agent.startsWith("person:");
  const search = useSearch({ strict: false }) as { folder?: string };
  const current = search.folder ?? null;
  const onRecords = useRouterState({ select: (st) => st.location.pathname === "/records" });
  const [adding, setAdding] = useState(false);
  const move = useMoveRecord();
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
    <nav className="folders" aria-label={t("folders.title")}>
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
          <Link to="/records" search={{}} aria-current={current === null && onRecords ? "page" : undefined}>
            <Icon name="stack" />
            <span>{t("folders.all")}</span>
            <span className="n">{tree.data?.total ?? ""}</span>
          </Link>
        </li>
        <li ref={unfiled} {...dropProps} data-drop={isDropTarget || undefined}>
          <Link to="/records" search={{ folder: "-" }} aria-current={current === "-" ? "page" : undefined}>
            <Icon name="inbox" />
            <span>{t("folders.unfiled")}</span>
            <span className="n">{tree.data?.unfiled ?? ""}</span>
          </Link>
        </li>
      </ul>
      {person && (
        <button type="button" className="newf" onClick={() => setAdding(true)}>
          <Icon name="plus" size={12} />
          {t("folders.new")}
        </button>
      )}
    </nav>
  );
}
