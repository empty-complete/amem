import type { Pos } from "./quote";

/** Обернуть диапазон [start, end) по элементам-спанам в <mark>; вернуть первый mark. Каждый спан — один текстовый узел (как у pdf.js). */
export function markRange(els: HTMLElement[], start: Pos, end: Pos): HTMLElement | null {
  let first: HTMLElement | null = null;
  for (let s = start.span; s <= end.span; s++) {
    const el = els[s];
    const node = el?.firstChild;
    if (!el || !node || node.nodeType !== Node.TEXT_NODE) continue;
    const text = node.textContent ?? "";
    const from = s === start.span ? start.offset : 0;
    const to = s === end.span ? Math.min(end.offset, text.length) : text.length;
    if (to <= from) continue;
    const mark = document.createElement("mark");
    mark.className = "q";
    mark.textContent = text.slice(from, to);
    el.replaceChildren(text.slice(0, from), mark, text.slice(to));
    first ??= mark;
  }
  return first;
}
