// Подсказки под полем ввода (окно «Записать», поле тегов): список по шаблону ARIA combobox — фокус остаётся в
// поле, стрелки двигают выбор (aria-activedescendant), Enter или Tab подставляют, Esc закрывает.
import { type KeyboardEvent, useEffect, useId, useState } from "react";
import "../palette/palette.css";

/** Значение с задержкой: запрос подсказок не на каждую букву. */
export function useDebounced<T>(v: T, ms = 150) {
  const [d, setD] = useState(v);
  useEffect(() => {
    const t = setTimeout(() => setD(v), ms);
    return () => clearTimeout(t);
  }, [v, ms]);
  return d;
}

export interface Option {
  id: string;
  label: string;
  /** Справа мелко: число записей, вид. */
  meta?: string;
}

/** Состояние списка и обработчик клавиш для поля; onPick — что сделать с выбранным. */
export function useSuggest(options: Option[], onPick: (o: Option) => void) {
  const id = useId();
  const [active, setActive] = useState(0);
  const [closed, setClosed] = useState(false);
  const open = !closed && options.length > 0;
  const at = Math.min(active, Math.max(options.length - 1, 0));
  const pick = (o: Option) => {
    setActive(0);
    onPick(o);
  };
  /** true — клавишу обработал список: полю её не обрабатывать. */
  const onKey = (e: KeyboardEvent): boolean => {
    if (!open) return false;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const n = options.length;
      setActive((at + (e.key === "ArrowDown" ? 1 : n - 1)) % n);
      return true;
    }
    if ((e.key === "Enter" || e.key === "Tab") && !e.shiftKey && !e.nativeEvent.isComposing) {
      const o = options[at];
      if (!o) return false;
      e.preventDefault();
      pick(o);
      return true;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      setClosed(true);
      return true;
    }
    return false;
  };
  const optId = (i: number) => `${id}-o${i}`;
  return {
    open,
    /** Новый ввод снова открывает закрытый по Esc список. */
    reopen: () => {
      setClosed(false);
      setActive(0);
    },
    onKey,
    fieldProps: {
      "aria-autocomplete": "list" as const,
      "aria-controls": open ? id : undefined,
      "aria-activedescendant": open ? optId(at) : undefined,
    },
    list: open ? (
      <div id={id} role="listbox" className="palette palette__list suggest">
        {options.map((o, i) => (
          <div
            key={o.id}
            id={optId(i)}
            role="option"
            // фокус остаётся в поле (aria-activedescendant); -1 — чтобы щелчок не уводил его сюда
            tabIndex={-1}
            aria-selected={i === at}
            className="palette__opt"
            data-focused={i === at || undefined}
            // mousedown, а не click: поле не теряет фокус
            onMouseDown={(e) => {
              e.preventDefault();
              pick(o);
            }}
          >
            <span className="palette__label">{o.label}</span>
            {o.meta && <span className="palette__meta">{o.meta}</span>}
          </div>
        ))}
      </div>
    ) : null,
  };
}

/** Слово-заготовка перед курсором: @объект, #тег, [[запись. */
export function tokenBefore(
  text: string,
  caret: number,
): { kind: "@" | "#" | "[["; query: string; from: number } | null {
  const head = text.slice(0, caret);
  const wiki = head.match(/\[\[([^\]\n]*)$/);
  if (wiki) return { kind: "[[", query: wiki[1] ?? "", from: caret - (wiki[0]?.length ?? 0) };
  const m = head.match(/(^|\s)([@#])([\p{L}\p{N}._-]*)$/u);
  if (!m) return null;
  const word = `${m[2]}${m[3]}`;
  return { kind: m[2] as "@" | "#", query: m[3] ?? "", from: caret - word.length };
}
