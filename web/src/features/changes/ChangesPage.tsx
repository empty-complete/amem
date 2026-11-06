import { Tabs } from "@heroui/react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { errorText } from "../../api/errors";
import { q } from "../../api/queries";
import { agentName, formatTime } from "../../ui/format";
import { RegionState } from "../../ui/RegionState";
import { recordPath } from "../records/RecordList";
import { eventText } from "./event";
import { groupByDay } from "./group";
import "./changes.css";

export type Who = "all" | "person" | "model";
export type Since = "7" | "30" | "all";

const sinceIso = (s: Since) =>
  s === "all" ? undefined : new Date(Date.now() - Number(s) * 86_400_000).toISOString();

/** Лента изменений базы по дням (разд. 5.8): кто и срок — фильтры в адресе. */
export function ChangesPage({ who = "all", since = "7" }: { who?: Who; since?: Since }) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  // срок округляем до часа, чтобы ключ запроса не менялся на каждом рендере
  const from = useMemo(() => sinceIso(since)?.slice(0, 13).concat(":00:00Z"), [since]);
  const list = useQuery(q.changes({ who, since: from }));
  const groups = useMemo(
    () =>
      list.data
        ? groupByDay(list.data.events, new Date(), i18n.language, {
            today: t("changes.today"),
            yesterday: t("changes.yesterday"),
          })
        : [],
    [list.data, i18n.language, t],
  );
  const set = (patch: { who?: Who; since?: Since }) =>
    navigate({ to: "/changes", search: (s: object) => ({ ...s, ...patch }) as never, replace: true });

  return (
    <section className="changes" aria-labelledby="ch-title">
      <div className="page-head">
        <h1 id="ch-title">{t("changes.title")}</h1>
      </div>
      <div className="changes__filters">
        <Tabs selectedKey={who} onSelectionChange={(k) => set({ who: k as Who })}>
          <Tabs.ListContainer>
            <Tabs.List aria-label={t("changes.who")}>
              {(["all", "person", "model"] as const).map((w) => (
                <Tabs.Tab key={w} id={w}>
                  {t(`changes.${w}`)}
                  <Tabs.Indicator />
                </Tabs.Tab>
              ))}
            </Tabs.List>
          </Tabs.ListContainer>
        </Tabs>
        <Tabs selectedKey={since} onSelectionChange={(k) => set({ since: k as Since })}>
          <Tabs.ListContainer>
            <Tabs.List aria-label={t("changes.when")}>
              {(
                [
                  ["7", "d7"],
                  ["30", "d30"],
                  ["all", "ever"],
                ] as const
              ).map(([k, l]) => (
                <Tabs.Tab key={k} id={k}>
                  {t(`changes.${l}`)}
                  <Tabs.Indicator />
                </Tabs.Tab>
              ))}
            </Tabs.List>
          </Tabs.ListContainer>
        </Tabs>
      </div>
      {list.isPending ? (
        <RegionState state="loading" />
      ) : list.isError ? (
        <RegionState
          state="error"
          message={errorText(list.error, t("region.offline"))}
          retry={() => list.refetch()}
        />
      ) : groups.length === 0 ? (
        <RegionState state="empty" text={t("changes.empty")} />
      ) : (
        groups.map((g) => (
          <section key={g.key} className="day" aria-label={g.title}>
            <h2>{g.title}</h2>
            <ol>
              {g.events.map((e) => (
                <li key={e.id} className="ev">
                  <time dateTime={e.at}>{formatTime(e.at, i18n.language)}</time>
                  <span className="ev__what">{eventText(e, t)}</span>
                  {e.ref ? (
                    <Link className="ev__rec" {...recordPath(e.ref)}>
                      {e.label ?? e.ref}
                    </Link>
                  ) : (
                    <span />
                  )}
                  <span className="ev__who" data-model={e.agent?.startsWith("model:") || undefined}>
                    {agentName(e.agent, i18n.language)}
                  </span>
                </li>
              ))}
            </ol>
          </section>
        ))
      )}
    </section>
  );
}
