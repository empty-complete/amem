// Рендер тела записи: markdown-it без HTML, [[ссылки]], формулы KaTeX (лениво), санитайз DOMPurify.
// Наружу выходит только очищенный DOM-фрагмент — HTML-строки в React не попадают.
import DOMPurify from "dompurify";
import MarkdownIt, { type StateBlock, type StateInline } from "markdown-it";

type Katex = typeof import("katex").default;
let katexP: Promise<Katex> | null = null;
const loadKatex = () => {
  katexP ??= Promise.all([import("katex"), import("katex/dist/katex.min.css")]).then(([m]) => m.default);
  return katexP;
};

export type Resolve = (label: string) => string;

function wikiRule(state: StateInline, silent: boolean) {
  const src = state.src;
  const pos = state.pos;
  if (src.charCodeAt(pos) !== 0x5b || src.charCodeAt(pos + 1) !== 0x5b) return false;
  const end = src.indexOf("]]", pos + 2);
  if (end < 0) return false;
  const label = src.slice(pos + 2, end);
  if (!label.trim() || label.includes("\n") || label.includes("[")) return false;
  if (!silent) state.push("wiki_link", "", 0).content = label;
  state.pos = end + 2;
  return true;
}

function mathInline(state: StateInline, silent: boolean) {
  const src = state.src;
  const pos = state.pos;
  if (src.charCodeAt(pos) !== 0x24 || src.charCodeAt(pos + 1) === 0x24) return false;
  if (/\s/.test(src[pos + 1] ?? " ")) return false;
  let end = pos + 1;
  while ((end = src.indexOf("$", end)) >= 0 && src[end - 1] === "\\") end++;
  if (end < 0 || /\s/.test(src[end - 1] ?? " ") || /\d/.test(src[end + 1] ?? "")) return false;
  if (!silent) state.push("math_inline", "", 0).content = src.slice(pos + 1, end);
  state.pos = end + 1;
  return true;
}

function mathBlock(state: StateBlock, startLine: number, endLine: number, silent: boolean) {
  const lineText = (n: number) => state.src.slice(state.bMarks[n]! + state.tShift[n]!, state.eMarks[n]);
  const first = lineText(startLine);
  if (!first.startsWith("$$")) return false;
  if (silent) return true;
  let content = first.slice(2);
  let line = startLine;
  if (content.trimEnd().endsWith("$$") && content.trim().length > 2) {
    content = content.trimEnd().slice(0, -2);
  } else {
    const parts = [content];
    for (line = startLine + 1; line < endLine; line++) {
      const t = lineText(line);
      if (t.trimEnd().endsWith("$$")) {
        parts.push(t.trimEnd().slice(0, -2));
        break;
      }
      parts.push(t);
    }
    content = parts.join("\n");
  }
  state.line = line + 1;
  const token = state.push("math_block", "", 0);
  token.block = true;
  token.content = content.trim();
  token.map = [startLine, state.line];
  return true;
}

function build(resolve: Resolve, katex: Katex | null) {
  const md = new MarkdownIt({ html: false, linkify: false, typographer: false });
  md.inline.ruler.before("link", "wiki_link", wikiRule);
  md.inline.ruler.after("escape", "math_inline", mathInline);
  md.block.ruler.before("fence", "math_block", mathBlock, { alt: ["paragraph"] });
  const esc = md.utils.escapeHtml;
  const tex = (src: string, displayMode: boolean) =>
    katex
      ? katex.renderToString(src, { displayMode, throwOnError: false, output: "htmlAndMathml" })
      : `<code class="tex">${esc(src)}</code>`;
  md.renderer.rules.wiki_link = (t, i) =>
    `<a class="wiki" href="${esc(resolve(t[i]!.content))}">${esc(t[i]!.content)}</a>`;
  md.renderer.rules.math_inline = (t, i) => tex(t[i]!.content, false);
  md.renderer.rules.math_block = (t, i) => `${tex(t[i]!.content, true)}\n`;
  md.renderer.rules.blockquote_open = () => '<blockquote class="quote">\n';
  return md;
}

const MATHML = ["math", "semantics", "annotation", "mrow", "mi", "mo", "mn", "msub", "msup", "msubsup", "mfrac", "msqrt", "mroot", "mspace", "mtext", "mover", "munder", "mstyle", "mpadded", "mtable", "mtr", "mtd"];

/** Markdown → очищенный DocumentFragment. KaTeX грузится, только если в тексте есть «$». */
export async function renderMarkdown(src: string, resolve: Resolve = (l) => `#${encodeURIComponent(l)}`) {
  const katex = src.includes("$") ? await loadKatex() : null;
  const html = build(resolve, katex).render(src);
  return DOMPurify.sanitize(html, {
    RETURN_DOM_FRAGMENT: true,
    ADD_TAGS: MATHML,
    ADD_ATTR: ["aria-hidden", "encoding", "mathvariant", "stretchy", "fence", "separator", "lspace", "rspace", "width", "height", "depth", "columnalign", "displaystyle", "scriptlevel"],
  });
}
