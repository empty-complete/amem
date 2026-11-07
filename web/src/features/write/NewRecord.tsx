import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { q } from "../../api/queries";
import { RegionState } from "../../ui/RegionState";
import { recordPath } from "../records/RecordList";
import { draftKey, loadDraft, saveDraft } from "./drafts";
import type { FieldIssues } from "./proposal";

/** Замечания проверки, пришедшие после окна отмены: человек уже ушёл со страницы — вернём его в /new с ними. */
let rejected: { key: string; issues: FieldIssues } | null = null;

import { emptyDraft, NEW_REF } from "./proposal";
import { RecordEditor } from "./RecordEditor";
import "../record/record.css";

const peekIssues = (key: string) => (rejected?.key === key ? rejected.issues : null);

/** /new — тот же экран записи, открытый в правке: «О чём» из места, вид — из адреса или заметка (разд. 5.9). */
export function NewRecord({
  about,
  kind,
  related,
  issue,
}: {
  about?: string;
  kind?: string;
  related?: string;
  issue?: string;
}) {
  const { t } = useTranslation();
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
  const aboutLabel = (aboutRec.data?.payload as { label?: { ru: string } } | undefined)?.label?.ru;
  // после записи — к тому, о чём запись (или на главную), а не «назад»: назад может увести из приложения
  const back = () => (about ? navigate(recordPath(about)) : navigate({ to: "/" }));
  return (
    <article className="note note--new" aria-label={t("edit.new_title")}>
      <RecordEditor
        initial={initial}
        labels={about && aboutLabel ? { [about]: aboutLabel } : {}}
        draftKey={key}
        extraLinks={related ? [{ src: NEW_REF, dst: related, rel: "see_also" }] : []}
        issues={issuesNow ?? (issue ? { fields: {}, sources: {}, other: [issue] } : null)}
        onQueued={back}
        onCancel={back}
        onRejected={(d, issues) => {
          saveDraft(key, d);
          rejected = { key, issues };
          navigate({ to: "/new", search: { about, kind: d.kind } as never });
        }}
      />
    </article>
  );
}
