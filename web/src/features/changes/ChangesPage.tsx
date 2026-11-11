import { ToggleButton, ToggleButtonGroup } from "@heroui/react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { errorText } from "../../api/errors";
import { q } from "../../api/queries";
import { formatTime } from "../../ui/format";
import { RegionState } from "../../ui/RegionState";
import { recordPath } from "../records/RecordList";
import { eventText } from "./event";
import { groupByDay } from "./group";
import "./changes.css";

export type Who = "all" | "person" | "model";
export type Since = "7" | "30" | "ever";

const sinceIso = (s: Since) =>
  s === "ever" ? undefined : new Date(Date.now() - Number(s) * 86_400_000).toISOString();

function Filter<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: (readonly [T, string])[];
  onChange: (v: T) => void;
}) {
  return (
    <ToggleButtonGroup
      size="sm"
      selectionMode="single"
      disallowEmptySelection
      selectedKeys={new Set([value])}
      onSelectionChange={(keys) => {
        const k = [...keys][0];
        if (k != null) onChange(String(k) as T);
      }}
      aria-label={label}
    >
      {options.map(([k, l], i) => (
        <ToggleButton key={k} id={k}>
          {i > 0 && <ToggleButtonGroup.Separator />}
          {l}
        </ToggleButton>
      ))}
    </ToggleButtonGroup>
  );
}

/** Лента изменений базы по дням (разд. 5.8): кто и срок — фильтры в адресе. */
export function ChangesPage({ who = "all", since = "7" }: { who?: Who; since?: Since }) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  // срок округляем до часа, чтобы ключ запроса не менялся на каждом рендере
  const from = useMemo(() => sinceIso(since)?.slice(0, 13).concat(":00:00Z"), [since]);
  const list = useQuery(q.changes({ who, since: from }));
  const me = useQuery(q.session()).data?.agent;
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
        <Filter
          label={t("changes.who")}
          value={who}
          options={(["all", "person", "model"] as const).map((w) => [w, t(`changes.${w}`)])}
          onChange={(v) => set({ who: v })}
        />
        <Filter
          label={t("changes.when")}
          value={since}
          options={[
            ["7", t("changes.d7")],
            ["30", t("changes.d30")],
            ["ever", t("changes.ever")],
          ]}
          onChange={(v) => set({ since: v })}
        />
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
                  <span className="ev__what" data-model={e.agent?.startsWith("model:") || undefined}>
                    {eventText(e, t, i18n.language, me)}
                  </span>
                  {e.ref ? (
                    <Link className="ev__rec" {...recordPath(e.ref)}>
                      {e.label ?? e.ref}
                    </Link>
                  ) : (
                    <span />
                  )}
                </li>
              ))}
            </ol>
          </section>
        ))
      )}
    </section>
  );
}
