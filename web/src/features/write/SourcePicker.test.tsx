import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithApp } from "../../test/render";
import { SourcePicker } from "./SourcePicker";

vi.mock("../source/PdfPage", () => ({
  default: ({ page, onSelectText }: { page: number; onSelectText?: (s: string) => void }) => (
    <button type="button" onClick={() => onSelectText?.("Погрешность ±2 % в диапазоне от 10 до 90 %")}>
      выделить на странице {page}
    </button>
  ),
}));

test("PDF: найти файл, выделить цитату на странице — источник с цитатой и страницей", async () => {
  const user = userEvent.setup();
  const pick = vi.fn();
  await renderWithApp(<SourcePicker open onClose={() => {}} onPick={pick} />);
  await user.type(screen.getByRole("searchbox", { name: "Найти файл по имени или пути" }), "Руковод");
  await user.click(await screen.findByRole("button", { name: /Руководство_МС-1.pdf/ }));
  await user.click(screen.getByRole("button", { name: "Следующая страница" }));
  await user.click(await screen.findByRole("button", { name: "выделить на странице 2" }));
  expect(screen.getByRole("textbox", { name: /Цитата/ })).toHaveValue(
    "Погрешность ±2 % в диапазоне от 10 до 90 %",
  );
  await user.click(screen.getByRole("button", { name: "Готово" }));
  expect(pick).toHaveBeenCalledWith(
    expect.objectContaining({
      object_version: 2,
      selectors: [{ type: "page", value: "2" }],
      quote: "Погрешность ±2 % в диапазоне от 10 до 90 %",
    }),
  );
});

test("таблица: протяжка по ячейкам — лист и диапазон", async () => {
  const user = userEvent.setup();
  const pick = vi.fn();
  await renderWithApp(<SourcePicker open onClose={() => {}} onPick={pick} />);
  await user.click(await screen.findByRole("button", { name: /Наблюдения_ноябрь.xlsx/ }));
  await user.click(await screen.findByRole("tab", { name: "В-2" }));
  const table = await screen.findByRole("table", { name: "Лист В-2" });
  const cell = (txt: string) => within(table).getAllByRole("cell", { name: txt })[0] as HTMLElement;
  fireEvent.pointerDown(cell("99"));
  fireEvent.pointerEnter(cell("85"));
  fireEvent.pointerUp(cell("85"));
  expect(screen.getByRole("textbox", { name: "Диапазон" })).toHaveValue("B4:C9");
  await user.click(screen.getByRole("button", { name: "Готово" }));
  expect(pick).toHaveBeenCalledWith(
    expect.objectContaining({
      selectors: [
        { type: "sheet", value: "В-2" },
        { type: "range", value: "B4:C9" },
      ],
    }),
  );
});

// загрузку файла (multipart) проверяет e2e в браузере: в jsdom/undici MSW обрывает поток FormData
