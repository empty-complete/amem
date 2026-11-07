import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MoveDialog } from "../../features/write/MoveDialog";
import { resetQueue, UNDO_MS } from "../../features/write/submitQueue";
import { db } from "../../mocks/db";
import { renderWithApp } from "../../test/render";
import { Folders } from "./Folders";

afterEach(() => {
  resetQueue();
  vi.useRealTimers();
});

const nav = () => screen.getByRole("navigation", { name: "Папки" });

test("новая папка на месте; такая уже есть — словами", async () => {
  const user = userEvent.setup();
  await renderWithApp(<Folders />);
  await user.click(await screen.findByRole("button", { name: "Папка" }));
  await user.type(screen.getByRole("textbox", { name: "Имя новой папки" }), "Обходы{Enter}");
  expect(await within(nav()).findByRole("link", { name: /Обходы/ })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Папка" }));
  await user.type(screen.getByRole("textbox", { name: "Имя новой папки" }), "Архив{Enter}");
  expect(await screen.findByRole("alert")).toHaveTextContent("Такая папка уже есть");
});

test("переименование переносит записи; непустую не удалить", async () => {
  const user = userEvent.setup();
  await renderWithApp(<Folders />);
  await user.click(await screen.findByRole("button", { name: "Папка «Архив»: действия" }));
  await user.click(await screen.findByRole("menuitem", { name: "Переименовать" }));
  const input = screen.getByRole("textbox", { name: "Переименовать" });
  await user.clear(input);
  await user.type(input, "Старое{Enter}");
  expect(await within(nav()).findByRole("link", { name: /Старое/ })).toBeInTheDocument();
  expect(db.records.filter((r) => r.folder?.startsWith("Старое")).length).toBe(2);
  await user.click(screen.getByRole("button", { name: "Папка «Старое»: действия" }));
  await user.click(await screen.findByRole("menuitem", { name: "Удалить" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("В папке есть записи");
});

test("«Переместить в папку» — с окном отмены", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  const ref = "atm:0193b7c2-5e1a-7d40-9f2e-00000000001e";
  await renderWithApp(<MoveDialog recordRef={ref} current={null} open onClose={() => {}} />);
  await user.click(await screen.findByRole("radio", { name: "Архив" }));
  await user.click(screen.getByRole("button", { name: "Переместить в папку" }));
  expect(db.records.find((r) => r.ref === ref)?.folder).toBeNull();
  await act(() => vi.advanceTimersByTimeAsync(UNDO_MS + 50));
  expect(db.records.find((r) => r.ref === ref)?.folder).toBe("Архив");
});
