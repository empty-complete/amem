import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { z } from "zod";
import { RecordList } from "../features/records/RecordList";

export const Route = createFileRoute("/")({
  validateSearch: z.object({ folder: z.string().optional() }),
  component: Home,
});

function Home() {
  const { t } = useTranslation();
  const { folder } = Route.useSearch();
  const title =
    folder === "-" ? t("folders.unfiled") : folder ? (folder.split("/").pop() ?? folder) : t("folders.all");
  return <RecordList folder={folder ?? null} title={title} />;
}
