// Живой предпросмотр, как в Obsidian: разметка Markdown скрыта везде, кроме строк с курсором; заголовки крупнее,
// [[ссылки]] и формулы $…$ отрисованы. Текст остаётся исходным Markdown — меняется только вид. Без фокуса
// отрисовано всё.
import { syntaxTree } from "@codemirror/language";
import type { EditorState, Range } from "@codemirror/state";
import {
  Decoration,
  type DecorationSet,
  type EditorView,
  ViewPlugin,
  type ViewUpdate,
  WidgetType,
} from "@codemirror/view";
import { renderMath } from "../record/markdown";

const hide = Decoration.replace({});
const WIKI = Decoration.mark({ class: "cm-lp-wiki" });
const CODE = Decoration.mark({ class: "cm-lp-code" });
const LINK = Decoration.mark({ class: "cm-lp-link" });
const QUOTE = Decoration.line({ class: "cm-lp-quote" });
const HEAD = [1, 2, 3, 4, 5, 6].map((n) => Decoration.line({ class: `cm-lp-h cm-lp-h${n}` }));

class Bullet extends WidgetType {
  eq() {
    return true;
  }
  toDOM() {
    const s = document.createElement("span");
    s.className = "cm-lp-bullet";
    s.textContent = "•";
    return s;
  }
}

class Formula extends WidgetType {
  constructor(readonly tex: string) {
    super();
  }
  eq(o: Formula) {
    return o.tex === this.tex;
  }
  toDOM() {
    const s = document.createElement("span");
    s.className = "cm-lp-math";
    s.textContent = this.tex;
    void renderMath(this.tex, false).then((f) => s.replaceChildren(f));
    return s;
  }
  /** Щелчок по формуле ставит курсор — строка раскрывается в исходник. */
  ignoreEvent() {
    return false;
  }
}

/** Номера строк, которых касается выделение; без фокуса — ни одной. */
function activeLines(state: EditorState, focused: boolean) {
  const set = new Set<number>();
  if (!focused) return set;
  for (const r of state.selection.ranges) {
    const a = state.doc.lineAt(r.from).number;
    const b = state.doc.lineAt(r.to).number;
    for (let n = a; n <= b; n++) set.add(n);
  }
  return set;
}

function inCode(state: EditorState, pos: number) {
  type Node = ReturnType<ReturnType<typeof syntaxTree>["resolveInner"]>;
  for (let n: Node | null = syntaxTree(state).resolveInner(pos, 1); n; n = n.parent)
    if (/^(InlineCode|FencedCode|CodeBlock)$/.test(n.name)) return true;
  return false;
}

export function previewDecorations(view: EditorView): DecorationSet {
  const { state } = view;
  const active = activeLines(state, view.hasFocus);
  const raw = (pos: number) => active.has(state.doc.lineAt(pos).number);
  const out: Range<Decoration>[] = [];
  const taken: [number, number][] = [];
  const quoted = new Set<number>();
  for (const { from, to } of view.visibleRanges) {
    const text = state.sliceDoc(from, to);
    for (const m of text.matchAll(/\[\[([^\]\n]+)\]\]/g)) {
      const a = from + (m.index ?? 0);
      const b = a + m[0].length;
      if (inCode(state, a)) continue;
      taken.push([a, b]);
      if (raw(a)) out.push(WIKI.range(a, b));
      else out.push(hide.range(a, a + 2), WIKI.range(a + 2, b - 2), hide.range(b - 2, b));
    }
    for (const m of text.matchAll(/(?<![\\$])\$([^$\n]+?)\$(?!\$)/g)) {
      const a = from + (m.index ?? 0);
      const b = a + m[0].length;
      if (inCode(state, a) || taken.some(([x, y]) => a < y && b > x)) continue;
      taken.push([a, b]);
      if (!raw(a)) out.push(Decoration.replace({ widget: new Formula(m[1] ?? "") }).range(a, b));
    }
    syntaxTree(state).iterate({
      from,
      to,
      enter: (n) => {
        if (n.name === "FencedCode" || n.name === "CodeBlock") return false;
        if (taken.some(([a, b]) => n.from >= a && n.to <= b)) return false;
        const parent = n.node.parent?.name ?? "";
        const head = n.name.match(/^ATXHeading(\d)$/);
        const deco = head && HEAD[Number(head[1]) - 1];
        if (deco) {
          out.push(deco.range(state.doc.lineAt(n.from).from));
          return;
        }
        if (n.name === "QuoteMark") {
          const l = state.doc.lineAt(n.from).from;
          if (!quoted.has(l)) out.push(QUOTE.range(l));
          quoted.add(l);
        }
        if (n.name === "InlineCode") out.push(CODE.range(n.from, n.to));
        if (n.name === "Link") out.push(LINK.range(n.from, n.to));
        if (raw(n.from)) return;
        // знак и пробел после него: «## », «> »
        const withSpace = () => (state.sliceDoc(n.to, n.to + 1) === " " ? n.to + 1 : n.to);
        if (n.name === "HeaderMark" && parent.startsWith("ATXHeading"))
          out.push(hide.range(n.from, withSpace()));
        else if (n.name === "QuoteMark") out.push(hide.range(n.from, withSpace()));
        else if (n.name === "EmphasisMark") out.push(hide.range(n.from, n.to));
        else if (n.name === "CodeMark" && parent === "InlineCode") out.push(hide.range(n.from, n.to));
        else if ((n.name === "LinkMark" || n.name === "URL") && parent === "Link")
          out.push(hide.range(n.from, n.to));
        else if (n.name === "ListMark" && n.node.parent?.parent?.name === "BulletList")
          out.push(Decoration.replace({ widget: new Bullet() }).range(n.from, n.to));
      },
    });
  }
  // пустые скрытия (знак без текста) не нужны; строковые украшения стоят в точке начала строки
  return Decoration.set(
    out.filter((r) => r.from < r.to || r.value.spec.class),
    true,
  );
}

export const livePreview = ViewPlugin.fromClass(
  class {
    decorations: DecorationSet;
    constructor(view: EditorView) {
      this.decorations = previewDecorations(view);
    }
    update(u: ViewUpdate) {
      if (
        u.docChanged ||
        u.viewportChanged ||
        u.selectionSet ||
        u.focusChanged ||
        syntaxTree(u.startState) !== syntaxTree(u.state)
      )
        this.decorations = previewDecorations(u.view);
    }
  },
  { decorations: (v) => v.decorations },
);
