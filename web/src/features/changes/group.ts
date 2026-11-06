import type { ChangeEvent } from "./event";

const dayKey = (d: Date) => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;

/** События по местным дням: «Сегодня», «Вчера», затем «4 ноября» (год — если не текущий). */
export function groupByDay(
  events: ChangeEvent[],
  now: Date,
  lang: string,
  words: { today: string; yesterday: string } = { today: "Сегодня", yesterday: "Вчера" },
) {
  const today = dayKey(now);
  const y = new Date(now);
  y.setDate(y.getDate() - 1);
  const yesterday = dayKey(y);
  const fmt = (d: Date) =>
    new Intl.DateTimeFormat(lang.startsWith("en") ? "en" : "ru", {
      day: "numeric",
      month: "long",
      ...(d.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
    }).format(d);
  const groups: { key: string; title: string; events: ChangeEvent[] }[] = [];
  for (const e of [...events].sort((a, b) => b.at.localeCompare(a.at))) {
    const d = new Date(e.at);
    const key = dayKey(d);
    let g = groups.find((x) => x.key === key);
    if (!g) {
      g = {
        key,
        title: key === today ? words.today : key === yesterday ? words.yesterday : fmt(d),
        events: [],
      };
      groups.push(g);
    }
    g.events.push(e);
  }
  return groups;
}
