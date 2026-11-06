// Исходник записи только для чтения: CodeMirror с подсветкой Markdown. Модуль грузится лениво.
import { markdown } from "@codemirror/lang-markdown";
import { defaultHighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { useEffect, useRef } from "react";

export default function SourceView({ doc, label }: { doc: string; label: string }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!box.current) return;
    const view = new EditorView({
      parent: box.current,
      state: EditorState.create({
        doc,
        extensions: [
          EditorState.readOnly.of(true),
          EditorView.editable.of(false),
          EditorView.lineWrapping,
          EditorView.contentAttributes.of({ "aria-label": label, "aria-readonly": "true" }),
          markdown(),
          syntaxHighlighting(defaultHighlightStyle),
        ],
      }),
    });
    return () => view.destroy();
  }, [doc, label]);
  return <div ref={box} className="cm" />;
}
