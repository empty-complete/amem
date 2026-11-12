import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithApp } from "../../test/render";
import { ExportForm } from "./ExportForm";

test("антология: статусы зафиксированы на «проверено», после сборки — zip и отчёт", async () => {
  const user = userEvent.setup();
  await renderWithApp(<ExportForm />, "/bundles");
  await user.click(
    await screen.findByRole("checkbox", { name: /Антология: проверенное и предпочтительное/ }),
  );
  expect(screen.getByRole("checkbox", { name: "Ждёт проверки" })).toBeDisabled();
  await user.type(screen.getByRole("textbox", { name: "Заголовок отчёта" }), "Датчики");
  await user.click(screen.getByRole("button", { name: "Собрать подборку" }));
  expect(await screen.findByRole("heading", { name: /Подборка собрана/ })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Скачать zip" })).toHaveAttribute(
    "href",
    expect.stringMatching(/\/download$/),
  );
  // отчёт — в окне приложения (в настольном приложении нового окна нет), HTML в изолированной рамке
  await user.click(screen.getByRole("button", { name: "Открыть отчёт" }));
  const dlg = await screen.findByRole("dialog", { name: "Отчёт подборки" });
  const frame = dlg.querySelector("iframe");
  expect(frame?.getAttribute("sandbox")).toBe("");
  expect(frame?.getAttribute("srcdoc")).toContain("Датчики");
});

test("пустой отбор — словами", async () => {
  const user = userEvent.setup();
  await renderWithApp(<ExportForm />, "/bundles");
  await user.type(await screen.findByRole("textbox", { name: "Теги" }), "нет-такого");
  await user.click(screen.getByRole("button", { name: "Собрать подборку" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Подборка пуста");
});
