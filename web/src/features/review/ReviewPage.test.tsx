import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { db } from "../../mocks/db";
import { renderWithApp } from "../../test/render";
import { resetQueue, UNDO_MS } from "../write/submitQueue";
import { UndoToasts } from "../write/UndoToast";
import { ReviewPage } from "./ReviewPage";

vi.mock("../sky/SkyCanvas", () => ({ default: () => null }));
vi.mock("../source/PdfPage", () => ({ default: () => null }));

const ID = (n: number) => `5f0c2a8e-1d3b-4c6a-9e7f-0a1b2c3d4e${n.toString(16).padStart(2, "0")}`;
const EDIT = ID(1);
const SRC = ID(2);
const DOUBT = ID(0x5f);

afterEach(() => {
  resetQueue();
  vi.useRealTimers();
});

const page = (id?: string) =>
  renderWithApp(
    <>
      <ReviewPage itemId={id} state="open" />
      <UndoToasts />
    </>,
    id ? `/review/${id}` : "/review",
  );

test("список: причины словами; правка — сравнение по полям с подсветкой", async () => {
  await page(EDIT);
  const list = await screen.findByRole("listbox", { name: "Очередь проверки" });
  expect(within(list).getAllByRole("option")).toHaveLength(8);
  expect(within(list).getByRole("option", { selected: true })).toHaveTextContent("правка");
  expect(await screen.findByText("Правка: принять новую версию?")).toBeInTheDocument();
  const diff = await screen.findByRole("region", { name: "Что изменится" });
  expect(diff.querySelector("ins")?.textContent).toContain("сильного");
});

test("источник изменился — две версии; сомнение модели — вердикт и уверенность", async () => {
  const { router } = await page(SRC);
  const vers = await screen.findByRole("region", { name: "Источник изменился" });
  expect(vers).toHaveTextContent("Было (версия 1)");
  expect(vers.querySelector("ins")?.textContent).toContain("40");
  await act(() => router.navigate({ to: "/review/$itemId", params: { itemId: DOUBT } }));
});

test("Y — подтверждено с окном отмены, открыт следующий; «Отменить» возвращает", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  const { router } = await page(EDIT);
  await screen.findByRole("region", { name: "Что изменится" });
  await user.keyboard("y");
  expect(await screen.findByText("Подтверждено")).toBeInTheDocument();
  expect(router.state.location.pathname).not.toContain(EDIT);
  await user.click(screen.getByRole("button", { name: "Отменить" }));
  expect(within(screen.getByRole("listbox")).getAllByRole("option")).toHaveLength(8);
  await act(() => vi.advanceTimersByTimeAsync(UNDO_MS + 100));
  expect(db.reviewItems.find((i) => i.id === EDIT)?.state).toBe("queued");
});

test("N — отклонено и записано после окна; запись получает статус «Отклонено»", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  await page(DOUBT);
  await screen.findByRole("region", { name: "Вердикт модели" });
  await user.keyboard("n");
  await act(() => vi.advanceTimersByTimeAsync(UNDO_MS + 100));
  expect(db.reviewItems.find((i) => i.id === DOUBT)?.state).toBe("done");
  expect(db.records.find((r) => r.ref === "atm:0193b7c2-5e1a-7d40-9f2e-00000000000b")?.status).toBe(
    "rejected",
  );
});

test("уже решено — строка «Уже решено: …»", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  await page(SRC);
  await screen.findByRole("region", { name: "Источник изменился" });
  const it = db.reviewItems.find((i) => i.id === SRC);
  if (it) it.state = "done";
  await user.click(screen.getByRole("button", { name: "Подтвердить, Y" }));
  await act(() => vi.advanceTimersByTimeAsync(UNDO_MS + 100));
  expect(await screen.findByText(/Уже решено:/)).toBeInTheDocument();
});

test("пустая очередь — словами", async () => {
  for (const i of db.reviewItems) i.state = "done";
  await page();
  expect(await screen.findByText(/^Вас ничего не ждёт/)).toBeInTheDocument();
});

test("вкладка «Разбирает модель»: смысловая проверка и последний проход проверяющего", async () => {
  const first = db.reviewItems[0];
  if (!first) throw new Error("нет образцов");
  db.reviewItems.push({ ...first, id: ID(0x70), reason: "semantic", label: "Смысл для модели" });
  await renderWithApp(<ReviewPage state="open" who="model" />, "/review?who=model");
  expect(await screen.findByRole("tab", { name: /^Разбирает модель/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(
    await screen.findByText(/^Смысловую проверку разбирает проверяющая модель\. Последний проход/),
  ).toBeInTheDocument();
  const list = await screen.findByRole("listbox", { name: "Очередь проверки" });
  expect(within(list).getAllByRole("option")).toHaveLength(1);
  expect(within(list).getByText("Смысл для модели")).toBeInTheDocument();
});

test("вкладки: «Ждут вас» — решает человек, «Разбирает модель» — смысловая проверка; у кнопок — что будет", async () => {
  const first = db.reviewItems[0];
  if (!first) throw new Error("нет образцов");
  db.reviewItems.push({ ...first, id: ID(0x70), reason: "semantic", label: "Смысл для модели" });
  await page(EDIT);
  const you = await screen.findByRole("tab", { name: /^Ждут вас/ });
  expect(you).toHaveAttribute("aria-selected", "true");
  const list = await screen.findByRole("listbox", { name: "Очередь проверки" });
  expect(within(list).queryByText("Смысл для модели")).not.toBeInTheDocument();
  expect(screen.getByText(/^Здесь то, что решает только человек/)).toBeInTheDocument();
  expect(screen.getByText("Подтвердить — правка станет текущей версией записи.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Отклонить, N" })).toHaveAccessibleDescription(
    "Отклонить — правка не примется, останется прежняя версия.",
  );
  expect(screen.getByRole("tab", { name: /^Разбирает модель/ })).toHaveAttribute("aria-selected", "false");
});
