import type { components } from "../../api/schema";
import type { IconName } from "../../ui/icons";

export type Reason = components["schemas"]["ReviewReason"];

export const REASON_ICON: Record<Reason, IconName> = {
  semantic: "search",
  warning: "warn",
  high_risk: "shield",
  semantic_doubt: "clock",
  edit: "pencil",
  source_changed: "file",
  audit: "check",
  calibration: "ruler",
  imported: "inbox",
};

export const REASONS = Object.keys(REASON_ICON) as Reason[];

/** Что решает только человек: всё, кроме смысловой проверки — её разбирает проверяющая модель (amemo-verify);
 * человек может решить и её. Как в службе: review.MODEL_REASONS = {semantic}. */
export const MODEL_REASONS: readonly Reason[] = ["semantic"];
export const forPerson = (r: string) => !MODEL_REASONS.includes(r as Reason);

/** Решение о правке (новая ревизия), а не о самой записи: подтверждение делает правку текущей. */
export const aboutEdit = (r: string) => r === "edit" || r === "imported";
