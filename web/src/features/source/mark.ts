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

/** Прокрутить к элементу только внутри ближайшего прокручиваемого контейнера — страница не двигается. */
export function scrollWithin(el: HTMLElement | null) {
  if (!el) return;
  let box = el.parentElement;
  while (
    box &&
    !(box.scrollHeight > box.clientHeight && /(auto|scroll)/.test(getComputedStyle(box).overflowY))
  ) {
    box = box.parentElement;
  }
  if (!box || box === document.scrollingElement || box === document.body) return;
  const a = el.getBoundingClientRect();
  const b = box.getBoundingClientRect();
  box.scrollTop += a.top - b.top - (b.height - a.height) / 2;
}

const norm = (s: string) => s.replace(/\s+/g, " ").trim().toLowerCase();

/** Подсветить первое вхождение начала цитаты в одном текстовом узле (абзацы docx-preview и Markdown — узлы
 * целиком); вернуть mark или null. */
export function markQuote(root: HTMLElement, quote: string): HTMLElement | null {
  const want = norm(quote).slice(0, 60);
  if (!want) return null;
  const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    const text = n.textContent ?? "";
    const at = norm(text).indexOf(want);
    if (at < 0) continue;
    // позиция в исходном тексте: нормализация сжимает пробелы — ищем по словам с начала цитаты
    const words = want.split(" ");
    const re = new RegExp(words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("\\s+"), "i");
    const m = text.match(re);
    if (!m || m.index == null) continue;
    const range = document.createRange();
    range.setStart(n, m.index);
    range.setEnd(n, m.index + m[0].length);
    const mark = document.createElement("mark");
    mark.className = "docx__quote";
    range.surroundContents(mark);
    return mark;
  }
  return null;
}
