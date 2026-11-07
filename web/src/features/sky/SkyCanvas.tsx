// Холст неба на force-graph (canvas 2D, d3-force). Модуль грузится лениво и не входит в первую загрузку.
import ForceGraph from "force-graph";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import type { SkyColors } from "./colors";
import { labelOrder, placeLabels, type Sky, type Star, visibleLabels } from "./model";

type N = Star & { x?: number; y?: number; vx?: number; vy?: number; fx?: number; fy?: number };
type L = { source: string | N; target: string | N; rel: string };

export interface SkyCanvasApi {
  fit: () => void;
  focus: (id: string) => void;
  positions: () => Map<string, { x: number; y: number }>;
  screen: (id: string) => { x: number; y: number } | null;
}

export interface SkyCanvasProps {
  sky: Sky;
  selected: string | null;
  dim: Set<string>;
  colors: SkyColors;
  reducedMotion: boolean;
  onSelect: (id: string | null) => void;
  onOpen: (id: string) => void;
  onHover?: (id: string | null) => void;
}

const idOf = (x: string | N) => (typeof x === "string" ? x : x.id);

const SkyCanvas = forwardRef<SkyCanvasApi, SkyCanvasProps>(function SkyCanvas(props, ref) {
  const box = useRef<HTMLDivElement>(null);
  const fg = useRef<ForceGraph<N, L> | null>(null);
  const live = useRef(props);
  live.current = props;
  const nodes = useRef(new Map<string, N>());
  const flashes = useRef(new Map<string, number>());
  const needFit = useRef(true);
  const touched = useRef(false);

  // один экземпляр force-graph на окно
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const g = new ForceGraph<N, L>(el);
    fg.current = g;
    let lastClick = { id: "", at: 0 };
    let lastBg = 0;
    g.backgroundColor("rgba(0,0,0,0)")
      .nodeId("id")
      // подсказка при наведении — только там, где подписи на небе нет
      .nodeLabel((n) => (visibleLabels(live.current.sky, live.current.selected).has(n.id) ? "" : n.label))
      .nodeRelSize(1)
      .nodeVal((n) => n.r * n.r)
      .linkSource("source")
      .linkTarget("target")
      .cooldownTime(1600)
      .d3VelocityDecay(0.35)
      .minZoom(0.3)
      .maxZoom(8)
      .nodeCanvasObject((n, ctx, scale) => drawStar(n, ctx, scale, live.current, flashes.current))
      .nodePointerAreaPaint((n, color, ctx) => {
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(n.x ?? 0, n.y ?? 0, n.r + 4, 0, Math.PI * 2);
        ctx.fill();
      })
      .linkColor((l) => {
        const p = live.current;
        const s = idOf(l.source);
        const t = idOf(l.target);
        if (p.dim.has(s) || p.dim.has(t)) return withAlpha(p.colors.muted, 0.08);
        if (p.selected && (s === p.selected || t === p.selected)) return withAlpha(p.colors.ink, 0.75);
        return withAlpha(p.colors.muted, p.selected ? 0.18 : 0.38);
      })
      .linkWidth((l) => {
        const p = live.current;
        return p.selected && (idOf(l.source) === p.selected || idOf(l.target) === p.selected) ? 1.6 : 0.8;
      })
      .onNodeClick((n) => {
        const now = performance.now();
        if (lastClick.id === n.id && now - lastClick.at < 320) live.current.onOpen(n.id);
        else live.current.onSelect(n.id);
        lastClick = { id: n.id, at: now };
      })
      .onNodeHover((n) => {
        el.style.cursor = n ? "pointer" : "grab";
        live.current.onHover?.(n?.id ?? null);
      })
      .onBackgroundClick(() => {
        const now = performance.now();
        if (now - lastBg < 320) fitCapped(g, live.current.reducedMotion);
        else live.current.onSelect(null);
        lastBg = now;
      })
      .onZoom((t) => {
        // зум от колеса или перетаскивания фона — небо «тронуто»
        if (t && performance.now() - lastFit > 600) touched.current = true;
      })
      .onNodeDragEnd((n) => {
        n.fx = undefined;
        n.fy = undefined;
      })
      .onRenderFramePost((ctx, scale) => drawLabels(ctx, scale, live.current, nodes.current))
      .onEngineStop(() => {
        // вписываем, когда укладка остыла, — один раз на новые данные
        // вписываем на каждой остановке, пока небо не трогали руками
        if (needFit.current || !touched.current) {
          needFit.current = false;
          fitCapped(g, live.current.reducedMotion);
        }
      });
    const charge = g.d3Force("charge") as unknown as { strength?: (v: number) => void } | undefined;
    charge?.strength?.(-38);
    let resizeT: ReturnType<typeof setTimeout> | undefined;
    const ro = new ResizeObserver(() => {
      g.width(el.clientWidth).height(el.clientHeight);
      // пока небо не трогали руками, после смены размера вписываем заново
      clearTimeout(resizeT);
      if (!touched.current) resizeT = setTimeout(() => fitCapped(g, true), 60);
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
      g._destructor();
      fg.current = null;
    };
  }, []);

  // данные: позиции сохраняются по id, небо не перестраивается целиком;
  // звёзды, появившиеся в уже уложенном небе, встают рядом с соседом и вспыхивают
  useEffect(() => {
    const g = fg.current;
    if (!g) return;
    const prev = nodes.current;
    const next = new Map<string, N>();
    for (const s of props.sky.nodes) next.set(s.id, Object.assign(prev.get(s.id) ?? {}, s));
    const added = prev.size ? [...next.keys()].filter((k) => !prev.has(k)) : [];
    const incremental = prev.size > 0 && added.length > 0 && added.length <= 3;
    for (const id of added) {
      const nb = [...(props.sky.neighbours.get(id) ?? [])].map((k) => prev.get(k)).find((m) => m?.x != null);
      const n = next.get(id);
      if (n && nb) {
        n.x = (nb.x ?? 0) + 12;
        n.y = (nb.y ?? 0) + 12;
      }
    }
    nodes.current = next;
    if (props.reducedMotion) g.warmupTicks(300).cooldownTicks(0);
    else g.warmupTicks(0).cooldownTicks(Number.POSITIVE_INFINITY);
    g.graphData({ nodes: [...next.values()], links: props.sky.links.map((l) => ({ ...l })) });
    if (incremental) {
      // укладывается только новая звезда: остальные на миг закреплены
      const pinned = [...next.values()].filter((m) => !added.includes(m.id) && m.fx == null);
      for (const m of pinned) {
        m.fx = m.x;
        m.fy = m.y;
      }
      const t = setTimeout(() => {
        for (const m of pinned) {
          m.fx = undefined;
          m.fy = undefined;
        }
      }, 900);
      if (!props.reducedMotion) {
        const now = performance.now();
        for (const id of added) flashes.current.set(id, now);
        g.autoPauseRedraw(false);
        setTimeout(() => {
          for (const id of added) flashes.current.delete(id);
          g.autoPauseRedraw(true);
        }, 700);
      }
      return () => clearTimeout(t);
    }
    if (added.length || !prev.size) {
      const t = setTimeout(
        () => g.zoomToFit(props.reducedMotion ? 0 : 500, 40),
        props.reducedMotion ? 0 : 900,
      );
      return () => clearTimeout(t);
    }
  }, [props.sky, props.reducedMotion]);

  // выбор, приглушение, цвета — только перерисовка (холст читает их из live.current)
  // biome-ignore lint/correctness/useExhaustiveDependencies: зависимости — триггер перерисовки, внутри они не читаются
  useEffect(() => {
    fg.current?.autoPauseRedraw(false);
    const t = setTimeout(() => fg.current?.autoPauseRedraw(true), 50);
    return () => clearTimeout(t);
  }, [props.selected, props.dim, props.colors]);

  useImperativeHandle(ref, () => ({
    fit() {
      if (fg.current) fitCapped(fg.current, live.current.reducedMotion);
    },
    focus(id) {
      const n = nodes.current.get(id);
      if (n?.x != null && n.y != null) fg.current?.centerAt(n.x, n.y, live.current.reducedMotion ? 0 : 300);
    },
    positions() {
      return new Map([...nodes.current].map(([k, n]) => [k, { x: n.x ?? 0, y: n.y ?? 0 }]));
    },
    screen(id) {
      const n = nodes.current.get(id);
      const g = fg.current;
      if (!n || !g || n.x == null || n.y == null) return null;
      const p = g.graph2ScreenCoords(n.x, n.y);
      const r = box.current?.getBoundingClientRect();
      return r ? { x: r.left + p.x, y: r.top + p.y } : null;
    },
  }));

  return <div ref={box} className="sky__canvas" />;
});

