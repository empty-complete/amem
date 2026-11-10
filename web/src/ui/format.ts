// Значения, единицы, размеры и даты словами — одно место на весь интерфейс.

const UNITS: Record<string, { ru: string; en: string }> = {
  Cel: { ru: "°C", en: "°C" },
  K: { ru: "K", en: "K" },
  s: { ru: "с", en: "s" },
  min: { ru: "мин", en: "min" },
  h: { ru: "ч", en: "h" },
  d: { ru: "сут", en: "d" },
  "%": { ru: "%", en: "%" },
  hPa: { ru: "гПа", en: "hPa" },
  kPa: { ru: "кПа", en: "kPa" },
  Pa: { ru: "Па", en: "Pa" },
  V: { ru: "В", en: "V" },
  A: { ru: "А", en: "A" },
  "A.h": { ru: "А·ч", en: "A·h" },
  W: { ru: "Вт", en: "W" },
  m: { ru: "м", en: "m" },
  mm: { ru: "мм", en: "mm" },
  m2: { ru: "м²", en: "m²" },
  cm2: { ru: "см²", en: "cm²" },
  "m/s": { ru: "м/с", en: "m/s" },
  "1": { ru: "", en: "" },
};

export function unitLabel(code: string | null | undefined, lang = "ru") {
  if (!code) return "";
  const u = UNITS[code];
  return u ? (lang.startsWith("en") ? u.en : u.ru) : code;
}

const num = (n: number, lang: string) =>
  new Intl.NumberFormat(lang.startsWith("en") ? "en" : "ru", { maximumFractionDigits: 6 })
    .format(n)
    .replace("-", "−");

export interface ValueLike {
  value_text?: string | null;
  amount?: number | null;
  lower_bound?: number | null;
  upper_bound?: number | null;
  unit?: string | null;
}

/** «±2 %», «60 с», «0…100 %», «IP65». */
export function formatValue(v: ValueLike | null | undefined, lang = "ru"): string {
  if (!v) return "";
  const unit = unitLabel(v.unit, lang);
  const tail = unit ? ` ${unit}` : "";
  if (v.value_text) return `${v.value_text}${tail}`;
  if (v.amount != null) return `${num(v.amount, lang)}${tail}`;
  if (v.lower_bound != null || v.upper_bound != null) {
    const lo = v.lower_bound != null ? num(v.lower_bound, lang) : "";
    const hi = v.upper_bound != null ? num(v.upper_bound, lang) : "";
    if (lo && hi) return `${lo}…${hi}${tail}`;
    return lang.startsWith("en")
      ? `${lo ? `from ${lo}` : `to ${hi}`}${tail}`
      : `${lo ? `от ${lo}` : `до ${hi}`}${tail}`;
  }
  return "";
}

export function formatSize(bytes: number | null | undefined, lang = "ru") {
  if (bytes == null) return "";
  const en = lang.startsWith("en");
  const units = en ? ["B", "KB", "MB", "GB"] : ["Б", "КБ", "МБ", "ГБ"];
  let n = bytes;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return `${new Intl.NumberFormat(en ? "en" : "ru", { maximumFractionDigits: i ? 1 : 0 }).format(n)} ${units[i]}`;
}

export function formatDate(at: string, lang = "ru", withTime = false) {
  return new Intl.DateTimeFormat(lang.startsWith("en") ? "en" : "ru", {
    day: "numeric",
    month: "long",
    year: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  }).format(new Date(at));
}

export function formatTime(at: string, lang = "ru") {
  return new Intl.DateTimeFormat(lang.startsWith("en") ? "en" : "ru", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(at));
}

/** «person:anna» → «anna», «model:extractor» → «extractor (модель)». */
export function agentName(agent: string | null | undefined, lang = "ru") {
  if (!agent) return "";
  const [kind, name] = agent.split(":", 2);
  if (kind === "model") return `${name} (${lang.startsWith("en") ? "model" : "модель"})`;
  return name ?? agent;
}
