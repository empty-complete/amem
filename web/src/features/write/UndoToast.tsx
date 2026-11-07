import { useTranslation } from "react-i18next";
import { undo, usePending } from "./submitQueue";
import "./write.css";

/** «Записано: вопрос · Отменить» — одна строка на пакет, пока идёт окно отмены. */
export function UndoToasts() {
  const { t } = useTranslation();
  const pending = usePending();
  return (
    <div className="toasts" role="status" aria-live="polite">
      {pending.map((p) => (
        <div key={p.id} className="toast">
          <span>{t("write.saved", { what: p.what })}</span>
          <button type="button" onClick={() => undo(p.id)}>
            {t("write.undo")}
          </button>
        </div>
      ))}
    </div>
  );
}
