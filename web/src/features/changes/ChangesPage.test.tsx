import { screen, within } from "@testing-library/react";
import { renderWithApp } from "../../test/render";
import { ChangesPage } from "./ChangesPage";

test("лента по дням: сегодня сверху, события словами, кто записал", async () => {
  await renderWithApp(<ChangesPage who="all" since="ever" />, "/changes");
  const today = await screen.findByRole("region", { name: "Сегодня" });
  expect(within(today).getByText("новая ревизия")).toBeInTheDocument();
  expect(within(today).getByText("связь добавлена · см. также")).toBeInTheDocument();
  expect(within(today).getAllByText("anna").length).toBeGreaterThan(0);
  expect(screen.getByRole("region", { name: "Вчера" })).toBeInTheDocument();
  expect(screen.getByText("статус: Ждёт проверки")).toBeInTheDocument();
});

test("фильтр «Агенты» — только модели", async () => {
  await renderWithApp(<ChangesPage who="model" since="ever" />, "/changes");
  await screen.findByRole("region", { name: "Вчера" });
  expect(screen.queryByText("anna")).not.toBeInTheDocument();
  expect(screen.getAllByText(/\(модель\)/).length).toBeGreaterThan(0);
});
