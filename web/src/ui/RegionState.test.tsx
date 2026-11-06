import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RegionState } from "./RegionState";

test("загрузка — скелет с ролью status", () => {
  render(<RegionState state="loading" skeleton={<div data-testid="sk" />} />);
  expect(screen.getByRole("status")).toBeInTheDocument();
  expect(screen.getByTestId("sk")).toBeInTheDocument();
});

test("пусто — одна строка и одно действие", async () => {
  const onPress = vi.fn();
  render(<RegionState state="empty" text="Очередь пуста" action={{ label: "Записать", onPress }} />);
  expect(screen.getByText("Очередь пуста")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Записать" }));
  expect(onPress).toHaveBeenCalled();
});

test("ошибка — что сломалось и «Повторить»", async () => {
  const retry = vi.fn();
  render(<RegionState state="error" message="Нет связи со службой" retry={retry} />);
  expect(screen.getByRole("alert")).toHaveTextContent("Нет связи со службой");
  await userEvent.click(screen.getByRole("button", { name: "Повторить" }));
  expect(retry).toHaveBeenCalled();
});
