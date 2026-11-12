// Редактор тела: CodeMirror 6 с подсветкой Markdown, панелью, меню по правой кнопке и клавишами; подсказки [[ @ #.
// Лениво.
import { autocompletion, type Completion, type CompletionContext } from "@codemirror/autocomplete";
import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { markdown } from "@codemirror/lang-markdown";
import { defaultHighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { EditorSelection, EditorState } from "@codemirror/state";
import { EditorView, keymap, placeholder as ph } from "@codemirror/view";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { livePreview } from "./livePreview";

export interface BodyEditorApi {
  wrap: (before: string, after?: string) => void;
  line: (prefix: string) => void;
  heading: (level: number) => void;
  focus: () => void;
  /** Выделенный текст («» — ничего не выделено). */
  selection: () => string;
  /** Заменить выделение (или вставить в курсор) текстом. */
  insert: (text: string) => void;
  selectAll: () => void;
}

/** Подсказка-запись: ссылка и подпись; выбор вставляет [[подпись]] и сообщает ссылку (onPick). */
export type Hit = { ref: string; label: string };

export interface Suggest {
  records: (q: string) => Promise<Hit[]>;
  objects: (q: string) => Promise<Hit[]>;
  tags: (q: string) => Promise<string[]>;
  /** Выбрана подсказка: via «[[» — запись, «@» — объект (его кладут в «О чём»). */
  onPick?: (hit: Hit, via: "[[" | "@") => void;
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

/** Строки, которых касается выделение. */
function lines(view: EditorView) {
  const out = new Map<number, { from: number; text: string }>();
  for (const r of view.state.selection.ranges) {
    const a = view.state.doc.lineAt(r.from).number;
    const b = view.state.doc.lineAt(r.to).number;
    for (let n = a; n <= b; n++) {
      const l = view.state.doc.line(n);
      out.set(n, { from: l.from, text: l.text });
    }
  }
  return [...out.values()];
}

/** Приставка строк (цитата, список): у всех выделенных строк есть — снять, иначе поставить. */
function line(view: EditorView, prefix: string) {
  const ls = lines(view);
  const all = ls.every((l) => l.text.startsWith(prefix));
  view.dispatch({
    changes: ls.map((l) =>
      all ? { from: l.from, to: l.from + prefix.length } : { from: l.from, insert: prefix },
    ),
  });
  view.focus();
  return true;
}

/** Заголовок уровня 1–3: прежний знак заголовка заменяется; тот же уровень — снимается. */
function heading(view: EditorView, level: number) {
  const mark = `${"#".repeat(level)} `;
  view.dispatch({
    changes: lines(view).map((l) => {
      const old = l.text.match(/^#{1,6} /)?.[0] ?? "";
      return { from: l.from, to: l.from + old.length, insert: old === mark ? "" : mark };
    }),
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
    /** Правая кнопка на выделении — меню оформления в точке щелчка; без выделения — меню браузера. */
    onMenu?: (at: { x: number; y: number }) => void;
    /** Живой предпросмотр: разметка скрыта вне строки с курсором (тело записи, не исходник). */
    live?: boolean;
  }
>(function BodyEditor(p, ref) {
  const box = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const live = useRef(p);
  live.current = p;

  // редактор создаётся один раз; внешние смены значения — эффектом ниже
  // biome-ignore lint/correctness/useExhaustiveDependencies: создаём один раз на монтирование
  useEffect(() => {
    if (!box.current) return;
    const source = async (ctx: CompletionContext) => {
      const wiki = ctx.matchBefore(/\[\[[^\]\n]*/);
      const at = ctx.matchBefore(/@[\p{L}\p{N}._-]*/u);
      const tag = ctx.matchBefore(/#[\p{L}\p{N}_-]*/u);
      const s = live.current.suggest;
      // ссылка на запись: вставить [[подпись]] (закрывающие «]]», если они уже стоят, — заменить) и сообщить ссылку
      const links = (list: Hit[], via: "[[" | "@"): Completion[] =>
        list.map((h) => ({
          label: h.label,
          apply: (v, _c, from, to) => {
            const tail = v.state.sliceDoc(to, to + 2) === "]]" ? to + 2 : to;
            const insert = `[[${h.label}]]`;
            v.dispatch({ changes: { from, to: tail, insert }, selection: { anchor: from + insert.length } });
            live.current.suggest.onPick?.(h, via);
          },
        }));
      // служба уже отобрала подсказки по набранному: свой фильтр CodeMirror сравнивал бы «@Камп» с подписью и
      // прятал всё (filter: false); список пересобирается на каждом знаке
      if (wiki)
        return { from: wiki.from, filter: false, options: links(await s.records(wiki.text.slice(2)), "[[") };
      if (at && (at.from === 0 || /\s/.test(ctx.state.sliceDoc(at.from - 1, at.from))))
        return { from: at.from, filter: false, options: links(await s.objects(at.text.slice(1)), "@") };
      if (tag && (tag.from === 0 || /\s/.test(ctx.state.sliceDoc(tag.from - 1, tag.from))))
        return {
          from: tag.from,
          filter: false,
          options: (await s.tags(tag.text.slice(1))).map((l) => ({ label: `#${l}`, apply: `#${l}` })),
        };
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
          p.live ? livePreview : [],
          ph(p.placeholder),
          autocompletion({ override: [source], icons: false }),
          keymap.of([
            { key: "Mod-b", run: (v) => wrap(v, "**") },
            { key: "Mod-i", run: (v) => wrap(v, "*") },
            { key: "Mod-k", run: (v) => wrap(v, "[[", "]]") },
            {
              key: "Mod-Enter",
              run: () => {
                live.current.onSubmit?.();
                return true;
              },
            },
            ...defaultKeymap,
            ...historyKeymap,
          ]),
          EditorView.domEventHandlers({
            contextmenu: (e) => {
              // меню — всегда, как в Obsidian: без выделения часть пунктов недоступна
              if (!live.current.onMenu) return false;
              e.preventDefault();
              live.current.onMenu({ x: e.clientX, y: e.clientY });
              return true;
            },
          }),
          EditorView.contentAttributes.of({ "aria-label": p.label, "aria-multiline": "true" }),
          EditorView.updateListener.of((u) => {
            if (u.docChanged) live.current.onChange(u.state.doc.toString());
          }),
        ],
      }),
    });
    view.current = v;
    return () => v.destroy();
  }, []);

  useEffect(() => {
    const v = view.current;
    if (v && v.state.doc.toString() !== p.value)
      v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: p.value } });
  }, [p.value]);

  useImperativeHandle(ref, () => ({
    wrap: (b, a) => view.current && wrap(view.current, b, a),
    line: (prefix) => view.current && line(view.current, prefix),
    heading: (level) => view.current && heading(view.current, level),
    selection: () => {
      const v = view.current;
      if (!v) return "";
      return v.state.selection.ranges.map((r) => v.state.sliceDoc(r.from, r.to)).join("\n");
    },
    insert: (text) => {
      const v = view.current;
      if (!v) return;
      v.dispatch(v.state.replaceSelection(text));
      v.focus();
    },
    selectAll: () => {
      const v = view.current;
      if (!v) return;
      v.dispatch({ selection: { anchor: 0, head: v.state.doc.length } });
      v.focus();
    },
    focus: () => view.current?.focus(),
  }));

  return <div ref={box} className="cm cm--edit" />;
});

export default BodyEditor;
