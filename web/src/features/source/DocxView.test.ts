import { markQuote } from "./DocxView";

test("цитата подсвечивается в отрисованном DOCX, даже с другими пробелами и регистром", () => {
  const root = document.createElement("div");
  root.innerHTML = "<h1>Мачта</h1><p>Растяжки   проверять после каждого шторма и записывать.</p>";
  const mark = markQuote(root, "растяжки проверять после каждого");
  expect(mark?.tagName).toBe("MARK");
  expect(mark?.textContent).toBe("Растяжки   проверять после каждого");
  expect(root.querySelector("p")?.textContent).toBe(
    "Растяжки   проверять после каждого шторма и записывать.",
  );
  expect(markQuote(root, "этого в документе нет")).toBeNull();
});
