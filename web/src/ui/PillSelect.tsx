// Компактный список-плашка для строк фильтров: подпись — выбранное значение, выбранное (не «любое») подсвечено.
import type { ReactNode } from "react";
import { Icon } from "./icons";
import "./ui.css";

export function PillSelect({
  label,
  value,
  onChange,
  children,
  className,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span className={className ? `pillsel ${className}` : "pillsel"} data-on={value ? "" : undefined}>
      <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
        {children}
      </select>
      <Icon name="chev" size={10} className="pillsel__chev" />
    </span>
  );
}
