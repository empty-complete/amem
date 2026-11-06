import { screen } from "@testing-library/react";
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
