import type { components } from "./schema";

type Problem = components["schemas"]["Problem"];
export type CheckIssue = components["schemas"]["CheckIssue"];

const TITLES: Record<number, string> = {
  401: "Нужен вход",
  403: "Только чтение",
  404: "Не найдено",
  409: "Уже решено",
  408: "Служба не дождалась запроса",
  413: "Слишком большой запрос",
  422: "Отклонено проверкой",
  503: "Служба недоступна",
  507: "Место исчерпано",
};

/** Заголовок по коду problem+json — точнее, чем по статусу (503 бывает и «нет службы», и «не уложилась»). */
const CODE_TITLES: Record<string, string> = {
  body_timeout: "Служба не дождалась тела запроса",
  timeout: "Служба не уложилась в 15 с — сузьте глубину или выбор",
  quota_exceeded: "Место под подборки и загрузки исчерпано",
  read_only: "Токен только для чтения",
};

/** Ошибка службы в формате problem+json (RFC 9457), разобранная для экрана. */
export class ApiError extends Error {
  constructor(
    public status: number,
    public title: string,
    public detail?: string,
    public code?: string,
    public issues: CheckIssue[] = [],
  ) {
    super(detail ?? title);
    this.name = "ApiError";
  }
}

export async function problemFromResponse(res: Response): Promise<ApiError> {
  const type = res.headers.get("content-type") ?? "";
  if (type.includes("json")) {
    try {
      const p = (await res.json()) as Partial<Problem>;
      return new ApiError(
        p.status ?? res.status,
        (p.code && CODE_TITLES[p.code]) || p.title || TITLES[res.status] || "Ошибка",
        p.detail,
        p.code,
        // у check_rejected рядом с ошибками — предупреждения (private_removed и др.): человек видит всё сразу
        [...(p.issues ?? []), ...(p.warnings ?? [])],
      );
    } catch {
      // тело не JSON: остаётся ошибка по статусу
    }
  }
  return new ApiError(res.status, TITLES[res.status] ?? "Ошибка");
}

/** Сеть недоступна вовсе (служба не запущена). */
export function offlineError(cause: unknown): ApiError {
  return new ApiError(0, "Нет связи со службой amemo", cause instanceof Error ? cause.message : undefined);
}

/** Текст ошибки для человека: что случилось; для обрыва связи — подсказка, что делать. */
export function errorText(err: unknown, offline: string): string {
  if (err instanceof ApiError) return err.status === 0 ? offline : (err.detail ?? err.title);
  return offline;
}
