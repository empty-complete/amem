import { useTranslation } from "react-i18next";

const STEPS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["minute", 60],
  ["hour", 3600],
  ["day", 86400],
  ["week", 604800],
];

/** «2 ч назад» по языку интерфейса; полная дата — в подсказке. */
export function RelativeTime({ at, now = Date.now() }: { at: string; now?: number }) {
  const { i18n } = useTranslation();
  const d = new Date(at);
  const diff = (d.getTime() - now) / 1000;
  const abs = Math.abs(diff);
  const fmt = new Intl.RelativeTimeFormat(i18n.language, { numeric: "auto", style: "short" });
  let text: string;
  if (abs < 60) text = fmt.format(0, "minute");
  else if (abs >= 30 * 86400) text = d.toLocaleDateString(i18n.language, { day: "numeric", month: "short" });
  else {
    let unit: Intl.RelativeTimeFormatUnit = "minute";
    let size = 60;
    for (const [u, s] of STEPS) if (abs >= s) [unit, size] = [u, s];
    text = fmt.format(Math.round(diff / size), unit);
  }
  return (
    <time dateTime={at} title={d.toLocaleString(i18n.language)}>
      {text}
    </time>
  );
}
