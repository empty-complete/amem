import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { useUpdates } from "./updates";

/** Значок в верхней строке — только когда есть что сказать: установлено и ждёт перезапуска или не встало. */
export function UpdateBadge() {
  const { t } = useTranslation();
  const s = useUpdates().data;
  if (!s) return null;
  const kind =
    s.state === "ready" || s.state === "restarting" ? "ready" : s.state === "failed" ? "failed" : null;
  if (!kind) return null;
  return (
    <Link to="/settings" className="updchip" data-kind={kind} title={s.message || undefined}>
      {t(`updates.badge_${kind}`)}
    </Link>
  );
}
