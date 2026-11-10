import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef } from "react";
import { db } from "../../mocks/db";
import { renderWithApp } from "../../test/render";
import { CardPage } from "../card/CardPage";
import { draftKey, loadDraft } from "./drafts";
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
  window.localStorage.clear();
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
  const poll = await screen.findByRole("region", { name: "Опрос" });
  await user.click(within(poll).getByRole("button", { name: "Принять" }));
  await act(() => vi.advanceTimersByTimeAsync(UNDO_MS + 100));
  expect(await within(cond).findByText("−40 °C")).toBeInTheDocument();
  expect(await within(poll).findByText("60 с")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: /Известно 4 из 7/ })).toBeInTheDocument();
});

test("объект: «Добавить заметку» — строка не пишет в базу, а открывает редактор с черновиком", async () => {
  const user = userEvent.setup();
  const { router } = await renderWithApp(<CardPage entityRef={E3} />, `/entity/${E3}`);
  const before = db.records.length;
  await user.type(
    await screen.findByRole("textbox", { name: "Добавить заметку" }),
    "Решили поставить козырёк{Enter}",
  );
  await waitFor(() => expect(router.state.location.pathname).toBe("/new"));
  expect(router.state.location.search).toMatchObject({ about: E3, kind: "decision" });
  expect(db.records.length).toBe(before);
  expect(loadDraft(draftKey("new", E3))?.label).toBe("Решили поставить козырёк");
});

test("@объект ищется по всей базе: без выбора из подсказки — первая находка поиска", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  await renderWithApp(<Harness />, "/");
  act(() => placeStore.openQuick(true));
  const dlg = await screen.findByRole("dialog", { name: "Новая запись" });
  const box = within(dlg).getByRole("textbox", { name: "Текст записи" });
  await user.type(box, "Смазали узел @влажности");
  await act(() => vi.advanceTimersByTimeAsync(300));
  // подсказка открыта — Esc закрывает её, окно остаётся; Enter записывает
  await user.keyboard("{Escape}");
  expect(screen.getByRole("dialog", { name: "Новая запись" })).toBeInTheDocument();
  await user.keyboard("{Enter}");
  await act(() => vi.advanceTimersByTimeAsync(UNDO_MS + 100));
  const made = db.records.find((r) => r.label.startsWith("Смазали узел"));
  expect(made?.about.map((a) => a.ref)).toContain(E3);
});

test("подсказки: @ — объект плашкой «О чём», # — тег с частотой, вид с причиной", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  await renderWithApp(<Harness />, "/");
  act(() => placeStore.openQuick(true));
  const dlg = await screen.findByRole("dialog", { name: "Новая запись" });
  const box = within(dlg).getByRole("textbox", { name: "Текст записи" });
  await user.type(box, "Проверили @влаж");
  const opt = await within(dlg).findByRole("option", { name: /Датчик влажности В-2/ });
  await user.click(opt);
  expect(within(dlg).getByText("О чём: Датчик влажности В-2")).toBeInTheDocument();
  expect(box).toHaveValue("Проверили ");
  await user.type(box, "#мет");
  expect(await within(dlg).findByRole("option", { name: /#метео/ })).toBeInTheDocument();
  await user.keyboard("{Enter}");
  expect(box).toHaveValue("Проверили #метео ");
  expect(within(dlg).getByText("правило не подошло — нажмите, чтобы сменить")).toBeInTheDocument();
  await user.clear(box);
  await user.type(box, "Нужен ли обогрев?");
  expect(within(dlg).getByText("в конце «?»")).toBeInTheDocument();
});
