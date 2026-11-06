// Поиск цитаты в спанах слоя текста (pdf.js) или абзацах: нормализация, переносы, кавычки, минусы.

const DASHES = /[−–—‐‑]/g;
const QUOTES = /[«»„“”‟"]/g;

/** Нормализация для сравнения: NFKC, единые минусы и кавычки, без переносов, пробелы схлопнуты, нижний регистр. */
export function normalize(s: string): string {
  return s
    .normalize("NFKC")
    .replace(/-\s*\n\s*/g, "")
    .replace(DASHES, "-")
    .replace(QUOTES, '"')
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

export interface Pos {
  span: number;
  offset: number;
}

/** Склейка спанов с картой «символ склейки → (спан, смещение в исходном спане)». */
function joined(spans: string[]) {
  const chars: string[] = [];
  const map: Pos[] = [];
  let prevSpace = true;
  spans.forEach((raw, span) => {
    let hyphenated = false;
    for (let i = 0; i < raw.length; i++) {
      let c = (raw[i] as string).normalize("NFKC");
      if (c === "-" || DASHES.test(c)) {
        DASHES.lastIndex = 0;
        // перенос: «погреш-» в конце спана и продолжение в следующем
        if (i === raw.length - 1 && span < spans.length - 1 && /\p{L}/u.test(raw[i - 1] ?? "")) {
          hyphenated = true;
          continue;
        }
        c = "-";
      }
      DASHES.lastIndex = 0;
      if (QUOTES.test(c)) c = '"';
      QUOTES.lastIndex = 0;
      if (/\s/.test(c)) {
        if (prevSpace) continue;
        c = " ";
        prevSpace = true;
      } else prevSpace = false;
      for (const ch of c.toLowerCase()) {
        chars.push(ch);
        map.push({ span, offset: i });
      }
    }
    if (!prevSpace && !hyphenated) {
      chars.push(" ");
      map.push({ span, offset: raw.length });
      prevSpace = true;
    }
  });
  return { text: chars.join(""), map };
}

/** Начало и конец (конец не включительно) цитаты по спанам; null — не найдена. */
export function findQuote(spans: string[], quote: string): { start: Pos; end: Pos } | null {
  const q = normalize(quote);
  if (!q) return null;
  const { text, map } = joined(spans);
  const at = text.indexOf(q);
  if (at < 0) return null;
  const first = map[at] as Pos;
  const last = map[at + q.length - 1] as Pos;
  return { start: first, end: { span: last.span, offset: last.offset + 1 } };
}
