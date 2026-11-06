import { Disclosure } from "@heroui/react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { errorText } from "../../api/errors";
import { q } from "../../api/queries";
import type { components } from "../../api/schema";
import { agentName, formatDate, formatTime } from "../../ui/format";
import { KindChip } from "../../ui/KindChip";
import { RegionState } from "../../ui/RegionState";
import { eventText } from "../changes/event";
import { recordPath } from "../records/RecordList";
import { fileType, placeText, VerdictText } from "../source/SourcePanel";

type Source = components["schemas"]["SourceView"];
type Link_ = components["schemas"]["LinkView"];

/** Источники записи карточками; нажатие выбирает источник в панели справа. */
export function SourcesWidget({
  sources,
  active,
  onActive,
}: {
  sources: Source[];
  active: number;
  onActive: (i: number) => void;
}) {
  const { t, i18n } = useTranslation();
  if (!sources.length) return null;
  return (
    <section className="widget" aria-labelledby="w-src">
      <h2 id="w-src">{t("record.sources")}</h2>
      <ul className="srcs">
        {sources.map((s, i) => (
          <li key={`${s.object}-${JSON.stringify(s.selectors)}`}>
            <button type="button" className="src" aria-pressed={i === active} onClick={() => onActive(i)}>
              <span className="ft" aria-hidden="true">
                {fileType(s, i18n.language)}
              </span>
              <span className="src__main">
                <span className="name">{s.object_name ?? s.object}</span>
                <span className="place">
                  {[placeText(s.selectors, t), t("source.version", { n: s.object_version })]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
                {s.quote && <q>{s.quote}</q>}
              </span>
              <span className="st">
                <VerdictText verdict={s.verdict} />
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Связи в обе стороны: «см. также → …», «← подтверждает …». */
export function LinksWidget({ recordRef }: { recordRef: string }) {
  const { t } = useTranslation();
  const links = useQuery(q.links(recordRef));
  const groups: [string, Link_[]][] = [
    [t("record.out"), links.data?.filter((l) => l.direction === "out") ?? []],
    [t("record.in"), links.data?.filter((l) => l.direction === "in") ?? []],
  ];
  return (
    <section className="widget" aria-label={t("record.links")}>
      <h2>{t("record.links")}</h2>
      {links.isPending ? (
        <RegionState state="loading" />
      ) : links.isError ? (
        <RegionState
          state="error"
          message={errorText(links.error, t("region.offline"))}
          retry={() => links.refetch()}
        />
      ) : links.data.length === 0 ? (
        <p className="muted">{t("record.no_links")}</p>
      ) : (
        <div className="rels">
          {groups.map(([dir, ls]) =>
            ls.map((l) => (
              <span className="rel" key={l.id}>
                <span className="r">
                  {l.direction === "in" ? "← " : ""}
                  {t(`record.rel.${l.rel}`, { defaultValue: l.rel })}
                  {l.direction === "out" ? " →" : ""}
                </span>
                <Link {...recordPath(l.other.ref)} title={dir}>
                  {l.other.label}
                </Link>
              </span>
            )),
          )}
        </div>
      )}
    </section>
  );
}

function Lazy({ title, children }: { title: string; children: (open: boolean) => React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <Disclosure className="widget fold" isExpanded={open} onExpandedChange={setOpen}>
      <Disclosure.Heading>
        <Disclosure.Trigger className="fold__trigger">
          {title}
          <Disclosure.Indicator />
        </Disclosure.Trigger>
      </Disclosure.Heading>
      <Disclosure.Content>
        <Disclosure.Body>{children(open)}</Disclosure.Body>
      </Disclosure.Content>
    </Disclosure>
  );
}

export function HistoryList({ recordRef }: { recordRef: string }) {
  const { t, i18n } = useTranslation();
  const h = useQuery(q.history(recordRef));
  if (h.isPending) return <RegionState state="loading" />;
  if (h.isError) return <RegionState state="error" message={errorText(h.error, t("region.offline"))} />;
  if (!h.data.events.length) return <p className="muted">{t("record.no_history")}</p>;
  return (
    <ol className="hist">
      {h.data.events.map((e) => (
        <li key={e.id}>
          <time dateTime={e.at}>
            {formatDate(e.at, i18n.language)}, {formatTime(e.at, i18n.language)}
          </time>
          <span>{eventText(e, t)}</span>
          <span className="muted">{agentName(e.agent, i18n.language)}</span>
        </li>
      ))}
    </ol>
  );
}

function SimilarList({ recordRef }: { recordRef: string }) {
  const { t } = useTranslation();
  const s = useQuery(q.similar(recordRef));
  if (s.isPending) return <RegionState state="loading" />;
  if (s.isError) return <RegionState state="error" message={errorText(s.error, t("region.offline"))} />;
  const items = s.data.items.filter((i) => i.ref !== recordRef);
  if (!items.length) return <p className="muted">{t("record.no_similar")}</p>;
  return (
    <ul className="simil">
      {items.map((i) => (
        <li key={i.ref}>
          <Link {...recordPath(i.ref)}>
            {i.kind && <KindChip kind={i.kind} />}
            <span>{i.label ?? i.snippet}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

export function HistoryWidget({ recordRef }: { recordRef: string }) {
  const { t } = useTranslation();
  return <Lazy title={t("record.history")}>{(open) => open && <HistoryList recordRef={recordRef} />}</Lazy>;
}

export function SimilarWidget({ recordRef }: { recordRef: string }) {
  const { t } = useTranslation();
  return <Lazy title={t("record.similar")}>{(open) => open && <SimilarList recordRef={recordRef} />}</Lazy>;
}
