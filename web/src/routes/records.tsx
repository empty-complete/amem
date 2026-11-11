import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { z } from "zod";
import type { RecordFilter } from "../api/queries";
import { RecordList } from "../features/records/RecordList";
import { list } from "../features/search/params";

export const Route = createFileRoute("/records")({
  validateSearch: z.object({
    folder: z.string().optional(),
    tag: list.optional(),
    kind: list.optional(),
    status: list.optional(),
    about: z.string().optional(),
  }),
  component: Records,
});

/** «Все записи» и содержимое папки — список с фильтрами в адресе: ссылка и перезагрузка открывают тот же набор. */
function Records() {
  const { t } = useTranslation();
  const s = Route.useSearch();
  const navigate = Route.useNavigate();
  const { folder } = s;
  const title =
    folder === "-" ? t("folders.unfiled") : folder ? (folder.split("/").pop() ?? folder) : t("folders.all");
  const filter = { tag: s.tag, kind: s.kind, status: s.status, about: s.about } as RecordFilter;
  return (
    <RecordList
      folder={folder ?? null}
      title={title}
      filter={filter}
      onFilter={(f) =>
        navigate({
          search: (prev) => ({
            folder: prev.folder,
            // пустые фильтры не пишутся в адрес
            tag: f.tag?.length ? f.tag : undefined,
            kind: f.kind?.length ? f.kind : undefined,
            status: f.status?.length ? f.status : undefined,
            about: f.about || undefined,
          }),
          replace: true,
        })
      }
    />
  );
}
