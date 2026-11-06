import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithApp } from "../../test/render";
import { CommandField } from "./CommandField";

test("записи по запросу; выбор открывает запись", async () => {
  const user = userEvent.setup();
  const { router } = await renderWithApp(<CommandField />);
  const box = screen.getByRole("combobox", { name: "Поиск по базе" });
  await user.type(box, "погрешность");
  await user.click(await screen.findByRole("option", { name: /Погрешность влажности В-2/ }));
  expect(decodeURIComponent(router.state.location.pathname)).toMatch(/^\/atom\/atm:.*0b$/);
});

test("команды реестра по названию", async () => {
  const user = userEvent.setup();
  const { router } = await renderWithApp(<CommandField />);
  await user.type(screen.getByRole("combobox", { name: "Поиск по базе" }), "проверк");
  await user.click(await screen.findByRole("option", { name: /Открыть проверку/ }));
  expect(router.state.location.pathname).toBe("/review");
});

test("Enter без выбора — страница результатов", async () => {
  const user = userEvent.setup();
  const { router } = await renderWithApp(<CommandField />);
  await user.type(screen.getByRole("combobox", { name: "Поиск по базе" }), "мачта{Enter}");
  expect(router.state.location.pathname).toBe("/search");
  expect((router.state.location.search as { q?: string }).q).toBe("мачта");
});
