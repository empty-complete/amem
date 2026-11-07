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
