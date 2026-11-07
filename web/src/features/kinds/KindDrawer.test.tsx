import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithApp } from "../../test/render";
import { KindDrawer } from "./KindDrawer";
import { kindsStore } from "./store";

afterEach(() => act(() => kindsStore.close()));

test("новый вид: имя → код транслитом, свойства, превью, сохранение — вид в списке «Мои виды»", async () => {
  const user = userEvent.setup();
  await renderWithApp(<KindDrawer />);
  act(() => kindsStore.open());
  const dlg = await screen.findByRole("dialog", { name: "Мои виды" });
  await user.click(within(dlg).getByRole("button", { name: "Вид" }));
  await user.type(within(dlg).getByRole("textbox", { name: "Имя вида" }), "Обход площадки");
  expect(within(dlg).getByRole("textbox", { name: "Код" })).toHaveValue("obkhod_ploshchadki");
  await user.click(within(dlg).getByRole("button", { name: "Добавить свойство" }));
  await user.type(within(dlg).getByRole("textbox", { name: "Имя свойства" }), "Что нашли");
  await user.click(within(dlg).getByRole("button", { name: "Добавить свойство" }));
  const names = within(dlg).getAllByRole("textbox", { name: "Имя свойства" });
  await user.type(names[1] as HTMLElement, "Объект");
  await user.selectOptions(within(dlg).getAllByRole("combobox", { name: "Тип" })[1] as HTMLElement, "object");
  await user.click(within(dlg).getAllByRole("checkbox", { name: "Нужно" })[1] as HTMLElement);
  const preview = within(dlg).getByRole("region", { name: "Как будет выглядеть" });
  expect(within(preview).getByText("Что нашли")).toBeInTheDocument();
  expect(within(preview).getByText("Нужно")).toBeInTheDocument();
  await user.click(within(dlg).getByRole("button", { name: "Сохранить вид" }));
  expect(await within(dlg).findByText("Вид «Обход площадки» сохранён")).toBeInTheDocument();
  await user.click(within(dlg).getByRole("button", { name: "К списку" }));
  expect(await within(dlg).findByRole("button", { name: /Обход площадки/ })).toBeInTheDocument();
});

test("пустое имя свойства — замечание у строки", async () => {
  const user = userEvent.setup();
  await renderWithApp(<KindDrawer />);
  act(() => kindsStore.open());
  const dlg = await screen.findByRole("dialog", { name: "Мои виды" });
  await user.click(within(dlg).getByRole("button", { name: "Вид" }));
  await user.type(within(dlg).getByRole("textbox", { name: "Имя вида" }), "Журнал");
  await user.click(within(dlg).getByRole("button", { name: "Добавить свойство" }));
  await user.click(within(dlg).getByRole("button", { name: "Сохранить вид" }));
  expect(await within(dlg).findByText("Нужно имя свойства")).toBeInTheDocument();
});
