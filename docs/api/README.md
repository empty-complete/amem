# HTTP-контракт amem v1

`http-v1.openapi.yaml` — контракт между службой amem (подпроект 4) и веб-интерфейсом (подпроект 5, `web/`).
Спецификация — `docs/superpowers/specs/2026-11-06-amem-subproject-5-web-ui-design.md`, разд. 6.

- **Реализует** служба: отдаёт контракт по `/api/v1/openapi.json`, её тесты сверяют ответы со схемами.
- **Потребляет** веб-UI: типы генерируются из файла (`cd web && npm run api:types`), CI проверяет свежесть (`npm run api:check`), фикстуры моков проверяются схемами (`web/tests/contract.test.ts`).
- **Менять** — только правкой этого файла в PR, который проходит обе стороны. Линтер: `npx @redocly/cli lint docs/api/http-v1.openapi.yaml --config docs/api/redocly.yaml`.
- **Ошибки** — `application/problem+json` (RFC 9457): `type`, `title`, `status`, `detail`, `code`; отказ проверки — ещё `issues` (`CheckIssue`). 401 — нужен вход, 403 — только чтение, 409 — пункт уже решён, 422 — отказ проверки, 503 — база недоступна.
- **Агент записи** служба берёт из сессии (`person:…`); UI его не передаёт.
- **Вход** — `Authorization: Bearer`, только если служба его потребовала; локальная служба работает без входа.

## Изменения

- **Часть B веб-интерфейса (чтение).** `ObjectView.cited_by` — массив `ObjectCitation` (запись, версия, место, цитата, итог сверки) вместо подписей; у `ObjectView` — `pages` (из кэша текста, `null`, пока текст не извлекался) и `sheets` (только xlsx/xlsm); путь `GET /objects/{id}/versions/{n}/sheet` (ячейки листа, не больше 10 000, иначе 413); у `RecordView` — `about` и `ancestors` с подписями; фильтр `about` у `GET /records`.
