// Очередь в сотни пунктов (часть J): по документам, с фильтрами «Документ» и «Объект». Всё — на клиенте поверх
// загруженного списка (до 500 пунктов, предел контракта).
import type { components } from "../../api/schema";

export type Item = components["schemas"]["ReviewItem"];
export type Grouping = "time" | "source";
export type Row = { kind: "head"; key: string; name: string; count: number } | { kind: "item"; item: Item };

export const NO_SOURCE = "-";
export const ENTITIES = "ent";

/** Ключ группы пункта: документ (объект первого источника), «Сущности» или «Без источника». */
export function groupKey(it: Item): string {
  if (it.source?.object) return it.source.object;
  return it.ref.startsWith("ent:") ? ENTITIES : NO_SOURCE;
}

/** Фильтр по документу (ключ группы) и по объекту (ссылка ent: в about). */
export function filterItems(items: Item[], f: { object?: string; about?: string }): Item[] {
  return items.filter(
    (it) =>
      (!f.object || groupKey(it) === f.object) &&
      (!f.about || it.ref === f.about || (it.about ?? []).some((a) => a.ref === f.about)),
  );
}

/** Порядок на экране и строки списка. По времени — как пришло; по документам — группы по числу пунктов
 * (больше — выше), «Сущности» и «Без источника» последними, внутри группы — по времени. */
export function arrange(
  items: Item[],
  grouping: Grouping,
  names: { none: string; entities: string },
): { ordered: Item[]; rows: Row[] } {
  if (grouping === "time") return { ordered: items, rows: items.map((item) => ({ kind: "item", item })) };
  const groups = new Map<string, Item[]>();
  for (const it of items) {
    const k = groupKey(it);
    groups.set(k, [...(groups.get(k) ?? []), it]);
  }
  const tail = (k: string) => (k === NO_SOURCE ? 2 : k === ENTITIES ? 1 : 0);
  const keys = [...groups.keys()].sort(
    (a, b) =>
      tail(a) - tail(b) ||
      (groups.get(b)?.length ?? 0) - (groups.get(a)?.length ?? 0) ||
      nameOf(groups, a, names).localeCompare(nameOf(groups, b, names)),
  );
  const ordered: Item[] = [];
  const rows: Row[] = [];
  for (const k of keys) {
    const its = groups.get(k) ?? [];
    rows.push({ kind: "head", key: k, name: nameOf(groups, k, names), count: its.length });
    for (const item of its) {
      ordered.push(item);
      rows.push({ kind: "item", item });
    }
  }
  return { ordered, rows };
}

function nameOf(groups: Map<string, Item[]>, k: string, names: { none: string; entities: string }) {
  if (k === NO_SOURCE) return names.none;
  if (k === ENTITIES) return names.entities;
  return groups.get(k)?.[0]?.source?.object_name ?? k;
}

/** Документы и объекты очереди для фильтров: имя и число пунктов, по убыванию числа. */
export function facets(items: Item[], names: { none: string; entities: string }) {
  const docs = new Map<string, { name: string; count: number }>();
  const about = new Map<string, { name: string; count: number }>();
  for (const it of items) {
    const k = groupKey(it);
    const name =
      k === NO_SOURCE ? names.none : k === ENTITIES ? names.entities : (it.source?.object_name ?? k);
    docs.set(k, { name, count: (docs.get(k)?.count ?? 0) + 1 });
    for (const a of it.about ?? [])
      about.set(a.ref, { name: a.label, count: (about.get(a.ref)?.count ?? 0) + 1 });
  }
  const sorted = (m: Map<string, { name: string; count: number }>) =>
    [...m.entries()]
      .map(([key, v]) => ({ key, ...v }))
      .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  return { docs: sorted(docs), about: sorted(about) };
}

/** Следующий после решения. По документам — в той же группе дальше, потом в ней же раньше, потом по экрану;
 * по времени — просто следующий на экране. */
export function nextAfter(ordered: Item[], current: Item, grouping: Grouping): Item | null {
  const i = ordered.indexOf(current);
  if (grouping === "time") return ordered[i + 1] ?? ordered[i - 1] ?? null;
  const k = groupKey(current);
  const same = (it: Item | undefined) => !!it && it !== current && groupKey(it) === k;
  const after = ordered.slice(i + 1).find(same);
  if (after) return after;
  const before = [...ordered.slice(0, i)].reverse().find(same);
  return before ?? ordered[i + 1] ?? ordered[i - 1] ?? null;
}
