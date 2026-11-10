import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { SignIn } from "../app/shell/SignIn";
import base from "../mocks/fixtures/base.json";
import { server } from "../mocks/node";
import { apiFetch, auth, authHeaders, nameFrom } from "./auth";
import { api } from "./client";

afterEach(() => act(() => auth.clear()));

test("токен: на вкладку по умолчанию, на устройстве — по «Запомнить»; «Выйти» стирает отовсюду", () => {
  auth.set("t-1", false);
  expect(sessionStorage.getItem("amemo.token")).toBe("t-1");
  expect(localStorage.getItem("amemo.token")).toBeNull();
  auth.set("t-2", true);
  expect(localStorage.getItem("amemo.token")).toBe("t-2");
  expect(sessionStorage.getItem("amemo.token")).toBeNull();
  auth.clear();
  expect(authHeaders()).toEqual({});
  expect(localStorage.getItem("amemo.token")).toBeNull();
});

test("с токеном — Authorization в запросах клиента и apiFetch; без токена — заголовка нет", async () => {
  const seen: (string | null)[] = [];
  server.use(
    http.get("/api/v1/base", ({ request }) => {
      seen.push(request.headers.get("authorization"));
      return HttpResponse.json(base);
    }),
  );
  await api.GET("/base").catch(() => {});
  auth.set("secret", false);
  await api.GET("/base").catch(() => {});
  await apiFetch(`${location.origin}/api/v1/base`);
  expect(seen).toEqual([null, "Bearer secret", "Bearer secret"]);
});

test("ответ 401 — показать вход; ввод токена — вход скрыт, токен сохранён", async () => {
  server.use(
    http.get("/api/v1/base", () =>
      HttpResponse.json(
        { type: "about:blank", title: "Нужен вход", status: 401, code: "unauthorized" },
        { status: 401, headers: { "content-type": "application/problem+json" } },
      ),
    ),
  );
  const qc = new QueryClient();
  render(
    <QueryClientProvider client={qc}>
      <SignIn />
    </QueryClientProvider>,
  );
  expect(screen.queryByRole("dialog")).toBeNull();
  await act(async () => {
    await api.GET("/base").catch(() => {});
  });
  const dlg = await screen.findByRole("dialog", { name: "Вход в общую службу" });
  await userEvent.type(screen.getByLabelText("Токен"), "abc");
  await userEvent.click(screen.getByRole("button", { name: "Войти" }));
  expect(dlg).not.toBeInTheDocument();
  expect(authHeaders()).toEqual({ Authorization: "Bearer abc" });
});

test("имя файла из Content-Disposition: filename* важнее filename", () => {
  expect(nameFrom("attachment; filename=\"a.zip\"; filename*=UTF-8''%D0%BF.zip")).toBe("п.zip");
  expect(nameFrom('attachment; filename="report.html"')).toBe("report.html");
  expect(nameFrom(null)).toBeUndefined();
});
