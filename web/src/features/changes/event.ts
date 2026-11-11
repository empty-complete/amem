import type { TFunction } from "i18next";
import type { components } from "../../api/schema";
import { agentName } from "../../ui/format";

export type ChangeEvent = components["schemas"]["ChangeEvent"];

/** Событие одной строкой с действующим лицом: «Вы перенесли в «Архив»», «Записал: extractor (модель)»,
 * «Проверено автоматически». me — агент сессии: свои действия — «Вы …». */
export function eventText(e: ChangeEvent, t: TFunction, lang = "ru", me?: string | null) {
  const who = agentName(e.type === "review" ? (e.reviewed_by ?? e.agent) : e.agent, lang);
  const mine = !!me && (e.type === "review" ? (e.reviewed_by ?? e.agent) : e.agent) === me;
  const as = mine ? "you" : "they";
  const rel = e.rel ? t(`record.rel.${e.rel}`, { defaultValue: e.rel }) : "";
  switch (e.type) {
    case "revision":
      return e.revision === 1
        ? t(`changes.ev.${as}.first`, { who })
        : t(`changes.ev.${as}.revision`, { who, n: e.revision });
    case "status": {
      if (e.status === "auto_verified") return t("changes.ev.auto_verified");
      return t(`changes.ev.${as}.status`, { who, status: e.status ? t(`status.${e.status}`) : "" });
    }
    case "review":
      return e.review_state === "accepted"
        ? t(`changes.ev.${as}.accepted`, { who })
        : e.review_state === "declined"
          ? t(`changes.ev.${as}.declined`, { who })
          : t(`changes.ev.${as}.review`, { who });
    case "folder":
      return e.to
        ? t(`changes.ev.${as}.moved`, { who, to: e.to.split("/").pop() })
        : t(`changes.ev.${as}.unfiled`, { who });
    case "link_created":
      return rel ? t(`changes.ev.${as}.linked_rel`, { who, rel }) : t(`changes.ev.${as}.linked`, { who });
    case "link_retired":
      return t(`changes.ev.${as}.unlinked`, { who });
    default:
      return String(e.type);
  }
}
