import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { z } from "zod";
import { RecordList } from "../features/records/RecordList";

export const Route = createFileRoute("/records")({
  validateSearch: z.object({ folder: z.string().optional() }),
  component: Records,
});

/** «Все записи» и содержимое папки — список (главная части A; главная теперь — небо). */
function Records() {
  const { t } = useTranslation();
  const { folder } = Route.useSearch();
  const title =
    folder === "-" ? t("folders.unfiled") : folder ? (folder.split("/").pop() ?? folder) : t("folders.all");
  return <RecordList folder={folder ?? null} title={title} />;
}
