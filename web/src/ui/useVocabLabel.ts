import { useQuery } from "@tanstack/react-query";
import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { q } from "../api/queries";

/** Подпись кода из словаря службы (parameter_group, parameter_origin…); словаря или кода нет — undefined.
 * Словарь — из кеша запросов: один запрос на схему, его отсутствие (404) не ошибка. */
export function useVocabLabel(scheme: string) {
  const { i18n } = useTranslation();
  const v = useQuery({ ...q.vocab(scheme), staleTime: Number.POSITIVE_INFINITY, retry: false });
  return useCallback(
    (code: string | null | undefined): string | undefined => {
      if (!code) return undefined;
      const e = v.data?.find((x) => x.code === code);
      if (!e) return undefined;
      return i18n.language.startsWith("en") ? (e.label.en ?? e.label.ru) : e.label.ru;
    },
    [v.data, i18n.language],
  );
}

/** Код без словаря — по-человечески: «operating_conditions» → «Operating conditions». */
export function humanize(code: string) {
  const s = code.replaceAll("_", " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}
