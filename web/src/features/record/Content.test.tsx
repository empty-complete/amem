import { render, screen, within } from "@testing-library/react";
import { RecordContent } from "./Content";

const table = {
  columns: [
    { code: "date", label: { ru: "Дата" } },
    { code: "v2", label: { ru: "В-2" }, unit: "%" },
    { code: "t", label: { ru: "T" }, unit: "Cel" },
  ],
  rows: [["03.11", 99, -2.4], { date: "08.11", v2: 87 }],
};

test("таблица: единицы в заголовках, числа по-русски, строка-объект по кодам, пустое — тире", () => {
  render(<RecordContent content={{ table }} />);
  const region = screen.getByRole("region", { name: "Таблица" });
  const cols = within(region)
    .getAllByRole("columnheader")
    .map((c) => c.textContent);
  expect(cols).toEqual(["Дата", "В-2, %", "T, °C"]);
  const rows = within(region).getAllByRole("row").slice(1);
  const first = within(rows[0] as HTMLElement)
    .getAllByRole("cell")
    .map((c) => c.textContent);
  expect(first.slice(0, 2)).toEqual(["03.11", "99"]);
  expect(first[2]).toMatch(/^[-−]2,4$/);
  expect(
    within(rows[1] as HTMLElement)
      .getAllByRole("cell")
      .map((c) => c.textContent),
  ).toEqual(["08.11", "87", "—"]);
  expect(screen.getByRole("region", { name: "Таблица, листается" })).toHaveAttribute("tabindex", "0");
});

test("формула: запись словами до загрузки KaTeX и обозначения с единицами", () => {
  render(
    <RecordContent
      content={{
        formula: {
          latex: "T_d = b",
          plain: "Td = b",
          symbols: [{ symbol: "RH", label: { ru: "относительная влажность" }, unit: "%" }],
        },
      }}
    />,
  );
  const f = screen.getByRole("region", { name: "Формула" });
  expect(f).toHaveTextContent("Td = b");
  expect(within(f).getByRole("term")).toHaveTextContent("RH");
  expect(within(f).getByRole("definition")).toHaveTextContent("относительная влажность, %");
});

test("без формулы и таблицы — ничего", () => {
  const { container } = render(<RecordContent content={{}} />);
  expect(container).toBeEmptyDOMElement();
});
