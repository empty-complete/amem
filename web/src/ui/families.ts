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

type KindEntry = { code: string; family?: "source" | "work" | null };

/** Семья по словарю видов службы (VocabEntry.family): виды и классы из пакетов области — тоже. Сущность — всегда
 * «объект»; вид без family — «работа», как в ядре; словаря ещё нет — запасной список familyOf. */
export function familyFrom(
  kinds: KindEntry[] | undefined,
  kindOrClass: string,
  target?: "atom" | "entity",
): Family {
  if (target === "entity") return "object";
  if (!kinds) return familyOf(kindOrClass, target);
  const v = kinds.find((k) => k.code === kindOrClass);
  if (v) return v.family === "source" ? "source" : "work";
  // в словаре видов все виды атомов, и из пакетов тоже: нет кода — значит класс сущности (если цель не атом)
  return target === "atom" ? "work" : "object";
}
