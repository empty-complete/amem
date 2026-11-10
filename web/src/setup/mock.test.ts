import type { Progress } from "./bridge";
import { mockBridge } from "./mock";

const choices = { lang: "ru" as const, dataDir: "C:\\amemo-data", docsDir: null, ocr: [], agents: [] };

test("заглушка: невыбранные шаги пропущены, остальные завершены", async () => {
  const seen: Progress[] = [];
  await mockBridge(new URLSearchParams("fast=1")).install(choices, (p) => seen.push(p));
  const last = Object.fromEntries(seen.map((p) => [p.stage, p.state]));
  expect(last).toEqual({
    download: "done",
    database: "done",
    store: "done",
    search: "done",
    ocr: "skipped",
    agents: "skipped",
  });
});

test("заглушка: ошибка шага — один раз, повтор проходит", async () => {
  const b = mockBridge(new URLSearchParams("fast=1&fail=database"));
  await expect(b.install(choices, () => {})).rejects.toThrow("pg_ctl start");
  await expect(b.install(choices, () => {})).resolves.toBeUndefined();
});

test("заглушка: путь вне кодировки Windows — запасная папка", async () => {
  const b = mockBridge(new URLSearchParams("nonansi=1"));
  const check = await b.checkFolder("C:\\Users\\Анна\\amemo-data");
  expect(check).toMatchObject({ ansiSafe: false, fallback: "C:\\amemo-data" });
  expect((await b.checkFolder("C:\\amemo-data")).ansiSafe).toBe(true);
});
