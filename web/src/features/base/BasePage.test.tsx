import { screen, within } from "@testing-library/react";
import { renderWithApp } from "../../test/render";
import { BasePage } from "./BasePage";

test("База: статусы, очередь по причинам, пакеты, бэкапы — таблицами", async () => {
  await renderWithApp(<BasePage />, "/base");
  const statuses = await screen.findByRole("table", { name: "Записи по статусам" });
  expect(within(statuses).getByRole("rowheader", { name: "Проверено" })).toBeInTheDocument();
  const queue = screen.getByRole("table", { name: "Очередь по причинам" });
  expect(within(queue).getByRole("rowheader", { name: "правка" })).toBeInTheDocument();
  expect(screen.getByRole("table", { name: "Пакеты" })).toHaveTextContent("meteo");
  expect(screen.getByRole("table", { name: "Бэкапы" })).toHaveTextContent("amemo-2026-11-07T03-00.dump");
});
