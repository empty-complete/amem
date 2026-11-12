// Род файла источника для просмотра и выбора места: по типу содержимого и расширению имени (тип есть не всегда).
import { useQuery } from "@tanstack/react-query";
import { q } from "../../api/queries";

export type FileKind = "pdf" | "sheet" | "docx" | "md" | "slides" | "image" | "text";

type Named = {
  media_type?: string | null;
  original_name?: string | null;
  object_name?: string | null;
  sheets?: string[] | null;
};

const ext = (name?: string | null) => {
  const n = (name ?? "").toLowerCase();
  return n.includes(".") ? (n.split(".").pop() ?? "") : "";
};

export function fileKind(o: Named): FileKind {
  const mt = (o.media_type ?? "").toLowerCase();
  const e = ext(o.original_name ?? o.object_name);
  if (mt === "application/pdf" || e === "pdf") return "pdf";
  if (o.sheets?.length || e === "xlsx" || e === "xlsm" || mt.includes("spreadsheetml")) return "sheet";
  if (e === "docx" || mt.includes("wordprocessingml")) return "docx";
  if (e === "md" || mt === "text/markdown") return "md";
  if (e === "pptx" || mt.includes("presentationml")) return "slides";
  if (mt.startsWith("image/")) return "image";
  return "text";
}

/** Имена листов книги: из карточки объекта, а если текст ещё не извлекали — из текста версии (первая строка
 * страницы — имя листа; запрос текста заодно кладёт его в кэш службы). */
export function useSheetNames(id: string, version: number | undefined, known?: string[] | null) {
  const text = useQuery({ ...q.objectText(id, version ?? 1), enabled: !known?.length && version != null });
  if (known?.length) return { names: known, pending: false };
  return {
    names: (text.data?.pages ?? []).map((p) => p.split("\n", 1)[0] ?? "").filter(Boolean),
    pending: text.isPending,
  };
}
