import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { q } from "../../api/queries";
import { RecordRow } from "../records/RecordList";
import { infer } from "../write/infer";
import { emptyDraft, toProposal } from "../write/proposal";
import { usePending } from "../write/submitQueue";
import { useSubmit } from "../write/useSubmit";

const KINDS = new Set(["note", "decision", "question", "lesson"]);

/** «Заметки и решения» у объекта: последняя строка — «Добавить заметку», как новая строка в Напоминаниях. */
export function Notes({ entityRef }: { entityRef: string }) {
  const { t } = useTranslation();
  const list = useQuery(q.about(entityRef));
  const vocab = useQuery(q.vocab("kind"));
  const templates = useQuery(q.templates("atom"));
  const pending = usePending().filter((p) => p.about.includes(entityRef) && KINDS.has(p.kind));
  const submit = useSubmit();
  const [text, setText] = useState("");
  const items = (list.data?.items ?? []).filter((r) => KINDS.has(r.kind_or_class));
  const add = () => {
    const i = infer(text, { properties: [] });
    if (!i.label) return;
    const kind = i.kind === "parameter" ? "note" : i.kind;
    const tpl = templates.data?.find((x) => x.code === kind);
    const d = {
      ...emptyDraft(kind),
      label: i.label,
      body: i.body,
      values: { about: [entityRef], tags: i.tags },
    };
    submit(
      { proposals: [toProposal(d, tpl).proposal] },
      { label: i.label, what: (tpl?.label.ru ?? kind).toLowerCase(), kind, about: [entityRef] },
    );
    setText("");
  };
  return (
    <section className="notes" aria-labelledby="notes-title">
      <h2 id="notes-title">{t("card.notes")}</h2>
      <ul className="rows">
        {items.map((r) => (
          <RecordRow key={r.ref} r={r} vocab={vocab.data} />
        ))}
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
