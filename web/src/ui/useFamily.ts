import { useQuery } from "@tanstack/react-query";
import { useCallback } from "react";
import { q } from "../api/queries";
import { type Family, familyFrom } from "./families";

/** Семья вида или класса по словарю службы; словарь — из кеша запросов, без запроса на каждую плашку. */
export function useFamily() {
  const kinds = useQuery({ ...q.vocab("kind"), staleTime: Number.POSITIVE_INFINITY });
  return useCallback(
    (kindOrClass: string, target?: "atom" | "entity"): Family => familyFrom(kinds.data, kindOrClass, target),
    [kinds.data],
  );
}
