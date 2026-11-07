import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { q } from "../../api/queries";
import type { components } from "../../api/schema";
import { Icon } from "../../ui/icons";
import { KindChip } from "../../ui/KindChip";
import { StatusText } from "../../ui/StatusText";
import { text } from "../record/doc";
import { kindLabel, recordPath } from "../records/RecordList";
import type { Star } from "./model";

type Status = components["schemas"]["Status"];

/** Панель выбранной звезды: вид, статус, заголовок, одна строка; «Открыть», «Окрестность», «Заметка». */
export function StarCard({
  star,
  onAround,
  floating = false,
}: {
  star: Star;
  onAround?: (id: string) => void;
  floating?: boolean;
}) {
  const { t, i18n } = useTranslation();
  // временная звезда (@new-…) ещё не записана — читать нечего
  const rec = useQuery({ ...q.record(star.id), retry: false, enabled: !star.id.startsWith("@") });
  const vocab = useQuery(q.vocab(star.object ? "entity_class" : "kind"));
  const p = rec.data?.payload as { summary_plain?: { ru: string }; description?: { ru: string } } | undefined;
  const line = text(p?.summary_plain ?? p?.description, i18n.language);
  return (
    <section className="starcard" data-floating={floating || undefined} aria-label={t("sky.selected")}>
      <div className="starcard__top">
        <KindChip
          kind={star.kind}
          target={star.object ? "entity" : "atom"}
          label={kindLabel(vocab.data, star.kind, i18n.language)}
        />
        <StatusText status={star.status as Status} />
      </div>
      <h3>{star.label}</h3>
      {line && <p className="muted">{line}</p>}
      <p className="muted starcard__meta">{t("sky.links", { count: star.degree })}</p>
      <div className="starcard__acts">
        <Link className="pillbtn" {...recordPath(star.id)}>
          {t("sky.open")}
        </Link>
        {onAround && (
          <button type="button" className="navlink" onClick={() => onAround(star.id)}>
            <Icon name="stack" />
            {t("sky.around")}
          </button>
        )}
        <Link className="navlink" to="/new" search={{ about: star.id } as never}>
          <Icon name="plus" />
          {t("sky.note")}
        </Link>
      </div>
    </section>
  );
}
