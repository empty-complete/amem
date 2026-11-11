import { delay, HttpResponse, http } from "msw";
import { db } from "./db";
import graphA3 from "./fixtures/graph-a3.json";
import baseFx from "./fixtures/graph-base.json";
import big from "./fixtures/graph-big.json";
import graphE3 from "./fixtures/graph-e3.json";

const around: Record<string, typeof graphE3> = { [graphE3.ref]: graphE3, [graphA3.ref]: graphA3 };

/** Окрестность глубины depth из образца глубины 2. */
function cut(g: typeof graphE3, depth: number) {
  const nodes = g.nodes.filter((n) => (n.depth ?? 0) <= depth);
  const keep = new Set(nodes.map((n) => n.ref));
  return {
    ...g,
    nodes,
    edges: g.edges.filter((e) => keep.has(e.src) && keep.has(e.dst)),
    total: nodes.length,
  };
}

/** Обзор базы вместе с тем, что записано в этой сессии. */
const baseNow = () => ({
  ...baseFx,
  nodes: [...baseFx.nodes, ...db.graph.nodes],
  edges: [...baseFx.edges, ...db.graph.edges],
  total: baseFx.total + db.graph.nodes.length,
});

/** Небо (часть C): обзор базы, окрестности объекта и записи, большая и пустая база. */
export const handlersC = [
  http.get("/api/v1/graph", async ({ request }) => {
    await delay(120);
    const url = new URL(request.url);
    const ref = url.searchParams.get("ref");
    const project = url.searchParams.get("project");
    const depth = Number(url.searchParams.get("depth") ?? 1);
    if (!ref) {
      if (project === "empty")
        return HttpResponse.json({ ref: null, nodes: [], edges: [], truncated: false, total: 0 });
      if (project === "big") return HttpResponse.json(big);
      // фильтры обзора, как у службы: теги — все сразу (и объекты, связанные с отобранными), вид, папка
      const tags = url.searchParams.getAll("tag").filter(Boolean);
      const kinds = url.searchParams.getAll("kind").filter(Boolean);
      const folder = url.searchParams.get("folder");
      const g = baseNow();
      if (!tags.length && !kinds.length && !folder) return HttpResponse.json(g);
      const rec = new Map(db.records.map((r) => [r.ref, r]));
      const inFolder = (f: string | null | undefined) =>
        !folder || (folder === "-" ? !f : f === folder || !!f?.startsWith(`${folder}/`));
      const atoms = g.nodes.filter((n) => {
        const r = rec.get(n.ref);
        return (
          n.ref.startsWith("atm:") &&
          (!kinds.length || kinds.includes(n.kind_or_class)) &&
          inFolder(r?.folder) &&
          (!tags.length || tags.every((t) => r?.tags?.includes(t)))
        );
      });
      const picked = new Set(atoms.map((n) => n.ref));
      const near = new Set(
        g.edges.flatMap((e) => (picked.has(e.src) ? [e.dst] : picked.has(e.dst) ? [e.src] : [])),
      );
      const ents = g.nodes.filter(
        (n) =>
          n.ref.startsWith("ent:") &&
          (!kinds.length || kinds.includes(n.kind_or_class)) &&
          inFolder(rec.get(n.ref)?.folder) &&
          (!tags.length || near.has(n.ref)),
      );
      const nodes = [...atoms, ...ents];
      const keep = new Set(nodes.map((n) => n.ref));
      const edges = g.edges.filter((e) => keep.has(e.src) && keep.has(e.dst));
      return HttpResponse.json({ ...g, nodes, edges, truncated: false, total: nodes.length });
    }
    const g0 = around[ref];
    if (g0) {
      // записанное в этой сессии рядом с окрестностью — тоже в небе
      const inside = new Set(g0.nodes.map((n) => n.ref));
      const edges = db.graph.edges.filter((e) => inside.has(e.dst) || inside.has(e.src));
      const extra = db.graph.nodes
        .filter((n) => edges.some((e) => e.src === n.ref || e.dst === n.ref))
        .map((n) => ({ ...n, depth: 1 }));
      const g = { ...g0, nodes: [...g0.nodes, ...extra], edges: [...g0.edges, ...edges] };
      return HttpResponse.json(cut(g as typeof g0, depth));
    }
    // остальные: центр и его прямые соседи из обзора базы
    const base = baseNow();
    const es = base.edges.filter((e) => e.src === ref || e.dst === ref);
    const keep = new Set([ref, ...es.flatMap((e) => [e.src, e.dst])]);
    const nodes = base.nodes
      .filter((n) => keep.has(n.ref))
      .map((n) => ({ ...n, depth: n.ref === ref ? 0 : 1 }));
    return HttpResponse.json({ ref, nodes, edges: es, truncated: false, total: nodes.length });
  }),
];
