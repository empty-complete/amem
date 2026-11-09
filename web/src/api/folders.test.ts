import { HttpResponse, http } from "msw";
import { server } from "../mocks/node";
import { folderApi } from "./folders";

test("путь папки уходит одним сегментом: «/» и пробел закодированы", async () => {
  const seen: string[] = [];
  server.use(
    http.patch("/api/v1/folders/:path", ({ request }) => {
      seen.push(new URL(request.url).pathname);
      return HttpResponse.json({ from: "Проекты/Старая папка", to: "Проекты/Новая", folders: 1, records: 0 });
    }),
  );
  await folderApi.rename("Проекты/Старая папка", "Проекты/Новая");
  expect(seen).toEqual([`/api/v1/folders/${encodeURIComponent("Проекты/Старая папка")}`]);
});
