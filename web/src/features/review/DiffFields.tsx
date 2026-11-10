import { useTranslation } from "react-i18next";
import type { FieldChange } from "./diff";
import "./review.css";

/** Изменённые поля по словам: удалённое зачёркнуто, добавленное подчёркнуто (проверка, история записи). */
export function DiffFields({ changes }: { changes: FieldChange[] }) {
  const { t } = useTranslation();
  return (
    <dl className="diff">
      {changes.map((c) => (
        <div key={c.field}>
          <dt>{t(`review.field.${c.field}`, { defaultValue: c.field })}</dt>
          <dd>
            {c.pieces.map((p, i) =>
              p.op === "same" ? (
                // biome-ignore lint/suspicious/noArrayIndexKey: куски сравнения неизменны и упорядочены
                <span key={i}>{p.text}</span>
              ) : p.op === "del" ? (
                // biome-ignore lint/suspicious/noArrayIndexKey: куски сравнения неизменны и упорядочены
                <del key={i}>{p.text}</del>
              ) : (
                // biome-ignore lint/suspicious/noArrayIndexKey: куски сравнения неизменны и упорядочены
                <ins key={i}>{p.text}</ins>
              ),
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}
