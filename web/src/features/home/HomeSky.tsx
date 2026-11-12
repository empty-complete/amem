import { ToggleButton, ToggleButtonGroup } from "@heroui/react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { q } from "../../api/queries";
import type { components } from "../../api/schema";
import { Icon } from "../../ui/icons";
import { PillSelect } from "../../ui/PillSelect";
import { RegionState } from "../../ui/RegionState";
import { kindLabel } from "../records/RecordList";
import "../records/records.css";
import type { Family, Filter } from "../sky/model";
import { buildSky } from "../sky/model";
import { hasScope, type SkyScope, savedScope, saveScope } from "../sky/prefs";
import { Sky } from "../sky/Sky";
import { StarCard } from "../sky/StarCard";
import "./home.css";

const FAM: Family[] = ["source", "work", "object"];

type Folder = components["schemas"]["Folder"];
const flatFolders = (fs: Folder[], depth = 0): { path: string; name: string; depth: number }[] =>
  fs.flatMap((f) => [{ path: f.path, name: f.name, depth }, ...flatFolders(f.children, depth + 1)]);

/** Главная (разд. 5.2): всё созвездие базы — вход; список записей остаётся под «Все записи». */
export function HomeSky({
  families,
  pending,
  center,
  project,
  scope = {},
}: {
  families?: string;
  pending: boolean;
  center?: string;
  project?: string;
  /** Фильтры обзора из адреса: теги, вид, папка. */
  scope?: SkyScope;
}) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const base = useQuery(q.base());
  const [selected, setSelected] = useState<string | null>(null);
  const [summary, setSummary] = useState<{ records: number; objects: number; pending: number } | null>(null);
  const fams = useMemo(() => new Set((families?.split(",") ?? []) as Family[]), [families]);
  const filter: Filter = useMemo(() => ({ families: fams, pendingOnly: pending }), [fams, pending]);
  const kinds = useQuery(q.vocab("kind"));
  const classes = useQuery(q.vocab("entity_class"));
  const tree = useQuery(q.folders());
  const tags = useQuery(q.tags(""));
  // без фильтров в адресе — последний выбор на этом устройстве
  const scoped = hasScope(scope);
  // biome-ignore lint/correctness/useExhaustiveDependencies: один раз при открытии главной
  useEffect(() => {
    const saved = savedScope();
    if (!scoped && !center && hasScope(saved))
      navigate({ to: "/", search: (s: object) => ({ ...s, ...saved }) as never, replace: true });
  }, []);
  const setScope = (next: SkyScope) => {
    const clean: SkyScope = {
      tag: next.tag?.length ? next.tag : undefined,
      kind: next.kind || undefined,
      folder: next.folder || undefined,
    };
    saveScope(clean);
    navigate({ to: "/", search: (s: object) => ({ ...s, ...clean }) as never, replace: true });
  };
  const graph = useQuery(q.graph({ ref: center, depth: 2, project, ...(center ? {} : scope) }));
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
        scope={center ? undefined : scope}
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
        {!center && (
          // фильтры неба — строкой из компактных списков под семьями: пустые места строки пропускают щелчок к звёздам
          // biome-ignore lint/a11y/useSemanticElements: строка фильтров неба, не поля формы
          <div className="home__scope" role="group" aria-label={t("home.scope")}>
            <PillSelect
              className="pillsel--sky"
              label={t("filters.tag")}
              value={scope.tag?.[0] ?? ""}
              onChange={(v) => setScope({ ...scope, tag: v ? [v] : [] })}
            >
              <option value="">{t("home.tag_any")}</option>
              {[...new Set([...(tags.data?.map((x) => x.tag) ?? []), ...(scope.tag ?? [])])].map((tag) => (
                <option key={tag} value={tag}>
                  #{tag}
                </option>
              ))}
            </PillSelect>
            <PillSelect
              className="pillsel--sky"
              label={t("filters.kind")}
              value={scope.kind ?? ""}
              onChange={(v) => setScope({ ...scope, kind: v })}
            >
              <option value="">{t("filters.kind_any")}</option>
              <optgroup label={t("filters.kinds")}>
                {kinds.data?.map((k) => (
                  <option key={k.code} value={k.code}>
                    {kindLabel(kinds.data, k.code, i18n.language)}
                  </option>
                ))}
              </optgroup>
              <optgroup label={t("filters.classes")}>
                {classes.data?.map((k) => (
                  <option key={k.code} value={k.code}>
                    {kindLabel(classes.data, k.code, i18n.language)}
                  </option>
                ))}
              </optgroup>
            </PillSelect>
            <PillSelect
              className="pillsel--sky"
              label={t("home.folder")}
              value={scope.folder ?? ""}
              onChange={(v) => setScope({ ...scope, folder: v })}
            >
              <option value="">{t("home.folder_any")}</option>
              {flatFolders(tree.data?.folders ?? []).map((f) => (
                <option key={f.path} value={f.path}>
                  {"  ".repeat(f.depth)}
                  {f.name}
                </option>
              ))}
              <option value="-">{t("folders.unfiled")}</option>
            </PillSelect>
            {scoped && (
              <button
                type="button"
                className="pillsel pillsel--sky pillsel--reset"
                onClick={() => setScope({})}
              >
                <Icon name="cross" size={12} />
                {t("filters.reset")}
              </button>
            )}
          </div>
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
