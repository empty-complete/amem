import { Button } from "@heroui/react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import "./ui.css";

type Props =
  | { state: "loading"; skeleton?: ReactNode; children?: never }
  | { state: "empty"; text: string; action?: { label: string; onPress: () => void } }
  | { state: "error"; message: string; retry?: () => void };

/** Четыре состояния области данных: загрузка (скелет той формы, что придёт), пусто (строка и действие), ошибка (что сломалось и «Повторить»). Полное состояние рисует сам экран. */
export function RegionState(props: Props) {
  const { t } = useTranslation();
  if (props.state === "loading") {
    return (
      <div role="status" aria-live="polite" aria-label={t("region.loading")}>
        {props.skeleton ?? (
          <div style={{ display: "grid", gap: 8 }}>
            {[0, 1, 2, 3, 4].map((i) => (
              <div key={i} className="skeleton-row" />
            ))}
          </div>
        )}
      </div>
    );
  }
  if (props.state === "empty") {
    return (
      <div className="region-msg">
        <p>{props.text}</p>
        {props.action && (
          <Button variant="secondary" size="sm" onPress={props.action.onPress}>
            {props.action.label}
          </Button>
        )}
      </div>
    );
  }
  return (
    <div className="region-msg" role="alert">
      <p>{props.message}</p>
      {props.retry && (
        <Button variant="outline" size="sm" onPress={props.retry}>
          {t("region.retry")}
        </Button>
      )}
    </div>
  );
}
