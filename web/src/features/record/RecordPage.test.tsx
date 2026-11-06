import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithApp } from "../../test/render";
import { RecordPage } from "./RecordPage";

vi.mock("../source/PdfPage", () => ({
  default: ({ page }: { page: number }) => <div>PDF, страница {page}</div>,
}));

const A3 = "atm:0193b7c2-5e1a-7d40-9f2e-00000000000b";
const A16 = "atm:0193b7c2-5e1a-7d40-9f2e-000000000016";
const N1 = "atm:0193b7c2-5e1a-7d40-9f2e-00000000001e";

test("запись: путь, заголовок, свойства, тело, источники, связи; технические поля скрыты", async () => {
  await renderWithApp(<RecordPage recordRef={A3} view="human" />, `/atom/${A3}`);
  expect(
    await screen.findByRole("heading", { level: 1, name: "Погрешность влажности В-2: ±2 %" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("navigation", { name: "О чём" })).toHaveTextContent(
    "Метеоплощадка / Метеостанция МС-1 / Датчик влажности В-2",
  );
  const props = screen.getByLabelText("Свойства");
  expect(await within(props).findByText("Параметр")).toBeInTheDocument();
  expect(within(props).getByText("🌱 росток")).toBeInTheDocument();
  expect(screen.getByText("±2 % в диапазоне 10…90 %", { selector: ".bigvalue" })).toBeInTheDocument();
  expect(screen.getByText(/Ждёт решения: Модель сомневается/)).toBeInTheDocument();
  expect(
    (await screen.findAllByRole("link", { name: "Нужен ли обогрев В-2 зимой?" })).length,
  ).toBeGreaterThan(0);
  await waitFor(() => expect(document.querySelector(".prose .katex-display")).not.toBeNull());
  expect(screen.getByRole("region", { name: "Связи" })).toHaveTextContent("см. также →");
  expect(screen.getByRole("complementary", { name: "Источник" })).toHaveTextContent("Цитата найдена");
  expect(screen.queryByText(/sha256/)).not.toBeInTheDocument();
});

test("[[ссылка]] в теле ведёт на запись из связей", async () => {
  const { router } = await renderWithApp(<RecordPage recordRef={A3} view="human" />, `/atom/${A3}`);
  await screen.findByRole("region", { name: "Связи" });
  const link = await waitFor(() => {
    const a = document.querySelector<HTMLAnchorElement>(".prose a.wiki");
    expect(a?.textContent).toBe("Нужен ли обогрев В-2 зимой?");
    expect(a?.getAttribute("href")).toMatch(/\/atom\/atm(:|%3A)/);
    return a as HTMLAnchorElement;
  });
  await userEvent.click(link);
  expect(decodeURIComponent(router.state.location.pathname)).toMatch(/^\/atom\/atm:.*18$/);
});

test("несколько источников — переключатель меняет панель", async () => {
  await renderWithApp(<RecordPage recordRef={A16} view="human" />, `/atom/${A16}`);
  const panel = await screen.findByRole("complementary", { name: "Источник" });
  expect(panel).toHaveTextContent("Найдена приблизительно");
  await userEvent.click(
    within(panel).getByRole("radio", { name: "Источник 2" }).closest("button") ??
      within(panel).getByRole("radio", { name: "Источник 2" }),
  );
  expect(panel).toHaveTextContent("Наблюдения_ноябрь.xlsx");
  expect(panel).toHaveTextContent("лист В-2, B4:C9");
  expect(panel).toHaveTextContent("Место не подтверждено цитатой");
});

test("исходник — шапка и тело текстом, только чтение", async () => {
  await renderWithApp(<RecordPage recordRef={A3} view="source" />, `/atom/${A3}?view=source`);
  const src = await screen.findByLabelText("Исходник записи");
  expect(src).toHaveTextContent("kind: parameter");
  expect(src).toHaveAttribute("aria-readonly", "true");
});

test("как видит агент — тело записи YAML", async () => {
  await renderWithApp(<RecordPage recordRef={A3} view="agent" />, `/atom/${A3}?view=agent`);
  const v = await screen.findByRole("region", { name: "Запись, как её получает агент" });
  expect(v).toHaveTextContent("summary_plain:");
  expect(v).toHaveTextContent("verdict: ok");
});

test("заметка человека без источника — основание словами", async () => {
  await renderWithApp(<RecordPage recordRef={N1} view="human" />, `/atom/${N1}`);
  expect(await screen.findByRole("complementary", { name: "Источник" })).toHaveTextContent(
    "Основание: слово автора",
  );
  expect(document.querySelector(".prose strong")?.textContent).toBe("верхний и средний");
});

test("нет записи — 404 словами", async () => {
  await renderWithApp(<RecordPage recordRef="atm:нет" view="human" />, "/atom/atm:нет");
  expect(await screen.findByRole("alert")).toHaveTextContent("Записи atm:нет нет");
});
