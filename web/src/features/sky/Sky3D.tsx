// Небо в 3D: 3d-force-graph (WebGL) — отдельный ленивый кусок, только по переключателю «3D».
import ForceGraph3D from "3d-force-graph";
import { useEffect, useRef } from "react";
import type { SkyCanvasProps } from "./SkyCanvas";

type N = {
  id: string;
  label: string;
  family: "source" | "work" | "object";
  r: number;
  x?: number;
  y?: number;
  z?: number;
};

const idOf = (e: unknown) => (typeof e === "object" && e ? (e as { id: string }).id : String(e));

type Live = { current: Pick<SkyCanvasProps, "selected" | "colors"> };

/** Связи выбранной звезды — цветом подписи и толще, прочие — приглушённые; цвета и выбор — из live. */
function paintLinks(fg: InstanceType<typeof ForceGraph3D>, live: Live) {
  const touches = (l: object) => {
    const s = live.current.selected;
    const { source, target } = l as { source: unknown; target: unknown };
    return !!s && (idOf(source) === s || idOf(target) === s);
  };
  fg.linkColor((l: object) => (touches(l) ? live.current.colors.ink : live.current.colors.muted)).linkWidth(
    (l: object) => (touches(l) ? 1.2 : 0),
  );
}

export default function Sky3D(p: Omit<SkyCanvasProps, "onHover">) {
  const box = useRef<HTMLDivElement>(null);
  const live = useRef(p);
  live.current = p;
  const g = useRef<InstanceType<typeof ForceGraph3D> | null>(null);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    let fitted = false;
    const fg = new ForceGraph3D(el, { controlType: "orbit" })
      .backgroundColor("rgba(0,0,0,0)")
      .showNavInfo(false)
      .nodeId("id")
      .nodeLabel((n: object) => (n as N).label)
      .nodeVal((n: object) => (n as N).r * (n as N).r)
      .nodeRelSize(2)
      // связи видно в обеих темах: цвет подписи неба, а не приглушённый; у выбранной звезды — толще
      .linkOpacity(0.55)
      .nodeOpacity(1)
      .nodeResolution(16)
      .onNodeClick((n: object) => live.current.onSelect((n as N).id))
      .onBackgroundClick(() => live.current.onSelect(null))
      .onEngineStop(() => {
        if (!fitted) {
          fitted = true;
          fg.zoomToFit(live.current.reducedMotion ? 0 : 600, 40);
        }
      });
    g.current = fg;
    const ro = new ResizeObserver(() => fg.width(el.clientWidth).height(el.clientHeight));
    ro.observe(el);
    return () => {
      ro.disconnect();
      fg._destructor();
    };
  }, []);

  useEffect(() => {
    const fg = g.current;
    if (!fg) return;
    fg.nodeColor((n: object) => {
      const s = n as N;
      return live.current.dim.has(s.id) ? live.current.colors.muted : live.current.colors.fam[s.family];
    });
    paintLinks(fg, live);
    fg.graphData({ nodes: p.sky.nodes.map((n) => ({ ...n })), links: p.sky.links.map((l) => ({ ...l })) });
    if (p.reducedMotion) fg.warmupTicks(200).cooldownTicks(0);
  }, [p.sky, p.reducedMotion]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: цвета и выбор читаются из live, перекраска — по их смене
  useEffect(() => {
    if (g.current) paintLinks(g.current, live);
  }, [p.selected, p.colors]);

  useEffect(() => {
    const fg = g.current;
    if (!fg || !p.selected) return;
    const n = fg.graphData().nodes.find((x: object) => (x as N).id === p.selected) as N | undefined;
    if (n?.x == null || n.y == null || n.z == null) return;
    const d = 90;
    const k = 1 + d / Math.hypot(n.x, n.y, n.z || 1);
    fg.cameraPosition(
      { x: n.x * k, y: n.y * k, z: n.z * k },
      { x: n.x, y: n.y, z: n.z },
      p.reducedMotion ? 0 : 800,
    );
  }, [p.selected, p.reducedMotion]);

  return <div ref={box} className="sky__canvas" />;
}
