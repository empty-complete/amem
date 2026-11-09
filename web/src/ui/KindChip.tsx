import { useTranslation } from "react-i18next";
import type { Family } from "./families";
import { useFamily } from "./useFamily";
import "./ui.css";

/** Плашка вида: цвет семьи несёт принадлежность, текст — всегда чернилами. */
export function KindChip({
  kind,
  target,
  label,
}: {
  kind: string;
  target?: "atom" | "entity";
  label?: string;
}) {
  const { t } = useTranslation();
  const family: Family = useFamily()(kind, target);
  return (
    <span className="kind" data-family={family} title={t(`family.${family}`)}>
      {label ?? kind}
    </span>
  );
}
