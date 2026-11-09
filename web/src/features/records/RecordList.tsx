import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useDrag } from "react-aria";
import { useTranslation } from "react-i18next";
import { errorText } from "../../api/errors";
import { q } from "../../api/queries";
import type { components } from "../../api/schema";
import { RECORD_MIME } from "../../app/shell/Folders";
import { KindChip } from "../../ui/KindChip";
import { RegionState } from "../../ui/RegionState";
import { RelativeTime } from "../../ui/RelativeTime";
import { StatusText } from "../../ui/StatusText";
import "./records.css";

type Summary = components["schemas"]["RecordSummary"];
type Vocab = components["schemas"]["VocabEntry"][];

export function recordPath(ref: string) {
  return ref.startsWith("ent:")
    ? ({ to: "/entity/$ref", params: { ref } } as const)
    : ({ to: "/atom/$ref", params: { ref } } as const);
}

/** Подпись вида или класса словами, с заглавной буквы: в словарях ядра подписи строчные («факт»).
 * Нет английской — русская; нет в словаре — код как есть. */
export function kindLabel(vocab: Vocab | undefined, code: string, lang: string) {
  const v = vocab?.find((x) => x.code === code);
  const text = lang.startsWith("en") ? (v?.label.en ?? v?.label.ru) : v?.label.ru;
  return text ? text.charAt(0).toLocaleUpperCase(lang) + text.slice(1) : code;
}

export function RecordRow({ r, vocab, classes }: { r: Summary; vocab?: Vocab; classes?: Vocab }) {
  const { i18n } = useTranslation();
  // строку можно перетащить на папку слева (React Aria: мышь, касание, клавиатура и чтецы)
  const { dragProps, isDragging } = useDrag({
    getItems: () => [{ [RECORD_MIME]: r.ref, "text/plain": r.label }],
  });
  return (
    <li {...dragProps} data-dragging={isDragging || undefined}>
      <Link className="row" {...recordPath(r.ref)}>
        <span className="main">
          <span className="line1">
            <KindChip
              kind={r.kind_or_class}
              target={r.target}
              label={kindLabel(r.target === "entity" ? classes : vocab, r.kind_or_class, i18n.language)}
            />
            <span className="ttl">{r.label}</span>
          </span>
          <span className="line2">
            {r.about?.map((a) => (
              <span key={a.ref}>{a.label}</span>
            ))}
            {r.folder && <span>{r.folder}</span>}
          </span>
        </span>
        <span className="side">
          <StatusText status={r.status} />
          <RelativeTime at={r.recorded_at} />
        </span>
      </Link>
    </li>
  );
}

/** «Все записи» или содержимое папки; папка — scope.folder записи. */
export function RecordList({ folder, title }: { folder: string | null; title: string }) {
  const { t } = useTranslation();
  const list = useQuery(q.records(folder));
  const vocab = useQuery(q.vocab("kind"));
  const classes = useQuery(q.vocab("entity_class"));
  return (
    <section aria-labelledby="records-title">
      <div className="page-head">
        <h1 id="records-title">{title}</h1>
        {list.data && (
          <span className="count">
            {t("records.count", { count: list.data.total ?? list.data.items.length })}
          </span>
        )}
      </div>
      {list.isPending ? (
        <RegionState state="loading" />
      ) : list.isError ? (
        <RegionState
          state="error"
          message={errorText(list.error, t("region.offline"))}
          retry={() => list.refetch()}
        />
      ) : list.data.items.length === 0 ? (
        <RegionState state="empty" text={t("records.empty")} />
      ) : (
        <ul className="rows">
          {list.data.items.map((r) => (
            <RecordRow key={r.ref} r={r} vocab={vocab.data} classes={classes.data} />
          ))}
        </ul>
      )}
    </section>
  );
}
