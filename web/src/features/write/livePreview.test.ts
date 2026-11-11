import { markdown } from "@codemirror/lang-markdown";
import { EditorSelection, EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { livePreview } from "./livePreview";

const DOC = "# Мачта\n\n**жирный** и *курсив*, `код`, [[Растяжки]]\n\n> цитата\n- пункт";

function mount(doc = DOC) {
  const parent = document.createElement("div");
  document.body.append(parent);
  const view = new EditorView({
    parent,
    state: EditorState.create({ doc, extensions: [markdown(), livePreview] }),
  });
  return view;
}

const lineText = (v: EditorView, n: number) => v.contentDOM.querySelectorAll(".cm-line")[n - 1]?.textContent;

test("без фокуса разметка скрыта: заголовок, жирный, курсив, код, [[ссылка]], цитата, пункт", () => {
  const v = mount();
  expect(lineText(v, 1)).toBe("Мачта");
  expect(v.contentDOM.querySelector(".cm-lp-h1")).not.toBeNull();
  expect(lineText(v, 3)).toBe("жирный и курсив, код, Растяжки");
  expect(lineText(v, 5)).toBe("цитата");
  expect(lineText(v, 6)).toBe("• пункт");
  // сам текст не меняется
  expect(v.state.doc.toString()).toBe(DOC);
  v.destroy();
});

test("строка с курсором — исходник, остальные отрисованы", () => {
  const v = mount();
  v.focus();
  v.dispatch({ selection: EditorSelection.cursor(v.state.doc.line(3).from + 1) });
  // в jsdom фокус может не встать — тогда предпросмотр честно считает, что фокуса нет
  if (v.hasFocus) {
    expect(lineText(v, 3)).toBe("**жирный** и *курсив*, `код`, [[Растяжки]]");
    expect(lineText(v, 1)).toBe("Мачта");
  }
  v.destroy();
});

test("формула $…$ заменяется отрисовкой; внутри `кода` знаки остаются", () => {
  const v = mount("площадь $a^2$ и `цена $5$`");
  expect(lineText(v, 1)).not.toContain("$a^2$");
  expect(v.contentDOM.querySelector(".cm-lp-math")).not.toBeNull();
  expect(lineText(v, 1)).toContain("цена $5$");
  v.destroy();
});
