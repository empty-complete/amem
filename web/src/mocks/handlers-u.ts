import { delay, HttpResponse, http } from "msw";
import fixture from "./fixtures/updates.json";

type Status = Omit<typeof fixture, "latest" | "checked_at"> & {
  latest: { version: string; url: string | null } | null;
  checked_at: string | null;
};

/** Обновления (U3): состояние живёт в памяти мока; установка — «в фоне», через мгновение ready. */
let st: Status = structuredClone(fixture);
export const resetUpdates = (over: Partial<Status> = {}) => {
  st = { ...structuredClone(fixture), ...over };
};

const problem = (code: string, title: string, detail: string) =>
  HttpResponse.json(
    { type: "about:blank", title, status: 409, detail, code },
    { status: 409, headers: { "content-type": "application/problem+json" } },
  );

export const handlersU = [
  http.get("/api/v1/updates", () => HttpResponse.json(st)),
  http.put("/api/v1/updates", async ({ request }) => {
    const { auto } = (await request.json()) as { auto: boolean };
    st = { ...st, auto };
    return HttpResponse.json(st);
  }),
  http.post("/api/v1/updates/check", async () => {
    await delay(150);
    st = { ...st, checked_at: new Date().toISOString() };
    return HttpResponse.json(st);
  }),
  http.post("/api/v1/updates/install", () => {
    if (st.state === "installing") return problem("update_busy", "Уже ставится", "Установка уже идёт.");
    if (!st.latest) return problem("no_update", "Ставить нечего", "Новее текущей версии нет.");
    const to = st.latest.version;
    st = { ...st, state: "installing", message: `Ставится ${to}…` };
    setTimeout(() => {
      st = { ...st, state: "ready", message: `${to} установлена — перезапуск, когда служба освободится.` };
    }, 600);
    return HttpResponse.json(st, { status: 202 });
  }),
];
