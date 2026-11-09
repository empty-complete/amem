// Язык текста записей — как amem/lang.py службы: слоты LangString, порядок замены, текст на языке интерфейса.
import { useCallback } from "react";
import { useTranslation } from "react-i18next";

export type Lang = "ru" | "en";
/** Текст на нескольких языках (LangString схемы v1): нужен хотя бы один из слотов. */
export type LangString = { ru?: string; en?: string };
/** То, что приходит в теле записи: слот бывает и null. */
type LangLike = { ru?: string | null; en?: string | null };

export const LANGS: readonly Lang[] = ["ru", "en"];

/** Язык i18next (ru, en, en-GB…) → слот LangString; всё, кроме en…, — ru. */
export function langOf(language: string | null | undefined): Lang {
  return language?.toLowerCase().startsWith("en") ? "en" : "ru";
}

/** Слоты по порядку замены: сначала язык, затем остальные по LANGS. */
export function order(lang?: string | null): Lang[] {
  const first = langOf(lang);
  return [first, ...LANGS.filter((x) => x !== first)];
}

const filled = (v: unknown): v is string => typeof v === "string" && v.trim() !== "";

/** Слот, из которого берётся текст на языке lang (с заменой); null — текста нет ни в одном слоте. */
export function slotOf(s: LangLike | null | undefined, lang?: string | null): Lang | null {
  if (!s || typeof s !== "object") return null;
  return order(lang).find((x) => filled(s[x])) ?? null;
}

/** Текст LangString на языке lang, а если его слот пуст — из другого; строка — как есть; нет текста — "". */
export function pickText(s: LangLike | string | null | undefined, lang?: string | null): string {
  if (typeof s === "string") return s;
  const slot = slotOf(s, lang);
  return slot && s ? (s[slot] ?? "") : "";
}

/** Есть ли у LangString текст хотя бы в одном слоте. */
export function hasText(s: LangLike | null | undefined): boolean {
  return slotOf(s) !== null;
}

/**
 * Слот правки: тот, из которого текст показан (иначе правка русской подписи в английском интерфейсе завела бы en
 * с русским текстом); пустой, но уже начатый слот — он же (стёртое и набранное заново остаётся в своём слоте);
 * новый текст — слот языка lang.
 */
export function editSlot(s: LangLike | null | undefined, lang?: string | null): Lang {
  const kept = s && typeof s === "object" ? order(lang).find((x) => typeof s[x] === "string") : undefined;
  return slotOf(s, lang) ?? kept ?? langOf(lang);
}

/** LangString после ввода value в слот правки (editSlot); другие слоты (с текстом) остаются. */
export function withText(s: LangLike | null | undefined, value: string, lang?: string | null): LangString {
  const out: LangString = {};
  for (const x of LANGS) {
    const v = s?.[x];
    if (typeof v === "string") out[x] = v;
  }
  out[editSlot(s, lang)] = value;
  return out;
}

/** Новый LangString: текст в слоте языка lang. */
export function langString(value: string, lang?: string | null): LangString {
  const out: LangString = {};
  out[langOf(lang)] = value;
  return out;
}

/** Язык интерфейса и выбор текста на нём: const { lang, text } = useText(); text(p.label). */
export function useText() {
  const { i18n } = useTranslation();
  const lang = langOf(i18n.language);
  const text = useCallback((s: LangLike | string | null | undefined) => pickText(s, lang), [lang]);
  return { lang, text };
}
