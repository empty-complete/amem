import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef } from "react";
import { renderWithApp } from "../../test/render";
import { CardPage } from "../card/CardPage";
import { placeStore } from "./place";
import { QuickWrite } from "./QuickWrite";
import { resetQueue, UNDO_MS } from "./submitQueue";
import { UndoToasts } from "./UndoToast";

vi.mock("../sky/SkyCanvas", () => ({ default: () => null }));

const E3 = "ent:0193b7c2-5e1a-7d40-9f2e-000000000003";

function Harness() {
  const btn = useRef<HTMLButtonElement>(null);
  return (
    <>
      <button ref={btn} type="button">
        Записать
      </button>
      <QuickWrite trigger={btn} />
      <UndoToasts />
    </>
  );
}

afterEach(() => {
  resetQueue();
  placeStore.openQuick(false);
  placeStore.setStar(null);
  vi.useRealTimers();
});

test("окно N: вид из текста, «О чём» из места, Enter — тост, отмена — ничего", async () => {
  const user = userEvent.setup();
  await renderWithApp(<Harness />, `/entity/${E3}`);
  act(() => placeStore.openQuick(true));
  const dlg = await screen.findByRole("dialog", { name: "Новая запись" });
  expect(await within(dlg).findByText("О чём: Датчик влажности В-2")).toBeInTheDocument();
  await user.type(within(dlg).getByRole("textbox", { name: "Текст записи" }), "Нужен ли обогрев зимой?");
  expect(within(dlg).getByRole("button", { name: /Вид: Вопрос/ })).toBeInTheDocument();
  await user.keyboard("{Enter}");
  expect(await screen.findByText("Записано: вопрос")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Отменить" }));
  expect(screen.queryByText("Записано: вопрос")).not.toBeInTheDocument();
});

test("плашка вида меняет выведенный вид одним нажатием", async () => {
  const user = userEvent.setup();
  await renderWithApp(<Harness />, "/");
  act(() => placeStore.openQuick(true));
  const dlg = await screen.findByRole("dialog", { name: "Новая запись" });
  await user.type(within(dlg).getByRole("textbox", { name: "Текст записи" }), "Проверить отвес");
  await user.click(within(dlg).getByRole("button", { name: /Вид: Заметка/ }));
  await user.click(await screen.findByRole("button", { name: "Урок" }));
  expect(within(dlg).getByRole("button", { name: /Вид: Урок/ })).toBeInTheDocument();
});

test("объект: пустое обязательное поле — значение → «известно», «Не знаю» → «Вопрос открыт», «Принять» умолчание", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  await renderWithApp(<CardPage entityRef={E3} />, `/entity/${E3}`);
  const cond = await screen.findByRole("region", { name: "Условия" });
  await user.click(within(cond).getByRole("button", { name: "Нужно" }));
  await user.type(within(cond).getByRole("textbox", { name: "Рабочая температура" }), "-40{Enter}");
  const poll = screen.getByRole("region", { name: "Опрос" });
  await user.click(within(poll).getByRole("button", { name: "Принять" }));
  await act(() => vi.advanceTimersByTimeAsync(UNDO_MS + 100));
  expect(await within(cond).findByText("−40 °C")).toBeInTheDocument();
  expect(await within(poll).findByText("60 с")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: /Известно 4 из 7/ })).toBeInTheDocument();
});

test("объект: «Добавить заметку» — строка в списке сразу, запись после окна", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  await renderWithApp(<CardPage entityRef={E3} />, `/entity/${E3}`);
  await user.type(
    await screen.findByRole("textbox", { name: "Добавить заметку" }),
    "Решили поставить козырёк{Enter}",
  );
  const notes = screen.getByRole("region", { name: "Заметки и решения" });
  expect(within(notes).getByText("Решили поставить козырёк")).toBeInTheDocument();
  expect(within(notes).getByText("записывается")).toBeInTheDocument();
  await act(() => vi.advanceTimersByTimeAsync(UNDO_MS + 100));
  expect(await within(notes).findByRole("link", { name: /Решили поставить козырёк/ })).toBeInTheDocument();
});
