import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithApp } from "../../test/render";
import { RecordPage } from "../record/RecordPage";
import { resetQueue, UNDO_MS } from "./submitQueue";

vi.mock("../sky/SkyCanvas", () => ({ default: () => null }));
vi.mock("../source/PdfPage", () => ({ default: () => null }));

const N1 = "atm:0193b7c2-5e1a-7d40-9f2e-00000000001e";
const A3 = "atm:0193b7c2-5e1a-7d40-9f2e-00000000000b";

afterEach(() => {
  resetQueue();
  vi.useRealTimers();
});

test("своя заметка правится: заголовок → новая ревизия после окна отмены", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  await renderWithApp(<RecordPage recordRef={N1} view="human" />, `/atom/${N1}`);
  await user.click(await screen.findByRole("button", { name: /^Править, (⌘|Ctrl\+)E$/ }));
  const title = await screen.findByRole("textbox", { name: "Заголовок" });
  await user.clear(title);
  await user.type(title, "Проверить мачту после бури");
  await user.click(screen.getByRole("button", { name: "Записать" }));
  await act(() => vi.advanceTimersByTimeAsync(UNDO_MS + 50));
  expect(
    await screen.findByRole("heading", { level: 1, name: "Проверить мачту после бури" }),
  ).toBeInTheDocument();
  expect(screen.getByText("ревизия 2")).toBeInTheDocument();
});

test("пустой заголовок — замечание проверки у поля, правка снова открыта", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  await renderWithApp(<RecordPage recordRef={N1} view="human" />, `/atom/${N1}`);
  await user.click(await screen.findByRole("button", { name: /^Править, (⌘|Ctrl\+)E$/ }));
  await user.clear(await screen.findByRole("textbox", { name: "Заголовок" }));
  await user.click(screen.getByRole("button", { name: "Записать" }));
  await act(() => vi.advanceTimersByTimeAsync(UNDO_MS + 50));
  expect(await screen.findByText("Нужен заголовок")).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "Заголовок" })).toHaveAttribute("aria-invalid", "true");
});

test("запись модели правится: подсказка о статусе; «Поставить на проверку» — в меню «Ещё»", async () => {
  const user = userEvent.setup();
  await renderWithApp(<RecordPage recordRef={A3} view="human" />, `/atom/${A3}`);
  await user.click(await screen.findByRole("button", { name: "Ещё" }));
  expect(await screen.findByRole("menuitem", { name: "Поставить на проверку" })).toBeInTheDocument();
  expect(screen.getByRole("menuitem", { name: "Записать своё рядом" })).toBeInTheDocument();
  await user.keyboard("{Escape}");
  await user.click(screen.getByRole("button", { name: /^Править, (⌘|Ctrl\+)E$/ }));
  expect(await screen.findByText(/статус записи не изменится/)).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "Заголовок" })).toBeInTheDocument();
});

test("смена вида подставляет форму шаблона; своё свойство переживает исходник", async () => {
  const user = userEvent.setup();
  await renderWithApp(<RecordPage recordRef={N1} view="human" />, `/atom/${N1}`);
  await user.click(await screen.findByRole("button", { name: /^Править, (⌘|Ctrl\+)E$/ }));
  await user.click(await screen.findByRole("button", { name: "Вид: Заметка. Сменить" }));
  await user.click(await screen.findByRole("button", { name: "Решение" }));
  expect(await screen.findByLabelText("Действует с")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Свойство" }));
  await user.type(screen.getByRole("textbox", { name: "Имя свойства" }), "Срочность{Enter}");
  await user.type(screen.getByRole("textbox", { name: "Срочность" }), "высокая");
  const kindRow = () =>
    screen.getByText("Вид", { selector: ".editor__kind > span" }).parentElement as HTMLElement;
  await user.click(within(kindRow()).getByRole("button", { name: "Исходник" }));
  const src = await screen.findByLabelText("Исходник записи");
  await waitFor(() => expect(src).toHaveTextContent("срочность: высокая"));
  await user.click(within(kindRow()).getByRole("button", { name: "Исходник" }));
  expect(await screen.findByRole("textbox", { name: "Срочность" })).toHaveValue("высокая");
});
