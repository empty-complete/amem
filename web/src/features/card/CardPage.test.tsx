import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithApp } from "../../test/render";
import { CardPage } from "./CardPage";

const E3 = "ent:0193b7c2-5e1a-7d40-9f2e-000000000003";
const E5 = "ent:0193b7c2-5e1a-7d40-9f2e-000000000005";

test("объект: путь, итог словами, все состояния полей", async () => {
  await renderWithApp(<CardPage entityRef={E3} />, `/entity/${E3}`);
  expect(await screen.findByRole("heading", { level: 1, name: "Датчик влажности В-2" })).toBeInTheDocument();
  expect(screen.getByRole("navigation", { name: "О чём" })).toHaveTextContent(
    "Метеоплощадка / Метеостанция МС-1",
  );
  const line = "Известно 2 из 7. 1 расхождение, 1 открытый вопрос, нет 1 обязательного поля.";
  expect(screen.getByRole("img", { name: line })).toBeInTheDocument();
  expect(screen.getByText(line)).toBeInTheDocument();
  // какие поля — по запросу, свёрнутым списком
  expect(screen.getByText("Какие поля не заполнены")).toBeInTheDocument();
  expect(screen.getAllByText("рабочая температура", { exact: false }).length).toBeGreaterThan(0);
  const measure = await screen.findByRole("region", { name: "Измерение" });
  expect(within(measure).getByText("0…100 %")).toBeInTheDocument();
  expect(within(measure).getByText("Не применяется")).toBeInTheDocument();
  const cond = await screen.findByRole("region", { name: "Условия" });
  expect(within(cond).getByText("Нужно")).toBeInTheDocument();
  expect(within(cond).getByText(/Где искать: паспорт датчика/)).toBeInTheDocument();
  expect(within(cond).getByText("Вопрос открыт")).toBeInTheDocument();
  expect(within(cond).getByText("из: Метеостанция МС-1")).toBeInTheDocument();
  // форма ядра: у кого спросить, когда нужно, откуда значение (словарь parameter_origin), вопрос — ссылкой
  expect(within(cond).getByText(/спросить: изготовитель/)).toBeInTheDocument();
  expect(within(cond).getByText(/нужно, если площадка зимой ниже −30 °C/)).toBeInTheDocument();
  expect(await within(cond).findAllByText(/паспорт$/)).not.toHaveLength(0);
  expect(within(cond).getByRole("link", { name: "вопрос задан — открыть" })).toBeInTheDocument();
  expect(screen.getByText("по умолчанию 60 с")).toBeInTheDocument();
});

test("расхождение раскрывается и показывает обе цитаты", async () => {
  await renderWithApp(<CardPage entityRef={E3} />, `/entity/${E3}`);
  const btn = await screen.findByRole("button", { name: /2 значения/ });
  expect(btn).toHaveAttribute("aria-expanded", "false");
  await userEvent.click(btn);
  const list = screen.getByRole("list", { name: "Кандидаты" });
  expect(list).toHaveTextContent("Погрешность ±2 % в диапазоне от 10 до 90 %");
  expect(list).toHaveTextContent("расхождение до 12 % при инее");
});

test("вкладка «Атомы» — записи о сущности", async () => {
  await renderWithApp(<CardPage entityRef={E3} />, `/entity/${E3}`);
  await userEvent.click(await screen.findByRole("tab", { name: "Атомы" }));
  expect(await screen.findByText("Погрешность влажности В-2: ±2 %")).toBeInTheDocument();
});

test("неизвестная сущность — ошибка словами", async () => {
  await renderWithApp(<CardPage entityRef={E5} />, `/entity/${E5}`);
  expect(await screen.findByRole("alert")).toBeInTheDocument();
});
