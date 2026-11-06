import type { TFunction } from "i18next";
import type { components } from "../../api/schema";

export type ChangeEvent = components["schemas"]["ChangeEvent"];

/** Событие словами: «новая ревизия», «связь добавлена», «статус: Проверено». */
export function eventText(e: ChangeEvent, t: TFunction) {
  switch (e.type) {
    case "revision":
      return e.revision === 1 ? t("changes.ev.revision_first") : t("changes.ev.revision");
    case "status":
      return t("changes.ev.status", { status: e.status ? t(`status.${e.status}`) : "" });
    case "review":
      return e.review_state === "accepted"
        ? `${t("changes.ev.review")}: ✓`
        : e.review_state === "declined"
          ? `${t("changes.ev.review")}: ✕`
          : t("changes.ev.review");
    case "link_created":
      return e.rel
        ? `${t("changes.ev.link_created")} · ${t(`record.rel.${e.rel}`, { defaultValue: e.rel })}`
        : t("changes.ev.link_created");
    case "link_retired":
      return t("changes.ev.link_retired");
    default:
      return t(`changes.ev.${e.type as string}`, { defaultValue: String(e.type) });
  }
}
