import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { z } from "zod";
import { HomeSky } from "../features/home/HomeSky";
import { RecordList } from "../features/records/RecordList";
import { list } from "../features/search/params";
import { useCorePlugin } from "../features/settings/store";

const FAMILIES = ["source", "work", "object"] as const;

export const Route = createFileRoute("/")({
  validateSearch: z.object({
    f: z
      .string()
      .optional()
      .catch(undefined)
      .transform(
        (v) =>
          v
            ?.split(",")
            .filter((x) => (FAMILIES as readonly string[]).includes(x))
            .join(",") || undefined,
      ),
    pending: z.coerce.boolean().optional().catch(undefined),
    center: z.string().optional().catch(undefined),
    project: z.string().optional().catch(undefined),
    tag: list.optional(),
    kind: z.string().optional().catch(undefined),
    folder: z.string().optional().catch(undefined),
  }),
  component: function Home() {
    const s = Route.useSearch();
    const { t } = useTranslation();
    // небо — плагин ядра: выключено в настройках — на главной список всех записей
    const sky = useCorePlugin("sky.home");
    if (!sky) return <RecordList folder={null} title={t("folders.all")} />;
    return (
      <HomeSky
        families={s.f}
        pending={!!s.pending}
        center={s.center}
        project={s.project}
        scope={{ tag: s.tag, kind: s.kind, folder: s.folder }}
      />
    );
  },
});