export default SkyCanvas;

let lastFit = 0;

/** Вписать небо с полями под заголовок и легенду; маленькую базу не раздувать сильнее 1.6×. */
function fitCapped(g: ForceGraph<N, L>, reduced: boolean) {
  const ms = reduced ? 0 : 400;
  lastFit = performance.now();
  // поля — под заголовок, легенду и подписи (подписи сами держатся внутри холста): 15 % узкой стороны, не больше 96 px
  g.zoomToFit(ms, Math.min(96, Math.min(g.width(), g.height()) * 0.15));
  setTimeout(() => {
    if (g.zoom() > 1.6) g.zoom(1.6, ms);
  }, ms + 20);
}

function withAlpha(color: string, a: number) {
  return `color-mix(in oklab, ${color} ${Math.round(a * 100)}%, transparent)`;
}

function drawStar(
  n: N,
  ctx: CanvasRenderingContext2D,
  scale: number,
  p: SkyCanvasProps,
  flashes: Map<string, number>,
) {
  const x = n.x ?? 0;
  const y = n.y ?? 0;
  const sel = p.selected === n.id;
  const near = p.selected ? p.sky.neighbours.get(p.selected)?.has(n.id) : false;
  const faded = p.dim.has(n.id) || (p.selected && !sel && !near);
  const r = sel ? n.r * 1.35 : n.r;
  ctx.globalAlpha = p.dim.has(n.id) ? 0.18 : faded ? 0.45 : 1;
  ctx.fillStyle = p.colors.fam[n.family];
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fill();
  const lw = 1.2 / scale;
  if (n.object) {
    ctx.strokeStyle = withAlpha(p.colors.ink, 0.5);
    ctx.lineWidth = lw;
    ctx.beginPath();
    ctx.arc(x, y, r + 2.5, 0, Math.PI * 2);
    ctx.stroke();
  }
  if (n.pending) {
    ctx.strokeStyle = p.colors.ink;
    ctx.lineWidth = lw;
    ctx.setLineDash([2 / scale, 2 / scale]);
    ctx.beginPath();
    ctx.arc(x, y, r + (n.object ? 5 : 3), 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);
  }
  if (sel) {
    ctx.strokeStyle = p.colors.ink;
    ctx.lineWidth = 2 / scale;
    ctx.beginPath();
    ctx.arc(x, y, r + 4, 0, Math.PI * 2);
    ctx.stroke();
  }
  const f = flashes.get(n.id);
  if (f != null) {
    const t = Math.min(1, (performance.now() - f) / 600);
    ctx.globalAlpha = 1 - t;
    ctx.strokeStyle = p.colors.fam[n.family];
    ctx.lineWidth = 2 / scale;
    ctx.beginPath();
    ctx.arc(x, y, r + 14 * t, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.globalAlpha = 1;
}

function drawLabels(ctx: CanvasRenderingContext2D, scale: number, p: SkyCanvasProps, nodes: Map<string, N>) {
  const size = 12 / scale;
  ctx.font = `500 ${size}px ${p.colors.font}`;
  ctx.textBaseline = "middle";
  const visible = visibleLabels(p.sky, p.selected);
  const order = labelOrder(p.sky, p.selected, visible);
  const pad = 3 / scale;
  const h = size + 2 * pad;
  const items = order.flatMap((s) => {
    const n = nodes.get(s.id);
    if (!n || n.x == null || n.y == null || p.dim.has(s.id)) return [];
    const text = s.label.length > 42 ? `${s.label.slice(0, 40)}…` : s.label;
    return [
      { id: s.id, text, x: n.x, y: n.y, r: n.r + 2 / scale, w: ctx.measureText(text).width + 2 * pad, h },
    ];
  });
  // мешают подписям только объекты: точки-атомы мелкие, подпись может лечь поверх
  const stars = [...nodes.values()]
    .filter((n) => n.object && n.x != null && n.y != null)
    .map((n) => ({ id: n.id, x: n.x ?? 0, y: n.y ?? 0, r: n.r, w: 0, h: 0 }));
  // границы холста в координатах графа: подписи не уходят за край окна
  const m = ctx.getTransform().inverse();
  const w = ctx.canvas.width;
  const h2 = ctx.canvas.height;
  const a = m.transformPoint({ x: 0, y: 0 });
  const b = m.transformPoint({ x: w, y: h2 });
  const placed = placeLabels(items, 3 / scale, stars, { x: a.x, y: a.y, w: b.x - a.x, h: b.y - a.y });
  for (const it of items) {
    const b = placed.get(it.id);
    if (!b) continue;
    ctx.fillStyle = withAlpha(p.colors.sky, 0.72);
    ctx.beginPath();
    ctx.roundRect(b.x, b.y, b.w, b.h, 3 / scale);
    ctx.fill();
    ctx.fillStyle = it.id === p.selected ? p.colors.ink : withAlpha(p.colors.ink, 0.86);
    ctx.fillText(it.text, b.x + pad, b.y + b.h / 2);
  }
}
