import { screen } from "@testing-library/react";
import { renderWithApp } from "../../test/render";
import { SearchResults } from "./SearchResults";

const p = (q: string) => ({ q, kind: [], status: [], limit: 10 });

test("точное совпадение кода идёт первым с подписью", async () => {
  await renderWithApp(<SearchResults params={p("погрешность")} />);
  expect(await screen.findByText("Точное совпадение кода")).toBeInTheDocument();
  const rows = screen.getAllByRole("link");
  expect(rows[0]).toHaveTextContent("Погрешность влажности В-2");
});

test("смысловой канал выключен — тихая строка, список есть", async () => {
  await renderWithApp(<SearchResults params={p("без смысла")} />);
  expect(await screen.findByText(/Поиск по смыслу недоступен/)).toBeInTheDocument();
  expect(screen.getAllByRole("link").length).toBe(3);
});

test("ошибка службы — что сломалось и «Повторить»", async () => {
  await renderWithApp(<SearchResults params={p("ошибка")} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("База не отвечает");
  expect(screen.getByRole("button", { name: "Повторить" })).toBeInTheDocument();
});

test("пустой запрос — подсказка, без запроса к службе", async () => {
  await renderWithApp(<SearchResults params={p("")} />);
  expect(screen.getByText(/Введите запрос/)).toBeInTheDocument();
});
