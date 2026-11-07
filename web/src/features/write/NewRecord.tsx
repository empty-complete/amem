import { useQuery } from "@tanstack/react-query";
import { useNavigate, useRouter } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { q } from "../../api/queries";
import { RegionState } from "../../ui/RegionState";
import { draftKey, loadDraft } from "./drafts";
import { emptyDraft, NEW_REF } from "./proposal";
import { RecordEditor } from "./RecordEditor";
import "../record/record.css";

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
  const router = useRouter();
  const navigate = useNavigate();
  const key = draftKey("new", about ?? null);
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
  const back = () => (router.history.length > 1 ? router.history.back() : navigate({ to: "/" }));
  return (
    <article className="note note--new" aria-label={t("edit.new_title")}>
      <RecordEditor
        initial={initial}
        labels={about && aboutLabel ? { [about]: aboutLabel } : {}}
        draftKey={key}
        extraLinks={related ? [{ src: NEW_REF, dst: related, rel: "see_also" }] : []}
        issues={issue ? { fields: {}, sources: {}, other: [issue] } : null}
        onQueued={back}
        onCancel={back}
        onRejected={(_, issues) =>
          navigate({
            to: "/new",
            search: {
              about,
              kind,
              issue: [issues.label, ...issues.other].filter(Boolean).join(" "),
            } as never,
          })
        }
      />
    </article>
  );
}
