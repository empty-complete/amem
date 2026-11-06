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
