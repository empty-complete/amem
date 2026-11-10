import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { q } from "../../api/queries";
import { RecordRow } from "../records/RecordList";
import { draftKey, loadDraft, saveDraft } from "../write/drafts";
import { infer } from "../write/infer";
import { emptyDraft } from "../write/proposal";
import { usePending } from "../write/submitQueue";

const KINDS = new Set(["note", "decision", "question", "lesson"]);

/** «Заметки и решения» у объекта: последняя строка — «Добавить заметку». Строка — только заголовок: Enter открывает
 * полный редактор с ним, объектом и видом; в базу запись уходит по «Записать». Незаконченное — черновик в списке. */
export function Notes({ entityRef }: { entityRef: string }) {
  const { t } = useTranslation();
  const list = useQuery(q.about(entityRef));
  const vocab = useQuery(q.vocab("kind"));
  const pending = usePending().filter((p) => p.about.includes(entityRef) && KINDS.has(p.kind));
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const key = draftKey("new", entityRef);
  const draft = loadDraft(key);
  const items = (list.data?.items ?? []).filter((r) => KINDS.has(r.kind_or_class));
  const add = () => {
    const i = infer(text, { properties: [] });
    if (!i.label) return;
    const kind = i.kind === "parameter" ? "note" : i.kind;
    saveDraft(key, {
      ...emptyDraft(kind),
      label: i.label,
      body: i.body,
      values: { about: [entityRef], tags: i.tags },
    });
    setText("");
    navigate({ to: "/new", search: { about: entityRef, kind } as never });
  };
  return (
    <section className="notes" aria-labelledby="notes-title">
      <h2 id="notes-title">{t("card.notes")}</h2>
      <ul className="rows">
        {items.map((r) => (
          <RecordRow key={r.ref} r={r} vocab={vocab.data} />
        ))}
        {draft?.label && !pending.length && (
          <li className="row row--pending">
            <Link className="main" to="/new" search={{ about: entityRef, kind: draft.kind } as never}>
              <span className="ttl">{draft.label}</span>
            </Link>
            <span className="muted">{t("card.unsaved")}</span>
          </li>
        )}
        {pending.map((p) => (
          <li key={p.id} className="row row--pending">
            <span className="main">
              <span className="ttl">{p.label}</span>
            </span>
            <span className="muted">{t("card.saving")}</span>
          </li>
        ))}
        <li className="addrow">
          <input
            className="fld fld--row"
            aria-label={t("card.add_note")}
            placeholder={t("card.add_note")}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.nativeEvent.isComposing) {
                e.preventDefault();
                add();
              }
            }}
          />
        </li>
      </ul>
    </section>
  );
}
