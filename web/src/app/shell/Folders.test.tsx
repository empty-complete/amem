import { screen, waitFor, within } from "@testing-library/react";
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

test("новая папка на месте; такая уже есть — словами", async () => {
  const user = userEvent.setup();
  await renderWithApp(<Folders />);
  await user.click(await screen.findByRole("button", { name: "Папка" }));
  await user.type(screen.getByRole("textbox", { name: "Имя новой папки" }), "Обходы{Enter}");
  expect(await within(nav()).findByRole("button", { name: /^Обходы/ })).toBeInTheDocument();
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
  expect(await within(nav()).findByRole("button", { name: /^Старое/ })).toBeInTheDocument();
  expect(db.records.filter((r) => r.folder?.startsWith("Старое")).length).toBe(2);
  await user.click(screen.getByRole("button", { name: "Папка «Старое»: действия" }));
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

test("папка раскрывается в панели: внутри её записи, без вложенных; значок справа — списком", async () => {
  const user = userEvent.setup();
  await renderWithApp(<Folders />);
  const inside = db.records.filter((r) => r.folder === "Архив/Станция 2024");
  expect(inside.length).toBeGreaterThan(0);
  // в самой «Архив» записей нет — они во вложенной папке
  await user.click(await within(nav()).findByRole("button", { name: /^Архив/ }));
  expect(await within(nav()).findByText("Пусто")).toBeInTheDocument();
  const station = within(nav()).getByRole("button", { name: /^Станция 2024/ });
  expect(station).toHaveAttribute("aria-expanded", "false");
  await user.click(station);
  expect(station).toHaveAttribute("aria-expanded", "true");
  for (const r of inside)
    expect(await within(nav()).findByRole("link", { name: r.label })).toBeInTheDocument();
  expect(within(nav()).getByRole("link", { name: "«Станция 2024» списком" })).toHaveAttribute(
    "href",
    expect.stringContaining("folder="),
  );
  await user.click(station);
  for (const r of inside)
    expect(within(nav()).queryByRole("link", { name: r.label })).not.toBeInTheDocument();
});

test("по умолчанию папку внутри папки не создать", async () => {
  const user = userEvent.setup();
  await renderWithApp(<Folders />);
  await user.click(await screen.findByRole("button", { name: "Папка «Архив»: действия" }));
  expect(await screen.findByRole("menuitem", { name: "Переименовать" })).toBeInTheDocument();
  expect(screen.queryByRole("menuitem", { name: "Папка внутри" })).not.toBeInTheDocument();
});
