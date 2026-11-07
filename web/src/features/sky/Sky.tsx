import { Button, ToggleButton, ToggleButtonGroup } from "@heroui/react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { type KeyboardEvent, lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { errorText } from "../../api/errors";
import { q } from "../../api/queries";
import { Icon } from "../../ui/icons";
import { RegionState } from "../../ui/RegionState";
import { kindLabel, recordPath } from "../records/RecordList";
import { skyBus } from "./bus";
import { useReducedMotion, useSkyColors } from "./colors";
import { arrowNeighbour, buildSky, dimmed, type Filter } from "./model";
import type { SkyCanvasApi } from "./SkyCanvas";
import { StarCard } from "./StarCard";
import "./sky.css";

const SkyCanvas = lazy(() => import("./SkyCanvas"));
const Sky3D = lazy(() => import("./Sky3D"));

const NO_FILTER: Filter = { families: new Set(), pendingOnly: false };

let gl: boolean | undefined;
/** Есть ли WebGL 2 — проверяется один раз: каждый контекст держит ресурсы видеокарты. */
const webgl = () => {
  if (gl === undefined) {
    try {
      const c = document.createElement("canvas");
      const ctx = c.getContext("webgl2");
      gl = !!ctx;
      ctx?.getExtension("WEBGL_lose_context")?.loseContext();
    } catch {
      gl = false;
    }
  }
  return gl;
};

export interface SkyProps {
  centerRef?: string;
  project?: string;
  depth?: number;
  height: number | string;
  filter?: Filter;
  /** «below» — панель звезды под небом; «none» — её рисует страница (главная). */
  card?: "below" | "none";
  selected?: string | null;
  onSelect?: (id: string | null) => void;
  onAround?: (id: string) => void;
  onSummary?: (s: { records: number; objects: number; pending: number }) => void;
  label?: string;
  showDepth?: boolean;
}

