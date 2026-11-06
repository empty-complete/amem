import { render, screen } from "@testing-library/react";
import { familyOf } from "./families";
import { StatusText } from "./StatusText";

test("статус передаётся словом и значком, а не только цветом", () => {
  const { container } = render(<StatusText status="needs_review" />);
  expect(screen.getByText("Ждёт проверки")).toBeInTheDocument();
  expect(container.querySelector("svg[aria-hidden='true']")).not.toBeNull();
});

test("семьи знания: источники, работа, объекты", () => {
  expect(familyOf("parameter")).toBe("source");
  expect(familyOf("decision")).toBe("work");
  expect(familyOf("note")).toBe("work");
  expect(familyOf("artifact", "entity")).toBe("object");
  expect(familyOf("something-new")).toBe("work");
});
