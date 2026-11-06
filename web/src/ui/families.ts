export type Family = "source" | "work" | "object";

const SOURCE = new Set(["fact", "parameter", "term", "requirement"]);
const ENTITY = new Set([
  "project",
  "document",
  "edition",
  "organization",
  "person",
  "place",
  "software",
  "topic",
  "artifact",
]);

/** Семья знания по виду записи или классу сущности (разд. 4.2): цвет на плашках и звёздах. */
export function familyOf(kindOrClass: string, target?: "atom" | "entity"): Family {
  if (target === "entity" || ENTITY.has(kindOrClass)) return "object";
  return SOURCE.has(kindOrClass) ? "source" : "work";
}