/** Окно неба (разд. 4.4): одно на главной, объекте, записи и в проверке — отличается только центром. */
export function Sky(props: SkyProps) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const [depth, setDepth] = useState(props.depth ?? 2);
  const [own, setOwn] = useState<string | null>(null);
  const selected = props.selected !== undefined ? props.selected : own;
  const select = useCallback(
    (id: string | null) => {
      setOwn(id);
      props.onSelect?.(id);
    },
    [props.onSelect],
  );
  const [full, setFull] = useState(false);
  const [three, setThree] = useState(false);
  const host = useRef<HTMLDivElement>(null);
  const canvas = useRef<SkyCanvasApi>(null);
  const colors = useSkyColors(host);
  const reduced = useReducedMotion();
  const graph = useQuery(q.graph({ ref: props.centerRef, depth, project: props.project }));
  const [extra, setExtra] = useState<
    { star: import("./model").Star; links: { source: string; target: string; rel: string }[] }[]
  >([]);
  // другой центр — новые звёзды прошлого неба не тянем
  // biome-ignore lint/correctness/useExhaustiveDependencies: сброс именно при смене центра или проекта
  useEffect(() => setExtra([]), [props.centerRef, props.project]);
  const sky = useMemo(() => {
    if (!graph.data) return null;
    const g = graph.data;
    // новые звёзды из события «запись создана» вливаются в те же данные
    const nodes = [
      ...g.nodes,
      ...extra.map((x) => ({
        ref: x.star.id,
        label: x.star.label,
        kind_or_class: x.star.kind,
        family: x.star.family,
        status: x.star.status as never,
        pending: x.star.pending,
        degree: x.star.degree,
        depth: 1,
      })),
    ];
    const edges = [
      ...g.edges,
      ...extra.flatMap((x) => x.links.map((l) => ({ src: l.source, dst: l.target, rel: l.rel }))),
    ];
    return buildSky({ ...g, nodes, edges, total: g.total + extra.length });
  }, [graph.data, extra]);
  const dim = useMemo(
    () => (sky ? dimmed(sky, props.filter ?? NO_FILTER) : new Set<string>()),
    [sky, props.filter],
  );
  const star = selected ? sky?.byId.get(selected) : undefined;
  const vocab = useQuery(q.vocab(star?.object ? "entity_class" : "kind"));

  useEffect(() => {
    if (!sky || !props.onSummary) return;
    const objects = sky.nodes.filter((n) => n.object).length;
    props.onSummary({ records: sky.total, objects, pending: sky.nodes.filter((n) => n.pending).length });
  }, [sky, props.onSummary]);

  // вспышка новой звезды по событию части D
  useEffect(
    () =>
      skyBus.on((d) => {
        if (!sky) return;
        if (!d.links.some((l) => sky.byId.has(l.source) || sky.byId.has(l.target))) return;
        setExtra((x) => [...x, d]);
        select(d.star.id);
      }),
    [sky, select],
  );

  // ручка для e2e — только в сборке с моками
  useEffect(() => {
    if (!import.meta.env.VITE_MOCK || !sky) return;
    (window as unknown as { __amemSky?: object }).__amemSky = {
      screen: (id: string) => canvas.current?.screen(id) ?? null,
      count: () => sky.nodes.length,
      dim: () => [...dim],
      emit: skyBus.emit,
    };
  }, [sky, dim]);

  const open = useCallback((id: string) => navigate(recordPath(id)), [navigate]);

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!sky || e.target !== e.currentTarget || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key.startsWith("Arrow")) {
      e.preventDefault();
      const from = selected ?? sky.center ?? sky.nodes.find((n) => n.object)?.id ?? sky.nodes[0]?.id ?? null;
      if (!from) return;
      if (!selected) return select(from);
      const pos = canvas.current?.positions() ?? new Map();
      const next = arrowNeighbour(from, sky.neighbours.get(from) ?? new Set(), pos, e.key);
      if (next) {
        select(next);
        canvas.current?.focus(next);
      }
    } else if (e.key === "Enter" && selected) {
      e.preventDefault();
      open(selected);
    } else if (e.key === "Escape") {
      if (full) setFull(false);
      else select(null);
    } else if (e.code === "Digit1" || e.code === "Digit2" || e.code === "Digit3") {
      setDepth(Number(e.code.slice(-1)));
    } else if (e.code === "KeyN" && selected) {
      e.preventDefault();
      e.stopPropagation();
      navigate({ to: "/new", search: { about: selected } as never });
    } else if (e.code === "KeyF") {
      setFull((f) => !f);
    }
  };

  const announce = star
    ? t("sky.announce", {
        kind: kindLabel(vocab.data, star.kind, i18n.language),
        label: star.label,
        status: star.pending ? t("sky.pending") : t(`status.${star.status}`),
        degree: star.degree,
      })
    : "";

  const body = graph.isPending ? (
    <div className="sky__skeleton" role="status" aria-label={t("region.loading")} />
  ) : graph.isError ? (
    <div className="sky__msg">
      <RegionState
        state="error"
        message={errorText(graph.error, t("region.offline"))}
        retry={() => graph.refetch()}
      />
    </div>
  ) : !sky?.nodes.length ? (
    <p className="sky__msg sky__empty">{t("sky.empty")}</p>
  ) : !colors ? null : (
    <Suspense fallback={<div className="sky__skeleton" />}>
      {three ? (
        <Sky3D
          sky={sky}
          selected={selected}
          dim={dim}
          colors={colors}
          reducedMotion={reduced}
          onSelect={select}
          onOpen={open}
        />
      ) : (
        <SkyCanvas
          ref={canvas}
          sky={sky}
          selected={selected}
          dim={dim}
          colors={colors}
          reducedMotion={reduced}
          onSelect={select}
          onOpen={open}
        />
      )}
    </Suspense>
  );

  return (
    <div className="skywin" data-full={full || undefined}>
      <div
        ref={host}
        className="sky"
        style={{ height: full ? undefined : props.height }}
        role="application"
        aria-roledescription={t("sky.role")}
        aria-label={
          props.label ?? t("sky.label", { stars: sky?.nodes.length ?? 0, links: sky?.links.length ?? 0 })
        }
        // biome-ignore lint/a11y/noNoninteractiveTabindex: небо — приложение внутри страницы, управляется с клавиатуры
        tabIndex={0}
        onKeyDown={onKey}
      >
        {body}
        <div className="sky__bar">
          {(props.centerRef || props.showDepth) && (
            <ToggleButtonGroup
              size="sm"
              selectionMode="single"
              disallowEmptySelection
              selectedKeys={new Set([String(depth)])}
              onSelectionChange={(k) => setDepth(Number([...k][0] ?? 2))}
              aria-label={t("sky.depth")}
              className="sky__depth"
            >
              {["1", "2", "3"].map((d, i) => (
                <ToggleButton key={d} id={d} aria-label={`${t("sky.depth")} ${d}`}>
                  {i > 0 && <ToggleButtonGroup.Separator />}
                  {d}
                </ToggleButton>
              ))}
            </ToggleButtonGroup>
          )}
          <Button
            size="sm"
            variant="ghost"
            className="sky__btn"
            aria-pressed={three}
            isDisabled={!three && !webgl()}
            aria-label={webgl() ? t("sky.three") : t("sky.three_off")}
            onPress={() => setThree((x) => !x)}
          >
            3D
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="sky__btn"
            onPress={() => canvas.current?.fit()}
            aria-label={t("sky.fit")}
          >
            <Icon name="search" />
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="sky__btn"
            aria-pressed={full}
            onPress={() => setFull((f) => !f)}
            aria-label={full ? t("sky.close") : t("sky.full")}
          >
            <Icon name={full ? "cross" : "external"} />
          </Button>
        </div>
        {sky?.truncated && (
          <p className="sky__note">{t("sky.truncated", { shown: sky.nodes.length, total: sky.total })}</p>
        )}
      </div>
      <span className="sr-only" aria-live="polite">
        {announce}
      </span>
      {props.card !== "none" && star && <StarCard star={star} onAround={props.onAround} />}
    </div>
  );
}
