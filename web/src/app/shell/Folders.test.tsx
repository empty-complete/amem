import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { MoveDialog } from "../../features/write/MoveDialog";
import { resetQueue } from "../../features/write/submitQueue";
import { UndoToasts } from "../../features/write/UndoToast";
import { db } from "../../mocks/db";
import { renderWithApp } from "../../test/render";
import { Folders } from "./Folders";

afterEach(() => {
  resetQueue();
  vi.useRealTimers();
});

// окно переноса закрывается, как на странице записи: под открытым модальным окном тост недоступен
function MoveHarness({ recordRef }: { recordRef: string }) {
  const [open, setOpen] = useState(true);
  return (
    <>
      <MoveDialog recordRef={recordRef} current={null} open={open} onClose={() => setOpen(false)} />
      <UndoToasts />
    </>
  );
}

const nav = () => screen.getByRole("navigation", { name: "Папки" });

/** Правая кнопка по пустому месту панели — меню корня. */
const rootMenu = () => {
  const area = nav().querySelector(".ftree");
  if (!area) throw new Error("нет дерева");
  fireEvent.contextMenu(area);
};

test("новая папка — правой кнопкой по пустому месту; такая уже есть — словами", async () => {
  const user = userEvent.setup();
  await renderWithApp(<Folders />);
  await within(nav()).findByRole("button", { name: /^Архив/ });
  rootMenu();
  await user.click(await screen.findByRole("menuitem", { name: "Новая папка" }));
  await user.type(screen.getByRole("textbox", { name: "Имя новой папки" }), "Обходы{Enter}");
  expect(await within(nav()).findByRole("button", { name: /^Обходы/ })).toBeInTheDocument();
  rootMenu();
  await user.click(await screen.findByRole("menuitem", { name: "Новая папка" }));
  await user.type(screen.getByRole("textbox", { name: "Имя новой папки" }), "Архив{Enter}");
  expect(await screen.findByRole("alert")).toHaveTextContent("Такая папка уже есть");
});

test("переименование переносит записи; непустую не удалить — правой кнопкой по папке", async () => {
  const user = userEvent.setup();
  await renderWithApp(<Folders />);
  const archive = await within(nav()).findByRole("button", { name: /^Архив/ });
  await user.pointer({ keys: "[MouseRight]", target: archive });
  await user.click(await screen.findByRole("menuitem", { name: "Переименовать" }));
  const input = screen.getByRole("textbox", { name: "Переименовать" });
  await user.clear(input);
  await user.type(input, "Старое{Enter}");
  const old = await within(nav()).findByRole("button", { name: /^Старое/ });
  expect(db.records.filter((r) => r.folder?.startsWith("Старое")).length).toBe(2);
  await user.pointer({ keys: "[MouseRight]", target: old });
  await user.click(await screen.findByRole("menuitem", { name: "Удалить" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("В папке есть записи");
});

test("«Переместить в папку» уходит сразу; «Отменить» возвращает в прежнюю папку", async () => {
  const user = userEvent.setup();
  const ref = "atm:0193b7c2-5e1a-7d40-9f2e-00000000001e";
  await renderWithApp(<MoveHarness recordRef={ref} />);
  await user.click(await screen.findByRole("radio", { name: "Архив" }));
  await user.click(screen.getByRole("button", { name: "Переместить в папку" }));
  await waitFor(() => expect(db.records.find((r) => r.ref === ref)?.folder).toBe("Архив"));
  await user.click(await screen.findByRole("button", { name: "Отменить" }));
  await waitFor(() => expect(db.records.find((r) => r.ref === ref)?.folder).toBeNull());
});

test("папка раскрывается в панели: внутри её записи и вложенные; записи без папки — в корне под папками", async () => {
  const user = userEvent.setup();
  await renderWithApp(<Folders />);
  const inside = db.records.filter((r) => r.folder === "Архив/Станция 2024");
  expect(inside.length).toBeGreaterThan(0);
  // без папки — сразу в корне, без раздела «Без папки» и без «Показать ещё»
  const loose = db.records.filter((r) => !r.folder);
  expect(loose.length).toBeGreaterThan(0);
  for (const r of loose.slice(0, 3))
    expect(await within(nav()).findByRole("link", { name: r.label })).toBeInTheDocument();
  expect(within(nav()).queryByRole("button", { name: /^Без папки/ })).not.toBeInTheDocument();
  expect(within(nav()).queryByRole("button", { name: "Показать ещё" })).not.toBeInTheDocument();
  // в самой «Архив» записей нет — они во вложенной папке
  await user.click(await within(nav()).findByRole("button", { name: /^Архив/ }));
  expect(await within(nav()).findByText("Пусто")).toBeInTheDocument();
  const station = within(nav()).getByRole("button", { name: /^Станция 2024/ });
  expect(station).toHaveAttribute("aria-expanded", "false");
  await user.click(station);
  expect(station).toHaveAttribute("aria-expanded", "true");
  for (const r of inside)
    expect(await within(nav()).findByRole("link", { name: r.label })).toBeInTheDocument();
  await user.click(station);
  for (const r of inside)
    expect(within(nav()).queryByRole("link", { name: r.label })).not.toBeInTheDocument();
});

test("заметки в дереве: Ctrl добавляет к выбору, правая кнопка — «Поделиться» с исходными файлами", async () => {
  const user = userEvent.setup();
  await renderWithApp(<Folders />);
  const station = await within(nav()).findByRole("button", { name: /^Станция 2024/ });
  await user.click(station);
  const inside = db.records.filter((r) => r.folder === "Архив/Станция 2024");
  const [a, b] = inside;
  if (!a || !b) throw new Error("нет образцов");
  const la = await within(nav()).findByRole("link", { name: a.label });
  const lb = within(nav()).getByRole("link", { name: b.label });
  await user.keyboard("{Control>}");
  await user.click(la);
  await user.click(lb);
  await user.keyboard("{/Control}");
  expect(la.closest("li")).toHaveAttribute("data-picked", "true");
  expect(lb.closest("li")).toHaveAttribute("data-picked", "true");
  await user.pointer({ keys: "[MouseRight]", target: lb });
  await user.click(await screen.findByRole("menuitem", { name: /^Поделиться/ }));
  const dlg = await screen.findByRole("dialog", { name: "Поделиться заметками" });
  expect(within(dlg).getByText(/^Выбрано 2 записи/)).toBeInTheDocument();
  expect(within(dlg).getByRole("checkbox", { name: /файл/i })).toBeChecked();
});

test("Shift выбирает диапазон от прошлой выбранной, без Ctrl — заменяет выбор", async () => {
  const user = userEvent.setup();
  await renderWithApp(<Folders />);
  await user.click(await within(nav()).findByRole("button", { name: /^Станция 2024/ }));
  const inside = db.records.filter((r) => r.folder === "Архив/Станция 2024");
  const links = await Promise.all(inside.map((r) => within(nav()).findByRole("link", { name: r.label })));
  const first = links[0];
  const last = links[links.length - 1];
  if (!first || !last || first === last) throw new Error("нет образцов");
  await user.click(first);
  await user.keyboard("{Shift>}");
  await user.click(last);
  await user.keyboard("{/Shift}");
  const picked = [...nav().querySelectorAll<HTMLElement>("li[data-picked]")].map((el) => el.dataset.ref);
  expect(picked).toHaveLength(links.length);
  // новый Shift-щелчок без Ctrl — новый диапазон вместо прежнего
  await user.keyboard("{Shift>}");
  await user.click(first);
  await user.keyboard("{/Shift}");
  expect(nav().querySelectorAll("li[data-picked]")).toHaveLength(1);
});
