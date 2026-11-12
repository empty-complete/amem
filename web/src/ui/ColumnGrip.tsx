// Край колонки, который тянут мышью (или стрелками): ширина — CSS-переменная на <html>, запоминается на устройстве.
// Ставится внутрь колонки с position: relative; колонка берёт ширину из var(--name, по умолчанию).
import { type KeyboardEvent, type PointerEvent, useEffect, useState } from "react";
import "./ui.css";

const read = (key: string) => {
  try {
    const v = Number(window.localStorage.getItem(key));
    return Number.isFinite(v) && v > 0 ? v : null;
  } catch {
    return null;
  }
};

export function ColumnGrip({
  name,
  label,
  min,
  max,
  initial,
  side = "right",
  className,
}: {
  /** CSS-переменная ширины, например --folders-w; ключ хранения — amemo.col<name>. */
  name: string;
  label: string;
  min: number;
  max: number;
  initial: number;
  /** На каком краю колонки стоит ручка: right — колонка слева (панель папок), left — колонка справа (граф). */
  side?: "left" | "right";
  className?: string;
}) {
  const key = `amemo.col${name}`;
  const [width, setWidth] = useState(() => read(key) ?? initial);
  useEffect(() => {
    document.documentElement.style.setProperty(name, `${width}px`);
  }, [name, width]);
  const save = (w: number) => {
    try {
      window.localStorage.setItem(key, String(w));
    } catch {
      // без хранилища ширина просто не запомнится
    }
  };
  const clamp = (w: number) => Math.round(Math.min(max, Math.max(min, w)));
  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    const grip = e.currentTarget;
    const box = grip.parentElement?.getBoundingClientRect();
    grip.setPointerCapture(e.pointerId);
    let last = width;
    const move = (ev: globalThis.PointerEvent) => {
      last = clamp(side === "right" ? ev.clientX - (box?.left ?? 0) : (box?.right ?? 0) - ev.clientX);
      setWidth(last);
    };
    const up = () => {
      grip.removeEventListener("pointermove", move);
      grip.removeEventListener("pointerup", up);
      save(last);
    };
    grip.addEventListener("pointermove", move);
    grip.addEventListener("pointerup", up);
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? 64 : 16;
    const grow = side === "right" ? "ArrowRight" : "ArrowLeft";
    const shrink = side === "right" ? "ArrowLeft" : "ArrowRight";
    const to = e.key === grow ? width + step : e.key === shrink ? width - step : null;
    if (to == null) return;
    e.preventDefault();
    const w = clamp(to);
    setWidth(w);
    save(w);
  };
  return (
    // biome-ignore lint/a11y/useSemanticElements: разделитель с изменяемым значением — role=separator, а не <hr>
    <div
      className={className ? `colgrip ${className}` : "colgrip"}
      data-side={side}
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={width}
      tabIndex={0}
      onPointerDown={onPointerDown}
      onKeyDown={onKey}
      onDoubleClick={() => {
        setWidth(initial);
        save(initial);
      }}
    />
  );
}
