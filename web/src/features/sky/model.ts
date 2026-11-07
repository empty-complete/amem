// Модель неба: чистые функции без DOM — звёзды, соседи, приглушение, подписи без наложений, переход стрелками.
import type { components } from "../../api/schema";

type Graph = components["schemas"]["GraphResult"];
export type Family = "source" | "work" | "object";

export interface Star {
  id: string;
  label: string;
  kind: string;
  family: Family;
  status: string;
  pending: boolean;
  object: boolean;
  degree: number;
  depth: number;
  r: number;
}
export interface Link {
  source: string;
  target: string;
  rel: string;
}
export interface Sky {
  center: string | null;
  nodes: Star[];
  links: Link[];
  byId: Map<string, Star>;
  neighbours: Map<string, Set<string>>;
  total: number;
  truncated: boolean;
}

export const radius = (object: boolean, degree: number) => (object ? Math.min(14, 5 + 1.6 * Math.sqrt(degree)) : 2.6);

export function buildSky(g: Graph): Sky {
  const ids = new Set(g.nodes.map((n) => n.ref));
  const links = g.edges
    .filter((e) => ids.has(e.src) && ids.has(e.dst) && e.src !== e.dst)
    .map((e) => ({ source: e.src, target: e.dst, rel: e.rel }));
  const neighbours = new Map<string, Set<string>>();
  for (const id of ids) neighbours.set(id, new Set());
  for (const l of links) {
    neighbours.get(l.source)?.add(l.target);
    neighbours.get(l.target)?.add(l.source);
  }
  const nodes: Star[] = g.nodes.map((n) => {
    const object = n.family === "object";
    const degree = n.degree ?? neighbours.get(n.ref)?.size ?? 0;
    return {
      id: n.ref,
      label: n.label,
      kind: n.kind_or_class,
      family: n.family,
      status: n.status,
      pending: n.pending ?? n.status === "needs_review",
      object,
      degree,
      depth: n.depth ?? 0,
      r: radius(object, degree),
    };
  });
  return {
    center: g.ref ?? null,
    nodes,
    links,
    byId: new Map(nodes.map((n) => [n.id, n])),
    neighbours,
    total: g.total ?? nodes.length,
    truncated: g.truncated,
  };
}

export interface Filter {
  families: Set<Family>;
  pendingOnly: boolean;
}

/** Какие звёзды приглушить: фильтр не убирает, а гасит (разд. 5.2). Пустой набор семей — все. */
export function dimmed(sky: Sky, f: Filter): Set<string> {
  const out = new Set<string>();
  for (const s of sky.nodes) {
    const famOk = f.families.size === 0 || f.families.has(s.family);
    if (!famOk || (f.pendingOnly && !s.pending)) out.add(s.id);
  }
  return out;
}

/** Подписи: у объектов всегда, у атомов — у выбранного и его соседей, и у центра неба. */
export function visibleLabels(sky: Sky, selected: string | null): Set<string> {
  const out = new Set<string>();
  for (const s of sky.nodes) if (s.object) out.add(s.id);
  if (sky.center) out.add(sky.center);
  if (selected) {
    out.add(selected);
    for (const n of sky.neighbours.get(selected) ?? []) out.add(n);
  }
  return out;
}

export interface LabelItem {
  id: string;
  x: number;
  y: number;
  r: number;
  w: number;
  h: number;
}
export interface Placed {
  x: number;
  y: number;
  w: number;
  h: number;
  side: "right" | "left" | "below" | "above";
}

const hits = (a: { x: number; y: number; w: number; h: number }, b: typeof a) =>
  a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

/**
 * Жадная раскладка подписей в порядке важности (порядок входа): справа → слева → под → над.
 * Подпись не пересекает поставленные подписи и чужие звёзды; места нет — null (подсказка при наведении остаётся).
 */
export function placeLabels(items: LabelItem[], gap = 3, stars: LabelItem[] = items): Map<string, Placed | null> {
  const out = new Map<string, Placed | null>();
  const boxes: Placed[] = [];
  const discs = stars.map((s) => ({ id: s.id, x: s.x - s.r - 1, y: s.y - s.r - 1, w: 2 * s.r + 2, h: 2 * s.r + 2 }));
  for (const it of items) {
    const tries: Placed[] = [
      { side: "right", x: it.x + it.r + gap, y: it.y - it.h / 2, w: it.w, h: it.h },
      { side: "left", x: it.x - it.r - gap - it.w, y: it.y - it.h / 2, w: it.w, h: it.h },
      { side: "below", x: it.x - it.w / 2, y: it.y + it.r + gap, w: it.w, h: it.h },
      { side: "above", x: it.x - it.w / 2, y: it.y - it.r - gap - it.h, w: it.w, h: it.h },
    ];
    const ok = tries.find(
      (b) => !boxes.some((p) => hits(b, p)) && !discs.some((d) => d.id !== it.id && hits(b, d)),
    );
    out.set(it.id, ok ?? null);
    if (ok) boxes.push(ok);
  }
  return out;
}

const DIR: Record<string, [number, number]> = {
  ArrowRight: [1, 0],
  ArrowLeft: [-1, 0],
  ArrowDown: [0, 1],
  ArrowUp: [0, -1],
};

/** Сосед в направлении стрелки: ближний и с меньшим отклонением, не дальше ~70° от направления. */
export function arrowNeighbour(
  id: string,
  neighbours: Set<string>,
  pos: Map<string, { x: number; y: number }>,
  key: string,
): string | null {
  const d = DIR[key];
  const p = pos.get(id);
  if (!d || !p) return null;
  let best: string | null = null;
  let score = Number.POSITIVE_INFINITY;
  for (const n of neighbours) {
    const q = pos.get(n);
    if (!q) continue;
    const dx = q.x - p.x;
    const dy = q.y - p.y;
    const dist = Math.hypot(dx, dy) || 1e-6;
    const cos = (dx * d[0] + dy * d[1]) / dist;
    if (cos < 0.35) continue; // в пределах ~70° от направления
    const s = dist * (1 + 2 * Math.acos(Math.min(1, cos)));
    if (s < score) {
      score = s;
      best = n;
    }
  }
  return best;
}

/** Порядок важности для подписей: выбранная, центр, объекты по степени, соседи выбранной. */
export function labelOrder(sky: Sky, selected: string | null, visible: Set<string>): Star[] {
  const rank = (s: Star) =>
    s.id === selected ? 0 : s.id === sky.center ? 1 : s.object ? 2 + 1 / (1 + s.degree) : 4;
  return sky.nodes.filter((s) => visible.has(s.id)).sort((a, b) => rank(a) - rank(b));
}
