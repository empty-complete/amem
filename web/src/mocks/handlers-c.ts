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
      return HttpResponse.json(project === "big" ? big : baseNow());
    }
    const g = around[ref];
    if (g) return HttpResponse.json(cut(g, depth));
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
