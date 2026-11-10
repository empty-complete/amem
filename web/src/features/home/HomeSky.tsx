import { ToggleButton, ToggleButtonGroup } from "@heroui/react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { q } from "../../api/queries";
import { RegionState } from "../../ui/RegionState";
import type { Family, Filter } from "../sky/model";
import { buildSky } from "../sky/model";
import { Sky } from "../sky/Sky";
import { StarCard } from "../sky/StarCard";
import "./home.css";

const FAM: Family[] = ["source", "work", "object"];

/** Главная (разд. 5.2): всё созвездие базы — вход; список записей остаётся под «Все записи». */
export function HomeSky({
  families,
  pending,
  center,
  project,
}: {
  families?: string;
  pending: boolean;
  center?: string;
  project?: string;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const base = useQuery(q.base());
  const [selected, setSelected] = useState<string | null>(null);
  const [summary, setSummary] = useState<{ records: number; objects: number; pending: number } | null>(null);
  const fams = useMemo(() => new Set((families?.split(",") ?? []) as Family[]), [families]);
  const filter: Filter = useMemo(() => ({ families: fams, pendingOnly: pending }), [fams, pending]);
  const graph = useQuery(q.graph({ ref: center, depth: 2, project }));
  const star = useMemo(() => {
    if (!selected || !graph.data) return null;
    return buildSky(graph.data).byId.get(selected) ?? null;
  }, [selected, graph.data]);

  const set = (patch: { f?: string; pending?: boolean; center?: string }) =>
    navigate({ to: "/", search: (s: object) => ({ ...s, ...patch }) as never, replace: true });
  const onSummary = useCallback((s: typeof summary) => setSummary(s), []);

  if (graph.data && graph.data.nodes.length === 0 && !center) {
    return (
      <div className="home home--empty">
        <RegionState
          state="empty"
          text={t("home.empty")}
          action={{ label: t("home.write"), onPress: () => navigate({ to: "/new" }) }}
        />
      </div>
    );
  }

  const line = summary
    ? [
        t("home.summary", {
          records: t("home.records", { count: summary.records - summary.objects }),
          objects: t("home.objects", { count: summary.objects }),
        }),
        summary.pending ? t("home.waiting", { count: summary.pending }) : "",
      ]
        .filter(Boolean)
        .join(", ")
    : "";

  return (
    <div className="home">
      <Sky
        height="100%"
        centerRef={center}
        project={project}
        filter={filter}
        card="none"
        selected={selected}
        onSelect={setSelected}
        onSummary={onSummary}
      />
      <div className="home__head">
        <h1>{base.data?.name ?? "amemo"}</h1>
        {line && <p className="home__line">{line}</p>}
        <ToggleButtonGroup
          size="sm"
          selectionMode="multiple"
          selectedKeys={new Set([...fams, ...(pending ? ["pending"] : [])])}
          onSelectionChange={(keys) => {
            const k = [...keys].map(String);
            set({
              f: k.filter((x) => x !== "pending").join(",") || undefined,
              pending: k.includes("pending") || undefined,
            });
          }}
          aria-label={t("home.filters")}
          className="home__filters"
        >
          {[...FAM, "pending"].map((f, i) => (
            <ToggleButton key={f} id={f} className="home__chip" data-family={f}>
              {i > 0 && <ToggleButtonGroup.Separator />}
              <i aria-hidden="true" />
              {t(`home.f_${f}`)}
            </ToggleButton>
          ))}
        </ToggleButtonGroup>
        {center && (
          <button type="button" className="navlink" onClick={() => set({ center: undefined })}>
            {t("sky.all")}
          </button>
        )}
      </div>
      {star && (
        <div className="home__card">
          <StarCard star={star} floating onAround={(id) => set({ center: id })} />
        </div>
      )}
      <div className="home__foot">
        <ul className="legend" aria-label={t("home.legend")}>
          {FAM.map((f) => (
            <li key={f} data-family={f}>
              <i aria-hidden="true" />
              {t(`home.f_${f}`)}
            </li>
          ))}
          <li data-ring="object">
            <i aria-hidden="true" />
            {t("home.l_object")}
          </li>
          <li data-ring="pending">
            <i aria-hidden="true" />
            {t("home.l_pending")}
          </li>
        </ul>
        <span className="home__keys">{t("home.keys")}</span>
        <Link className="navlink" to="/records">
          {t("home.all")}
        </Link>
      </div>
    </div>
  );
}
