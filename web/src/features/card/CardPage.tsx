import { Tabs } from "@heroui/react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { ApiError, errorText } from "../../api/errors";
import { q } from "../../api/queries";
import { formatValue, unitLabel } from "../../ui/format";
import { KindChip } from "../../ui/KindChip";
import { RegionState } from "../../ui/RegionState";
import { text } from "../record/doc";
import { HistoryList } from "../record/Widgets";
import { kindLabel, RecordRow, recordPath } from "../records/RecordList";
import { Sky } from "../sky/Sky";
import { useSubmit } from "../write/useSubmit";
import { CardTable, ExtraValues, type Fill, usePropertyName } from "./CardTable";
import { type Card, ORDER, summarize } from "./card";
import { Notes } from "./Notes";
import "../record/record.css";
import "../records/records.css";
import "./card.css";

function Summary({ card }: { card: Card }) {
  const { t } = useTranslation();
  const name = usePropertyName();
  const s = summarize(card, (f) => name(f.property, f.label));
  const line = [
    t("card.summary", { known: s.parts.known, total: s.total }),
    [
      s.parts.conflict ? t("card.conflicts", { count: s.parts.conflict }) : "",
      s.parts.asked ? t("card.asked_n", { count: s.parts.asked }) : "",
      s.blockers.length ? t("card.blockers", { list: s.blockers.join(", ").toLowerCase() }) : "",
    ]
      .filter(Boolean)
      .join(", "),
  ]
    .filter(Boolean)
    .join(" ")
    .replace(/([^.])$/, "$1.");
  return (
    <div className="fill">
      <div className="fill__bar" role="img" aria-label={line}>
        {ORDER.filter((st) => s.parts[st]).map((st) => (
          <span key={st} data-state={st} style={{ flexGrow: s.parts[st] }} />
        ))}
      </div>
      <p className="fill__line">{line}</p>
    </div>
  );
}

function Atoms({ entityRef }: { entityRef: string }) {
  const { t } = useTranslation();
  const list = useQuery(q.about(entityRef));
  const vocab = useQuery(q.vocab("kind"));
  if (list.isPending) return <RegionState state="loading" />;
  if (list.isError) return <RegionState state="error" message={errorText(list.error, t("region.offline"))} />;
  if (!list.data.items.length) return <RegionState state="empty" text={t("card.no_atoms")} />;
  return (
    <ul className="rows">
      {list.data.items.map((r) => (
        <RecordRow key={r.ref} r={r} vocab={vocab.data} />
      ))}
    </ul>
  );
}

