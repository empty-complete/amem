import type { TFunction } from "i18next";

/** Размер словами: 1.4 ГБ, 420 МБ (двоичные единицы, одна цифра после запятой у ГБ). */
export function size(bytes: number, t: TFunction, locale: string): string {
  const fmt = (n: number, digits: number) =>
    n.toLocaleString(locale, { maximumFractionDigits: digits, minimumFractionDigits: 0 });
  if (bytes >= 1024 ** 3) return t("size.gb", { n: fmt(bytes / 1024 ** 3, 1) });
  if (bytes >= 1024 ** 2) return t("size.mb", { n: fmt(bytes / 1024 ** 2, 0) });
  if (bytes >= 1024) return t("size.kb", { n: fmt(bytes / 1024, 0) });
  return t("size.b", { n: fmt(bytes, 0) });
}

/** Остаток времени: «40 с», «3 мин». */
export function left(seconds: number, t: TFunction): string {
  if (seconds < 60) return t("time.s", { n: Math.max(1, Math.round(seconds)) });
  return t("time.m", { n: Math.round(seconds / 60) });
}
