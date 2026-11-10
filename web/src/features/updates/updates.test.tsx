import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { resetUpdates } from "../../mocks/handlers-u";
import { server } from "../../mocks/node";
import { renderWithApp } from "../../test/render";
import { ReloadBanner } from "./ReloadBanner";
import { UpdateBadge } from "./UpdateBadge";
import { UpdatesSection } from "./UpdatesSection";
import { pollEvery, resetOpened } from "./updates";

afterEach(() => {
  resetUpdates();
  resetOpened();
});

const problem409 = (code: string, detail: string) =>
  HttpResponse.json(
    { type: "about:blank", title: "Конфликт", status: 409, detail, code },
    { status: 409, headers: { "content-type": "application/problem+json" } },
  );

test("версия, доступный релиз и автообновление включено по умолчанию", async () => {
  await renderWithApp(<UpdatesSection />);
  expect(await screen.findByText("amemo 0.1.0a1")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Доступна 0.1.0a2" })).toHaveAttribute(
    "href",
    expect.stringContaining("/releases/tag/v0.1.0a2"),
  );
  expect(screen.getByRole("switch", { name: "Обновляться автоматически" })).toBeChecked();
});

test("«Обновить сейчас» — установка в фоне, затем значок «Обновление установлено»", async () => {
  const user = userEvent.setup();
  await renderWithApp(
    <>
      <UpdatesSection />
      <UpdateBadge />
    </>,
  );
  expect(screen.queryByRole("link", { name: "Обновление установлено" })).toBeNull();
  await user.click(await screen.findByRole("button", { name: "Обновить сейчас" }));
  expect(await screen.findByText(/Ставится 0\.1\.0a2/)).toBeInTheDocument();
  expect(
    await screen.findByRole("link", { name: "Обновление установлено" }, { timeout: 4000 }),
  ).toBeInTheDocument();
});

test("выключить автообновление; выключено в настройках службы — словами", async () => {
  const user = userEvent.setup();
  await renderWithApp(<UpdatesSection />);
  const sw = await screen.findByRole("switch", { name: "Обновляться автоматически" });
  await user.click(sw);
  await waitFor(() => expect(sw).not.toBeChecked());
  server.use(
    http.put("/api/v1/updates", () =>
      problem409("auto_update_off", "Автообновление выключено в amemo.toml."),
    ),
  );
  await user.click(sw);
  expect(await screen.findByRole("alert")).toHaveTextContent("Автообновление выключено в amemo.toml.");
});

test("Docker: кнопки установки нет, объяснение — как обновить", async () => {
  resetUpdates({ install: "docker" });
  await renderWithApp(<UpdatesSection />);
  expect(await screen.findByText(/обновите образ/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Обновить сейчас" })).toBeNull();
});

test("служба без /updates — раздела нет, ошибок нет", async () => {
  server.use(
    http.get("/api/v1/updates", () =>
      HttpResponse.json(
        { type: "about:blank", title: "Не найдено", status: 404 },
        { status: 404, headers: { "content-type": "application/problem+json" } },
      ),
    ),
  );
  const { container } = await renderWithApp(<UpdatesSection />);
  await new Promise((r) => setTimeout(r, 50));
  expect(container.querySelector(".upd")).toBeNull();
});

test("служба перезапустилась на новой версии — плашка «перезагрузите страницу»", async () => {
  const user = userEvent.setup();
  await renderWithApp(
    <>
      <UpdatesSection />
      <ReloadBanner />
    </>,
  );
  await screen.findByText("amemo 0.1.0a1");
  expect(screen.queryByText(/перезагрузите страницу/)).toBeNull();
  resetUpdates({ current: "0.1.0a2", latest: null, state: "idle", message: "" });
  await user.click(screen.getByRole("button", { name: "Проверить сейчас" }));
  expect(await screen.findByText("amemo обновлён до 0.1.0a2 — перезагрузите страницу")).toBeInTheDocument();
});

test("опрос: часто, пока идёт установка; раз в 10 минут в покое", () => {
  const base = {
    current: "1",
    latest: null,
    channel: "stable",
    install: "pip",
    auto: true,
    checked_at: null,
    message: "",
  } as const;
  expect(pollEvery({ ...base, state: "installing" })).toBe(2_000);
  expect(pollEvery({ ...base, state: "ready" })).toBe(5_000);
  expect(pollEvery({ ...base, state: "idle" })).toBe(600_000);
});
