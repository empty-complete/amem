import { screen, within } from "@testing-library/react";
import { renderWithApp } from "../../test/render";
import { ChangesPage } from "./ChangesPage";

test("лента по дням: сегодня сверху; каждая строка называет, кто и что сделал", async () => {
  await renderWithApp(<ChangesPage who="all" since="ever" />, "/changes");
  const today = await screen.findByRole("region", { name: "Сегодня" });
  // свои действия — «Вы …» (сессия в образцах — anna)
  expect(within(today).getByText("Вы записали ревизию 2")).toBeInTheDocument();
  expect(within(today).getByText("Вы добавили связь «см. также»")).toBeInTheDocument();
  expect(within(today).getByText("Вы приняли правку")).toBeInTheDocument();
  const yesterday = screen.getByRole("region", { name: "Вчера" });
  expect(within(yesterday).getByText("Записал: extractor (модель)")).toBeInTheDocument();
  expect(
    within(yesterday).getByText("Статус «Ждёт проверки» поставил: checker (модель)"),
  ).toBeInTheDocument();
  expect(within(yesterday).getByText("Связь снял: linker (модель)")).toBeInTheDocument();
});

test("фильтр «Агенты» — только модели", async () => {
  await renderWithApp(<ChangesPage who="model" since="ever" />, "/changes");
  await screen.findByRole("region", { name: "Вчера" });
  expect(screen.queryByText("anna")).not.toBeInTheDocument();
  expect(screen.getAllByText(/\(модель\)/).length).toBeGreaterThan(0);
});
