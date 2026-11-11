import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import type { RecordFilter } from "../../api/queries";
import { db } from "../../mocks/db";
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

test("длинный список догружается до конца: строк столько же, сколько в счётчике", async () => {
  const user = userEvent.setup();
  const first = db.records[0];
  if (!first) throw new Error("нет образцов");
  for (let i = 0; i < 230; i++)
    db.records.push({
      ...first,
      ref: `atm:0193b7c2-5e1a-7d40-9f2e-${String(900000 + i).padStart(12, "0")}`,
      label: `Строка ${i}`,
    });
  const total = db.records.length;
  await renderWithApp(<RecordList folder={null} title="Все записи" />);
  expect(await screen.findByText("Строка 0")).toBeInTheDocument();
  expect(screen.queryByText("Строка 229")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Показать ещё" }));
  expect(await screen.findByText("Строка 229")).toBeInTheDocument();
  expect(screen.getAllByRole("listitem")).toHaveLength(total);
  expect(screen.queryByRole("button", { name: "Показать ещё" })).not.toBeInTheDocument();
});

test("фильтры складываются: два тега сразу и вид; счётчик — число отобранных", async () => {
  const [a, b, c] = db.records;
  if (!a || !b || !c) throw new Error("нет образцов");
  a.tags = ["метео", "зима"];
  b.tags = ["метео", "зима"];
  b.kind_or_class = a.kind_or_class === "note" ? "fact" : "note";
  c.tags = ["метео"];
  await renderWithApp(
    <RecordList
      folder={null}
      title="Все записи"
      filter={{ tag: ["метео", "зима"], kind: [a.kind_or_class] }}
    />,
  );
  expect(await screen.findByText(a.label)).toBeInTheDocument();
  expect(screen.queryByText(b.label)).not.toBeInTheDocument();
  expect(screen.queryByText(c.label)).not.toBeInTheDocument();
  expect(screen.getByText("1 запись")).toBeInTheDocument();
});

function FilterHarness() {
  const [f, setF] = useState<RecordFilter>({});
  return <RecordList folder={null} title="Все записи" filter={f} onFilter={setF} />;
}

test("строка фильтров: тег Enter-ом, статус из списка, «Сбросить» возвращает всё", async () => {
  const user = userEvent.setup();
  const first = db.records[0];
  if (!first) throw new Error("нет образцов");
  first.tags = ["зима"];
  const total = db.records.length;
  await renderWithApp(<FilterHarness />);
  await screen.findByText(new RegExp(`^${total} запис`));
  await user.type(screen.getByRole("combobox", { name: "Теги" }), "зима{Enter}");
  expect(await screen.findByText("1 запись")).toBeInTheDocument();
  expect(screen.getByText(first.label)).toBeInTheDocument();
  await user.selectOptions(screen.getByRole("combobox", { name: "Статус" }), "rejected");
  expect(await screen.findByText("Под эти фильтры ничего не подходит.")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Сбросить" }));
  expect(await screen.findByText(new RegExp(`^${total} запис`))).toBeInTheDocument();
});
