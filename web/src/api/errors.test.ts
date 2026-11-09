import { ApiError, problemFromResponse } from "./errors";

test("problem+json становится ApiError с кодом и замечаниями", async () => {
  const res = new Response(
    JSON.stringify({
      type: "about:blank",
      title: "Отклонено",
      status: 422,
      code: "level1",
      issues: [{ code: "has_label", severity: "violation", message: "Нет подписи" }],
    }),
    { status: 422, headers: { "content-type": "application/problem+json" } },
  );
  const err = await problemFromResponse(res);
  expect(err).toBeInstanceOf(ApiError);
  expect(err.status).toBe(422);
  expect(err.code).toBe("level1");
  expect(err.issues[0]?.message).toBe("Нет подписи");
});

test("ответ без тела становится ApiError по статусу", async () => {
  const err = await problemFromResponse(new Response(null, { status: 503 }));
  expect(err.status).toBe(503);
  expect(err.title).toBe("Служба недоступна");
});

test("check_rejected: замечания и предупреждения вместе; 413 — словами", async () => {
  const body = {
    title: "Отклонено проверкой",
    status: 422,
    code: "check_rejected",
    issues: [{ code: "schema", severity: "violation", message: "Не по схеме", ref: "@n0", path: "label" }],
    warnings: [
      { code: "private_removed", severity: "warning", message: "Вырезано скрытое", ref: "@n0", path: "body" },
    ],
  };
  const res = new Response(JSON.stringify(body), {
    status: 422,
    headers: { "content-type": "application/problem+json" },
  });
  const err = await problemFromResponse(res);
  expect(err.issues.map((i) => i.code)).toEqual(["schema", "private_removed"]);
  expect((await problemFromResponse(new Response("", { status: 413 }))).title).toBe("Слишком большой запрос");
});
