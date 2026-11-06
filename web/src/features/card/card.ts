import type { components } from "../../api/schema";

export type Card = components["schemas"]["Card"];
export type CardField = components["schemas"]["CardField"];
export type State = CardField["state"];

export const ORDER: State[] = ["known", "conflict", "asked", "missing", "na"];

/** Сводка карточки amem.card/1: счёт по состояниям, обязательные без значения, группы в порядке полей профиля. */
export function summarize(card: Card) {
  const parts = Object.fromEntries(ORDER.map((s) => [s, 0])) as Record<State, number>;
  for (const f of card.fields) parts[f.state]++;
  const blockers = card.fields
    .filter((f) => f.required && f.state !== "known" && f.state !== "na")
    .filter((f) => f.state !== "conflict" && f.state !== "asked")
    .map((f) => f.label ?? f.property);
  const groups: { name: string | null; fields: CardField[] }[] = [];
  for (const f of card.fields) {
    const name = f.group ?? null;
    let g = groups.find((x) => x.name === name);
    if (!g) {
      g = { name, fields: [] };
      groups.push(g);
    }
    g.fields.push(f);
  }
  return { parts, total: card.fields.length, blockers, groups };
}
