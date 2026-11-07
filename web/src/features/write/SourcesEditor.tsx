import { useTranslation } from "react-i18next";
import { Icon } from "../../ui/icons";
import { fileType, placeText } from "../source/SourcePanel";
import type { DraftSource } from "./proposal";

/** «Ближайшее в файле: «…»» из замечания уровня 2 — то, что можно взять цитатой одним нажатием. */
const near = (m?: string) => m?.match(/«([^»]+)»/)?.[1];

/** Источники в правке: карточки с крестиком; «+ Источник» — Task 7 (SourcePicker). */
export function SourcesEditor({
  sources,
  issues,
  onChange,
  onAdd,
}: {
  sources: DraftSource[];
  issues: Record<number, string>;
  onChange: (s: DraftSource[]) => void;
  onAdd?: () => void;
}) {
  const { t, i18n } = useTranslation();
  return (
    <section className="widget" aria-label={t("record.sources")}>
      <h2>{t("record.sources")}</h2>
      <ul className="srcs">
        {sources.map((s, i) => (
          <li
            key={`${s.object}-${JSON.stringify(s.selectors)}`}
            className="src src--edit"
            data-invalid={issues[i] ? true : undefined}
          >
            <span className="ft" aria-hidden="true">
              {fileType({ object_name: s.object_name, media_type: s.media_type ?? undefined }, i18n.language)}
            </span>
            <span className="src__main">
              <span className="name">{s.object_name ?? s.object}</span>
              <span className="place">
                {[placeText(s.selectors, t), t("source.version", { n: s.object_version })]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
              {s.quote && <q>{s.quote}</q>}
              {issues[i] && (
                <span className="fielderr" role="alert">
                  {issues[i]}
                  {near(issues[i]) && (
                    <button
                      type="button"
                      className="addprop"
                      onClick={() =>
                        onChange(sources.map((x, j) => (j === i ? { ...x, quote: near(issues[i]) } : x)))
                      }
                    >
                      {t("pick.take")}
                    </button>
                  )}
                </span>
              )}
            </span>
            <button
              type="button"
              className="iconbtn"
              aria-label={t("edit.remove", { what: s.object_name ?? s.object })}
              onClick={() => onChange(sources.filter((_, j) => j !== i))}
            >
              <Icon name="cross" size={12} />
            </button>
          </li>
        ))}
      </ul>
      {onAdd && (
        <button type="button" className="addprop" onClick={onAdd} aria-label={t("edit.add_source_full")}>
          <Icon name="plus" size={14} />
          {t("edit.add_source")}
        </button>
      )}
    </section>
  );
}
