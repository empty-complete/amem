import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import objects from "../../mocks/fixtures/objects-b.json";
import { renderWithApp } from "../../test/render";
import { ObjectPage, unparsed } from "./ObjectPage";
import { parseRange } from "./SheetPreview";

vi.mock("./PdfPage", () => ({
  default: ({ page, quotes }: { page: number; quotes: string[] }) => (
    <div>
      PDF, страница {page}, цитат {quotes.length}
    </div>
  ),
}));

const MANUAL = "0193b7c2-5e1a-7d40-9f2e-0000000000a1";
const SHEET = "0193b7c2-5e1a-7d40-9f2e-0000000000a2";

test("диапазон A1 в номера", () => {
  expect(parseRange("B4:C9")).toEqual({ c1: 2, c2: 3, r1: 4, r2: 9 });
  expect(parseRange("AA10")).toEqual({ c1: 27, c2: 27, r1: 10, r2: 10 });
  expect(parseRange("нет")).toBeNull();
});

test("не разобрано: листы без цитат при частичном разборе", () => {
  expect(unparsed(objects[SHEET] as never, String)).toEqual(["Т-1", "Д-3"]);
  expect(unparsed(objects[MANUAL] as never, (n) => `с. ${n}`)).toEqual(["с. 1"]);
});

test("источник-таблица: свойства, превью листа с цитируемым диапазоном, ссылки сюда", async () => {
  await renderWithApp(<ObjectPage objectId={SHEET} />, `/object/${SHEET}`);
  expect(await screen.findByRole("heading", { level: 1, name: "Наблюдения ноябрь" })).toBeInTheDocument();
  expect(screen.getByText("~/Документы/Метео/Наблюдения_ноябрь.xlsx")).toBeInTheDocument();
  const table = await screen.findByRole("table", { name: "Лист В-2" });
  const cited = within(table)
    .getAllByRole("cell")
    .filter((c) => c.hasAttribute("data-cited"));
  expect(cited).toHaveLength(12);
  expect(cited[0]).toHaveTextContent("99");
  expect(screen.getByText(/B4:C9 цитирует «В-2 завышает влажность при обмерзании»/)).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Ссылаются на этот файл" })).toHaveTextContent("лист В-2, B4:C9");
  expect(screen.getByRole("region", { name: "Не разобрано" })).toHaveTextContent("Т-1");
});

test("«Скопировать путь» пишет в буфер и говорит об этом", async () => {
  const user = userEvent.setup();
  const write = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue(undefined);
  await renderWithApp(<ObjectPage objectId={SHEET} />, `/object/${SHEET}`);
  await user.click(await screen.findByRole("button", { name: "Скопировать путь" }));
  expect(write).toHaveBeenCalledWith("~/Документы/Метео/Наблюдения_ноябрь.xlsx");
  await waitFor(() => expect(screen.getByText("Путь скопирован")).toBeInTheDocument());
});

test("PDF: страница с цитатами и бриф из заметки о файле", async () => {
  await renderWithApp(<ObjectPage objectId={MANUAL} />, `/object/${MANUAL}`);
  expect(await screen.findByText("PDF, страница 2, цитат 3")).toBeInTheDocument();
  expect(await screen.findByRole("region", { name: "О файле" })).toHaveTextContent("раздел 4.2");
});

test("нет объекта — ошибка словами", async () => {
  await renderWithApp(<ObjectPage objectId="нет" />, "/object/нет");
  expect(await screen.findByRole("alert")).toHaveTextContent("Объекта нет нет");
});
