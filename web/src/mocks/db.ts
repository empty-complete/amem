// Изменяемое хранилище моков: всё, что записано через /submit, сразу видно чтению.
// Тесты зовут reset() после каждого теста; в браузере состояние живёт до перезагрузки.
import cardFx from "./fixtures/card-e3.json";
import type changesFx from "./fixtures/changes.json";
import foldersFx from "./fixtures/folders.json";
import type graphFx from "./fixtures/graph-base.json";
import objectsFx from "./fixtures/objects-b.json";
import recordsFx from "./fixtures/records.json";
import viewsFx from "./fixtures/records-b.json";
import templatesFx from "./fixtures/templates.json";

const clone = <T>(x: T): T => structuredClone(x);

type Summary = (typeof recordsFx.items)[number];
type View = (typeof viewsFx)[keyof typeof viewsFx];
type Card = typeof cardFx;
type Obj = (typeof objectsFx)[keyof typeof objectsFx];
type Template = (typeof templatesFx)[number];
type Event = (typeof changesFx.events)[number] & Record<string, unknown>;
type GNode = (typeof graphFx.nodes)[number];
type GEdge = (typeof graphFx.edges)[number];
export interface Task {
  id: string;
  kind: "parse";
  object: string;
  version: number;
  note: string | null;
  state: "open" | "claimed" | "done" | "cancelled";
  created_by: string;
  claimed_by: null;
  claimed_until: null;
}

function folderPaths(): string[] {
  const out: string[] = [];
  const walk = (fs: typeof foldersFx.folders) => {
    for (const f of fs) {
      out.push(f.path);
      walk(f.children as never);
    }
  };
  walk(foldersFx.folders);
  return out;
}

function fresh() {
  return {
    records: clone(recordsFx.items) as Summary[],
    views: clone(viewsFx) as Record<string, View>,
    card: clone(cardFx) as Card,
    objects: clone(objectsFx) as Record<string, Obj>,
    templates: clone(templatesFx) as Template[],
    folders: folderPaths(),
    events: [] as Event[],
    graph: { nodes: [] as GNode[], edges: [] as GEdge[] },
    tasks: [] as Task[],
    submits: 0,
  };
}

export const db = { ...fresh(), reset() {} };
db.reset = () => Object.assign(db, fresh());

let n = 0;
/** Короткий уникальный ref в стиле UUIDv7 образца. */
export function newId(prefix: "atm" | "ent" | "obj" | "task") {
  n += 1;
  const tail = (Date.now() % 1e10).toString(16).padStart(9, "0") + n.toString(16).padStart(3, "0");
  const hex = `0193b7c2-5e1a-7d40-9f2e-${tail.slice(-12)}`;
  return prefix === "obj" || prefix === "task" ? hex : `${prefix}:${hex}`;
}

/** Дерево папок со счётчиками из записей — как ответ службы. */
export function folderTree() {
  const count = (p: string) =>
    db.records.filter((r) => r.folder === p || r.folder?.startsWith(`${p}/`)).length;
  type F = { path: string; name: string; count: number; children: F[] };
  const roots: F[] = [];
  const byPath = new Map<string, F>();
  for (const p of [...db.folders].sort((a, b) => a.split("/").length - b.split("/").length)) {
    const node: F = { path: p, name: p.split("/").pop() ?? p, count: count(p), children: [] };
    byPath.set(p, node);
    const parent = p.includes("/") ? byPath.get(p.slice(0, p.lastIndexOf("/"))) : undefined;
    (parent ? parent.children : roots).push(node);
  }
  return { folders: roots, unfiled: db.records.filter((r) => !r.folder).length, total: db.records.length };
}
