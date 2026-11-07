// Редактор тела: CodeMirror 6 с подсветкой Markdown, панелью и клавишами; подсказки [[ @ #. Лениво.
import { autocompletion, type Completion, type CompletionContext } from "@codemirror/autocomplete";
import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { markdown } from "@codemirror/lang-markdown";
import { defaultHighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { EditorSelection, EditorState } from "@codemirror/state";
import { EditorView, keymap, placeholder as ph } from "@codemirror/view";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";

export interface BodyEditorApi {
  wrap: (before: string, after?: string) => void;
  line: (prefix: string) => void;
  focus: () => void;
}

export interface Suggest {
  records: (q: string) => Promise<string[]>;
  objects: (q: string) => Promise<string[]>;
  tags: (q: string) => Promise<string[]>;
}

function wrap(view: EditorView, before: string, after = before) {
  view.dispatch(
    view.state.changeByRange((r) => {
      const text = view.state.sliceDoc(r.from, r.to);
      return {
        changes: { from: r.from, to: r.to, insert: before + text + after },
        range: text
          ? EditorSelection.range(r.from, r.to + before.length + after.length)
          : EditorSelection.cursor(r.from + before.length),
      };
    }),
  );
  view.focus();
  return true;
}

function line(view: EditorView, prefix: string) {
  const l = view.state.doc.lineAt(view.state.selection.main.head);
  const has = l.text.startsWith(prefix);
  view.dispatch({
    changes: has ? { from: l.from, to: l.from + prefix.length } : { from: l.from, insert: prefix },
  });
  view.focus();
  return true;
}

const BodyEditor = forwardRef<
  BodyEditorApi,
  {
    value: string;
    onChange: (v: string) => void;
    label: string;
    placeholder: string;
    suggest: Suggest;
    onSubmit?: () => void;
  }
>(function BodyEditor(p, ref) {
  const box = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const live = useRef(p);
  live.current = p;

  useEffect(() => {
    if (!box.current) return;
    const source = async (ctx: CompletionContext) => {
      const wiki = ctx.matchBefore(/\[\[[^\]\n]*/);
      const at = ctx.matchBefore(/@[\p{L}\p{N}._-]*/u);
      const tag = ctx.matchBefore(/#[\p{L}\p{N}_-]*/u);
      const s = live.current.suggest;
      const opts = (list: string[], wrapIt: (x: string) => string): Completion[] =>
        list.map((l) => ({ label: l, apply: wrapIt(l) }));
      if (wiki)
        return { from: wiki.from, options: opts(await s.records(wiki.text.slice(2)), (l) => `[[${l}]]`) };
      if (at && (at.from === 0 || /\s/.test(ctx.state.sliceDoc(at.from - 1, at.from))))
        return { from: at.from, options: opts(await s.objects(at.text.slice(1)), (l) => `[[${l}]]`) };
      if (tag && (tag.from === 0 || /\s/.test(ctx.state.sliceDoc(tag.from - 1, tag.from))))
        return { from: tag.from, options: opts(await s.tags(tag.text.slice(1)), (l) => `#${l}`) };
      return null;
    };
    const v = new EditorView({
      parent: box.current,
      state: EditorState.create({
        doc: p.value,
        extensions: [
          history(),
          EditorView.lineWrapping,
          markdown(),
          syntaxHighlighting(defaultHighlightStyle),
          ph(p.placeholder),
          autocompletion({ override: [source], icons: false }),
          keymap.of([
            { key: "Mod-b", run: (v) => wrap(v, "**") },
            { key: "Mod-i", run: (v) => wrap(v, "*") },
            { key: "Mod-k", run: (v) => wrap(v, "[[", "]]") },
            { key: "Mod-Enter", run: () => (live.current.onSubmit?.(), true) },
            ...defaultKeymap,
            ...historyKeymap,
          ]),
          EditorView.contentAttributes.of({ "aria-label": p.label, "aria-multiline": "true" }),
          EditorView.updateListener.of((u) => {
            if (u.docChanged) live.current.onChange(u.state.doc.toString());
          }),
        ],
      }),
    });
    view.current = v;
    return () => v.destroy();
    // редактор создаётся один раз; внешние смены значения — эффектом ниже
    // biome-ignore lint/correctness/useExhaustiveDependencies: создаём один раз на монтирование
  }, []);

  useEffect(() => {
    const v = view.current;
    if (v && v.state.doc.toString() !== p.value)
      v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: p.value } });
  }, [p.value]);

  useImperativeHandle(ref, () => ({
    wrap: (b, a) => view.current && wrap(view.current, b, a),
    line: (prefix) => view.current && line(view.current, prefix),
    focus: () => view.current?.focus(),
  }));

  return <div ref={box} className="cm cm--edit" />;
});

export default BodyEditor;
