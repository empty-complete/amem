import { writeLog } from "../../mocks/handlers-d";
import { enqueue, flushAll, resetQueue, UNDO_MS, undo } from "./submitQueue";

const body = (label: string) => ({
  proposals: [
    {
      target: "atom" as const,
      payload: { kind: "note", label: { ru: label }, basis: "author" },
      record_id: null,
    },
  ],
  links: [],
});
const meta = { what: "заметка", about: [], kind: "note" };

afterEach(() => {
  resetQueue();
  vi.useRealTimers();
});

test("до конца окна ничего не уходит; «Отменить» — и не уйдёт", async () => {
  vi.useFakeTimers();
  const id = enqueue({ ...meta, label: "Раз", body: body("Раз") });
  vi.advanceTimersByTime(UNDO_MS - 100);
  expect(writeLog).toEqual([]);
  undo(id);
  vi.advanceTimersByTime(UNDO_MS);
  expect(writeLog).toEqual([]);
});

test("по истечении окна пакет уходит, ответ — в onDone", async () => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  const done = vi.fn();
  enqueue({ ...meta, label: "Два", body: body("Два"), onDone: done });
  vi.advanceTimersByTime(UNDO_MS);
  vi.useRealTimers();
  await vi.waitFor(() => expect(done).toHaveBeenCalled());
  expect(writeLog).toEqual(["submit"]);
  expect(done.mock.calls[0]?.[0].records[0]).toMatchObject({
    label: "Два",
    created: true,
    status: "verified",
  });
});

test("уход со страницы — сразу и с keepalive", async () => {
  const spy = vi.spyOn(globalThis, "fetch");
  enqueue({ ...meta, label: "Три", body: body("Три") });
  flushAll();
  await vi.waitFor(() => expect(writeLog).toEqual(["submit"]));
  expect(spy.mock.calls[0]?.[1]).toMatchObject({ keepalive: true, method: "POST" });
  spy.mockRestore();
});

test("отказ проверки — замечания с путями", async () => {
  const issues = vi.fn();
  enqueue({ ...meta, label: "", body: body(""), onIssues: issues });
  flushAll();
  await vi.waitFor(() => expect(issues).toHaveBeenCalled());
  expect(issues.mock.calls[0]?.[0]).toContainEqual(
    expect.objectContaining({ path: "label.ru", message: "Нужен заголовок" }),
  );
});
