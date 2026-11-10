import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { db } from "../../mocks/db";
import { renderWithApp } from "../../test/render";
import { RecordList } from "./RecordList";

test("список записей: сначала скелет, потом строки со статусом словом", async () => {
  await renderWithApp(<RecordList folder={null} title="Все записи" />);
  expect(await screen.findByText("Диапазон температуры Т-1: −40…+60 °C")).toBeInTheDocument();
  expect(screen.getAllByText("Проверено").length).toBeGreaterThan(0);
  expect(screen.getByText("31 запись")).toBeInTheDocument();
});

test("папка фильтрует список вместе с вложенными", async () => {
  await renderWithApp(<RecordList folder="Архив" title="Архив" />);
  expect(await screen.findByText("Корпус МС-1 из алюминия")).toBeInTheDocument();
  expect(screen.queryByText("Ставим мачту на 2 м")).not.toBeInTheDocument();
});

test("длинный список догружается до конца: строк столько же, сколько в счётчике", async () => {
  const user = userEvent.setup();
  const first = db.records[0];
  if (!first) throw new Error("нет образцов");
  for (let i = 0; i < 230; i++)
    db.records.push({
      ...first,
      ref: `atm:0193b7c2-5e1a-7d40-9f2e-${String(900000 + i).padStart(12, "0")}`,
      label: `Строка ${i}`,
    });
  const total = db.records.length;
  await renderWithApp(<RecordList folder={null} title="Все записи" />);
  expect(await screen.findByText("Строка 0")).toBeInTheDocument();
  expect(screen.queryByText("Строка 229")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Показать ещё" }));
  expect(await screen.findByText("Строка 229")).toBeInTheDocument();
  expect(screen.getAllByRole("listitem")).toHaveLength(total);
  expect(screen.queryByRole("button", { name: "Показать ещё" })).not.toBeInTheDocument();
});