/** Страница объекта (разд. 5.5): путь по part_of, полнота карточки профиля, состояния полей; атомы и история. */
export function CardPage({ entityRef }: { entityRef: string }) {
  const { t, i18n } = useTranslation();
  const rec = useQuery(q.record(entityRef));
  const card = useQuery(q.card(entityRef));
  const classes = useQuery(q.vocab("entity_class"));
  const submit = useSubmit();
  const fill: Fill = {
    value: (f, v) => {
      const label = `${f.label ?? f.property}: ${[v.amount ?? v.value_text, v.unit ? unitLabel(v.unit, i18n.language) : ""].filter((x) => x != null && x !== "").join(" ")}`;
      submit(
        {
          proposals: [
            {
              target: "atom",
              record_id: null,
              payload: {
                kind: "parameter",
                label: { ru: label },
                about: [entityRef],
                basis: "author",
                content: { values: [{ property: f.property, ...v }] },
              },
            },
          ],
        },
        { label, what: t("card.what_value"), kind: "parameter", about: [entityRef], family: "source" },
      );
    },
    unknown: (f) => {
      const label = t("card.question_label", { what: (f.label ?? f.property).toLowerCase() });
      submit(
        {
          proposals: [
            {
              target: "atom",
              record_id: null,
              payload: {
                kind: "question",
                label: { ru: label },
                about: [entityRef],
                basis: "author",
                content: { values: [{ property: f.property, value_state: "unknown" }] },
              },
            },
          ],
        },
        { label, what: t("card.what_question"), kind: "question", about: [entityRef] },
      );
    },
    accept: (f) => {
      const v = (f.default ?? {}) as Record<string, unknown>;
      const label = `${f.label ?? f.property}: ${formatValue(v as never, i18n.language)}`;
      submit(
        {
          proposals: [
            {
              target: "atom",
              record_id: null,
              payload: {
                kind: "parameter",
                label: { ru: label },
                about: [entityRef],
                basis: "default",
                derived_from: [`profile:${card.data?.profile ?? ""}#${f.property}`],
                content: { values: [{ property: f.property, ...v }] },
              },
            },
          ],
        },
        { label, what: t("card.what_default"), kind: "parameter", about: [entityRef], family: "source" },
      );
    },
  };
  if (rec.isPending || card.isPending) return <RegionState state="loading" />;
  // без профиля служба отдаёт карточку с пустыми fields (значения записей — в extra); 404 — сущности нет в карточках
  const profiled = !!card.data?.fields.length;
  const noCard =
    (card.isError && card.error instanceof ApiError && card.error.status === 404) ||
    (!!card.data && !profiled);
  if (rec.isError && (card.isError || !card.data)) {
    return (
      <RegionState
        state="error"
        message={errorText(rec.error, t("region.offline"))}
        retry={() => rec.refetch()}
      />
    );
  }
  const payload = rec.data?.payload as
    | { label?: { ru: string }; entity_class?: string; description?: { ru: string } }
    | undefined;
  const label = payload?.label ? text(payload.label, i18n.language) : (card.data?.entity.label ?? entityRef);
  const cls = payload?.entity_class ?? card.data?.entity.entity_class ?? "";
  const ancestors = card.data?.ancestors ?? rec.data?.ancestors ?? [];
  const desc = payload?.description ? text(payload.description, i18n.language) : "";

  return (
    <div className="entitypage">
      <article className="entity" aria-labelledby="ent-title">
        <div className="note__bar">
          {ancestors.length > 0 && (
            <nav className="crumbs" aria-label={t("record.about")}>
              {ancestors.map((a, i) => (
                <span key={a.ref}>
                  {i > 0 && <span aria-hidden="true"> / </span>}
                  <Link {...recordPath(a.ref)}>{a.label}</Link>
                </span>
              ))}
            </nav>
          )}
        </div>
        <div className="entity__head">
          <h1 id="ent-title" className="title">
            {label}
          </h1>
          {cls && <KindChip kind={cls} target="entity" label={kindLabel(classes.data, cls, i18n.language)} />}
          {card.data?.profile && (
            <span className="muted">{t("card.profile", { name: card.data.profile })}</span>
          )}
        </div>
        {desc && <p className="lede">{desc}</p>}
        {card.data && profiled && <Summary card={card.data} />}
        {card.isError && !noCard && (
          <RegionState
            state="error"
            message={errorText(card.error, t("region.offline"))}
            retry={() => card.refetch()}
          />
        )}
        {noCard && <p className="muted">{t("card.no_profile")}</p>}

        <Tabs defaultSelectedKey={card.data ? "card" : "atoms"}>
          <Tabs.ListContainer>
            <Tabs.List aria-label={label}>
              {card.data && (
                <Tabs.Tab id="card">
                  {t("card.tab_card")}
                  <Tabs.Indicator />
                </Tabs.Tab>
              )}
              <Tabs.Tab id="atoms">
                {t("card.tab_atoms")}
                <Tabs.Indicator />
              </Tabs.Tab>
              <Tabs.Tab id="history">
                {t("card.tab_history")}
                <Tabs.Indicator />
              </Tabs.Tab>
            </Tabs.List>
          </Tabs.ListContainer>
          {card.data && (
            <Tabs.Panel id="card">
              {profiled && <CardTable groups={summarize(card.data).groups} fill={fill} />}
              <ExtraValues items={card.data.extra ?? []} />
              <Notes entityRef={entityRef} />
            </Tabs.Panel>
          )}
          <Tabs.Panel id="atoms">
            <Atoms entityRef={entityRef} />
          </Tabs.Panel>
          <Tabs.Panel id="history">
            <HistoryList recordRef={entityRef} />
          </Tabs.Panel>
        </Tabs>
      </article>
      <aside className="entity__side" aria-label={t("sky.widget")}>
        <Sky centerRef={entityRef} height="var(--entity-sky-h)" />
      </aside>
    </div>
  );
}
