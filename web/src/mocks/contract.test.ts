import { checkResponse } from "./contract";
import base from "./fixtures/base.json";

const req = (method: string, path: string) => new Request(`http://localhost/api/v1${path}`, { method });
const json = (body: unknown, status = 200) => Response.json(body, { status });

test("ответ по схеме проходит, пустой — нет; не JSON и чужие пути не сверяются", async () => {
  expect(await checkResponse(req("GET", "/base"), json(base))).toEqual([]);
  expect(await checkResponse(req("GET", "/base"), json({}))).not.toEqual([]);
  expect(await checkResponse(req("GET", "/objects/x/file"), new Response("pdf"))).toEqual([]);
  expect(await checkResponse(new Request("http://localhost/ui/"), json({}))).toEqual([]);
});

test("лишний путь и неверное тело ловятся", async () => {
  expect(await checkResponse(req("GET", "/nowhere"), json({}))).toEqual([
    "GET /nowhere → 200: нет в контракте",
  ]);
  const [err] = await checkResponse(req("GET", "/session"), json({ agent: 1 }));
  expect(err).toMatch(/^GET \/session → 200: /);
});

test("problem+json сверяется со схемой ошибки", async () => {
  const bad = new Response(JSON.stringify({ title: 5 }), {
    status: 404,
    headers: { "content-type": "application/problem+json" },
  });
  expect(await checkResponse(req("GET", "/records/atm:x"), bad)).not.toEqual([]);
});
