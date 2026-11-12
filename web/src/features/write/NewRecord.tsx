import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { q } from "../../api/queries";
import { type LangString, useText } from "../../ui/lang";
import { RegionState } from "../../ui/RegionState";
import { recordPath } from "../records/RecordList";
import { draftKey, loadDraft, saveDraft } from "./drafts";
import type { FieldIssues } from "./proposal";

/** Замечания проверки, пришедшие после окна отмены: человек уже ушёл со страницы — вернём его в /new с ними. */
let rejected: { key: string; issues: FieldIssues } | null = null;

import { newNoteFolder } from "../../app/shell/folderTree";
import { emptyDraft, NEW_REF } from "./proposal";
import { RecordEditor } from "./RecordEditor";
import "../record/record.css";

const peekIssues = (key: string) => (rejected?.key === key ? rejected.issues : null);

/** Хлебные крошки новой заметки, как в Obsidian: папка, куда она ляжет, и «Новая заметка». */
function NewCrumbs({ folder }: { folder: string }) {
  const { t } = useTranslation();
  const parts = folder ? folder.split("/") : [];
  return (
    <div className="note__bar">
      <nav className="crumbs" aria-label={t("edit.new_where")}>
        {parts.length ? (
          parts.map((name, i) => (
            <span key={parts.slice(0, i + 1).join("/")}>
              {i > 0 && <span aria-hidden="true"> / </span>}
              <Link to="/records" search={{ folder: parts.slice(0, i + 1).join("/") } as never}>
                {name}
              </Link>
            </span>
          ))
        ) : (
          <span className="muted">{t("folders.unfiled")}</span>
        )}
        <span aria-hidden="true"> / </span>
        <span aria-current="page">{t("edit.new_title")}</span>
      </nav>
    </div>
  );
}

/** /new — тот же экран записи, открытый в правке: «О чём» из места, вид — из адреса или заметка (разд. 5.9). */
export function NewRecord({
  about,
  kind,
  related,
  issue,
  folder,
}: {
  about?: string;
  kind?: string;
  related?: string;
  issue?: string;
  /** Папка из меню дерева: путь или «-» — корень. */
  folder?: string;
}) {
  const { t } = useTranslation();
  const { text } = useText();
  const navigate = useNavigate();
  const key = draftKey("new", about ?? null);
  const [issuesNow] = useState(() => peekIssues(key));
  // забираем после монтирования: StrictMode зовёт инициализатор дважды
  useEffect(() => {
    if (rejected?.key === key) rejected = null;
  }, [key]);
  const aboutRec = useQuery({ ...q.record(about ?? ""), enabled: !!about });
  const templates = useQuery(q.templates("atom"));
  if ((about && aboutRec.isPending) || templates.isPending) return <RegionState state="loading" />;
  const saved = loadDraft(key);
  const initial = saved ?? emptyDraft(kind ?? "note");
  if (kind) initial.kind = kind;
  const tpl = templates.data?.find((x) => x.code === initial.kind);
  const aboutKey = tpl?.form.find((f) => f.path === "about")?.key;
  if (about && aboutKey && !initial.values[aboutKey]) initial.values[aboutKey] = [about];
  const aboutLabel = text((aboutRec.data?.payload as { label?: LangString } | undefined)?.label) || undefined;
  // после записи — к тому, о чём запись (или на главную), а не «назад»: назад может увести из приложения
  const back = () => (about ? navigate(recordPath(about)) : navigate({ to: "/" }));
  return (
    <article className="note note--new" aria-label={t("edit.new_title")}>
      <NewCrumbs folder={folder === undefined ? newNoteFolder() : folder === "-" ? "" : folder} />
      <RecordEditor
        initial={initial}
        labels={about && aboutLabel ? { [about]: aboutLabel } : {}}
        draftKey={key}
        extraLinks={related ? [{ src: NEW_REF, dst: related, rel: "see_also" }] : []}
        folder={folder === undefined ? undefined : folder === "-" ? "" : folder}
        issues={issuesNow ?? (issue ? { fields: {}, sources: {}, other: [issue] } : null)}
        onQueued={back}
        onCancel={back}
        onRejected={(d, issues) => {
          saveDraft(key, d);
          rejected = { key, issues };
          navigate({ to: "/new", search: { about, kind: d.kind, folder } as never });
        }}
      />
    </article>
  );
}
