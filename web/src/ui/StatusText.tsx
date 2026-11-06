import { useTranslation } from "react-i18next";
import type { components } from "../api/schema";
import { Icon, type IconName } from "./icons";
import "./ui.css";

type Status = components["schemas"]["Status"];
const LOOK: Record<Status, [IconName, "ok" | "wait" | "bad" | "quiet"]> = {
  verified: ["check", "ok"],
  auto_verified: ["check", "ok"],
  needs_review: ["clock", "wait"],
  draft: ["dash", "quiet"],
  rejected: ["cross", "bad"],
  deprecated: ["dash", "quiet"],
  superseded: ["dash", "quiet"],
};

/** Статус словом и значком; цвет только помогает. */
export function StatusText({ status, compact = false }: { status: Status; compact?: boolean }) {
  const { t } = useTranslation();
  const [icon, tone] = LOOK[status];
  const text = t(`status.${status}`);
  return (
    <span className="status" data-tone={tone} title={compact ? text : undefined}>
      <Icon name={icon} />
      {compact ? <span className="sr-only">{text}</span> : text}
    </span>
  );
}
