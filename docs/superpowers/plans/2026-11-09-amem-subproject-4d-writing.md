# amem — подпроект 4, часть 4d «Запись человека: формы, свои виды, загрузка, задачи агентам»: план реализации

> **Для исполнителей-агентов:** задачи выполняются через superpowers:subagent-driven-development — свежий субагент на задачу, ревью после каждой. Шаги — с флажками (`- [ ]`).

09.11.2026. Дополняет `docs/superpowers/specs/2026-11-07-amem-subproject-4-service-design.md` (часть 4d в спецификации появляется в задаче 16 этого плана) и закрывает пути контракта, которые тест полноты держит в списке `LATER_4D` (`tests/test_service_contract.py`). Сторона веба уже сделана (подпроект 5, часть D, план — PR #21; моки — `web/src/mocks/handlers-d.ts`).

**Цель:** служба отдаёт вебу формы по шаблонам видов, хранит свои виды человека в базе («Мои виды»), принимает загрузку файлов в папку документов и ищет объекты, ведёт очередь задач агентам с выдачей через MCP.

**Архитектура:**
- библиотека — новые модули `amem/forms.py` (форма из шаблона), `amem/mine.py` (пакет «Мои виды» в базе), `amem/tasks.py` (задачи агентам); правки `amem/db.py` (пакет mine переживает `prepare`), `amem/bundle.py` (mine в подборке), `amem/lookup.py` (поиск объектов);
- `amem/api.py` — операции в форме контракта; `amem/service/http_v1.py` — пути; `amem/service/mcp.py` — инструменты задач; `amem/cli` — `amem tasks`;
- контракт не меняется, кроме мест, названных в задачах (их правит служба; копия в пакете — байт в байт).

**Стек:** как в подпроекте 4: Python 3.11+, PostgreSQL 18/16, psycopg 3, Starlette, `mcp` 2.3, LinkML → Pydantic (`tools/gen_schema.py`).

**Проверки — только в CI** (просьба пользователя, 09.11: локальные прогоны грузят машину). Локально — дешёвое: `ruff check amem tests tools`, `python -m py_compile`, `pytest --collect-only -q`, `tools/gen_schema.py --check`, `npx @redocly/cli@2 lint docs/api/http-v1.openapi.yaml`, `npm run api:check` в `web/`. Тесты гоняет CI на push ветки: `gh run list --branch subproject-4d-writing`, `gh run watch <id> --exit-status`, при падении — `gh run view <id> --log-failed`.

**Формат задачи:** падающий тест → реализация → push → зелёный CI → коммит исправлений, если нужно. Противоречие спецификации — сначала правится спецификация с причиной.

**Ветка:** `subproject-4d-writing` (worktree `~/projects/amem-4d`, от main после PR #38). PR с автослиянием после зелёных `test` и `commits`.

**Коммиты:** Conventional Commits на английском — `type(scope): subject` до 100 знаков, пустая строка, тело на английском, число тестов в теле (`3128→3150 tests`), последняя строка `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Хук `tools/hooks/commit-msg` и проверка `commits` в CI отклоняют другое.

**Правила:** тестовые данные нейтральны (вымышленные марки и нормы, без компаний, людей и личных путей); ошибки — свои классы-наследники `ValueError`; SQL совместим с PG16; новые id — UUIDv7.

---

## Решения (до задач)

1. **Семья вида.** `Concept.family` в схеме v1 — `source | work` (только виды атомов). Контракт (`TemplateView.family`, `TemplateDraft.family`) знает ещё `object` — у шаблонов сущностей. Служба выводит `object` для `target: entity`; в черновике сущности допустимо только `object`, у атома — `source | work` (иначе 422). Схема v1 не меняется.
2. **Блок `ui` у шаблона.** Новый необязательный слот `Template.ui` в `amem/schema/amem_v1.yaml`: `{body: wanted | required | none, widgets: [sources | links | around | values_table | similar | children], fields: [{path, label: {ru, en}, hint: {ru, en}, type?}]}`. Проверка пакета (`packs._check_ui`): путь `fields` — правило шаблона, его предков по `extends` или интерфейсов его target, поле, которое форма показывает всегда (`packs.UI_BASE`: у атома `about`, `tags`; у сущности `codes`), или величина `content.values[property=X]` / `qualifiers[property=X]` с X из словаря property (только у атома); путь не повторяется; `ui` — только у atom и entity. Иначе — ошибка пакета с файлом, шаблоном и путём. На проверку записей блок не влияет.
   *Поправка 09.11 (задача 17):* `fields` — список с `path`, а не отображение `{<path>: …}`: LinkML строит отображение только по полю-идентификатору, и тогда `path` обязателен внутри каждого значения — запись `{about: {label: …}}` не проходит строгую проверку. Список — как у `Template.fields`. Ключи `parameters` в `ui` не нужны: параметры профиля — не поля формы (решение 3). Путь `content.values[property=X]` не может быть правилом поля (`FieldRule.path` не знает отбора по property), поэтому величины формы задаются в `ui`, а правило `content.values` остаётся проверкой «хотя бы одно значение».
3. **Форма вида** (`amem/forms.py`). *Поправка 09.11 (задача 17)* — первая редакция («поле на каждый `FieldRule` и параметр шаблона») с ядром не сходится: у ядра всего два шаблона своих видов (`decision`, `note`) и три интерфейса (`has_label`, `has_source`, `has_value`), чьи правила — `label`, `summary_plain`, `sources[].selectors`, `content.values[].unit` — это проверки, а не поля формы; у семи видов ядра своего шаблона нет, а веб выбирает вид из `GET /templates`; у `FieldRule` нет ни словаря, ни вида связи; параметры профиля — значения атомов `parameter` о сущности, у тела сущности нет `content`. Правила теперь такие:
   - форма есть у каждого вида атома (словарь `kind`) и класса сущности (`entity_class`), с шаблоном или без; правила сводятся, как при проверке (`check.templates.rules_for`: интерфейсы target, затем свой шаблон с `extends`); `TemplateView.code` и `applies_to` — код вида, `pack` — откуда понятие вида, `label` — подпись понятия, `description` — описание своего шаблона, иначе определение вида;
   - поле формы — правило, чей путь — поле тела верхнего уровня, которое заполняет человек (не `label`, `summary_plain`, `body`, `description`, `sources`, `basis` и служебные; не составное — `Scope`, `Content`, `LangString`; правило с `[]` или с точкой — ограничение), плюс `content.values`; плюс поля `packs.UI_BASE`; плюс величины из `ui.fields`; `parameters` — не поля (их показывает карточка);
   - тип — из `ui.fields[path].type`, иначе по пути: `about` → `object` (`accepts.entity_classes` — из правила); `content.values` и `content.values[property=X]` → `quantity` (`property` = X, `unit` — единица словаря property); `qualifiers[property=X]` → `text`; `valid_from`/`valid_to` → `date` (оба сразу — одно поле `period`, ключ `valid`); `tags` → `tags`; перечень схемы со словарём в базе (`packs.SERVICE`: `rank`, `status`, …) → `choice` (`scheme`); поле, через которое задаётся связь (`rel.via_field`, кроме `about`: `derived_from`) → `record` (`accepts.rel`); другой список строк (`codes`, `aliases`) → `tags`; иначе `text`;
   - величины `ui` заменяют общее поле `content.values`; правило `content.values` просит хотя бы одно значение, поэтому величина обязательна, только если она одна; `required` прочих полей — из правила;
   - подпись и подсказка — из `ui.fields`, иначе из словаря property (`label`, `definition`), иначе подпись поля записи (`forms.LABELS`), иначе сам путь; блок `ui` сводится по порядку применения шаблонов (поле — по path, `body` и `widgets` — у последнего, где заданы); `body` по умолчанию `wanted`, `widgets` — `[sources, links]`.
4. **Пакет «Мои виды» (`mine`).** Строка в таблице `pack` с именем `mine`; версия `0.0.N` растёт с каждой правкой, digest — `canon.content_hash` всех действующих шаблонов mine. Шаблоны — строки `template` (каждая правка — новая `version` шаблона, `template_active` переключается), понятия вида — `concept` с `origin = 'mine'`. Проверка — та же, что у пакета из файла: из базы собирается `Pack` mine и проверяется вместе с загруженными пакетами (`packs._check_templates`).
5. **Код своего вида** — `[a-z][a-z0-9_]{1,63}`, не совпадает с кодом из пакетов-файлов (409 `template_exists`). Если позже пакет из файла принесёт тот же код — `db.prepare` отказывает с `MigrationError`, называя код и пакет.
6. **`db.load_vocab` сохраняет mine:** понятия `origin = 'mine'` не считаются осиротевшими; после пересборки `template_active` в неё возвращаются действующие шаблоны mine (последняя версия каждого кода, если код не удалён).
7. **Удаление своего вида** — 409 `template_in_use`, если есть записи этого вида (любого статуса); иначе шаблон уходит из `template_active`, понятие удаляется, пакет mine получает новую версию. Старые версии шаблона остаются в `template` (на них ссылаются проверенные ранее записи).
8. **Права.** Свои виды правит и удаляет только `person:` (модель — 403 `forbidden`; токен `read_only` — 403 `read_only`). Загружать файлы и ставить задачи могут человек и модель; `read_only` — нет. Брать и закрывать задачи — только модель (через MCP); отменить — тот, кто поставил, или человек.
9. **Загрузка файла.** `POST /objects` (multipart, поле `file`, необязательное `path`): путь в папке документов — `path` или `Загрузки/<имя файла>` (NFC, `objects._check_relative`). Тот же файл по пути (тот же digest) — 200 с `ObjectView`; по пути лежит другой файл — 409 `object_path_taken`; иначе файл пишется атомарно и `objects.ingest` — 201. Нет `AMEM_DOCS` — 503 `docs_unavailable`. Предел — `UPLOAD_LIMIT` загрузок (как у подборок), квота `AMEM_STATE_QUOTA` не тратится (файл ложится в папку документов, а не в состояние службы). Нужен `Origin` своей службы (как у `/bundles/inspect`).
10. **Задачи агентам** — таблица `task` (миграция `0012_tasks.sql`): `id` UUIDv7, `kind` (`parse`), `object` + `version`, `note`, `state` `open | claimed | done | cancelled`, `created_by`, `created_at`, `claimed_by`, `claimed_until` (аренда 30 мин, как у очереди проверки), `done_at`, `result` (jsonb: что сделано — ссылки записей). Одна открытая задача на (kind, object, version): повтор возвращает её `task_id` (идемпотентно, 202). MCP: `amem_tasks` (открытые и свои), `amem_task_claim`, `amem_task_release`, `amem_task_done` (с `result`).
11. **Подборки.** `bundle.export(with_packs=True)` кладёт mine как обычный пакет (`packs/mine/` с `pack.yaml` и шаблонами, собранными из базы). `bundle.import_` с пакетом mine: шаблоны, которых в базе нет, добавляются в mine; тот же код с другим содержимым — коллизия `bundle_pack_conflict` (422, в отчёте `collisions`); `dry_run` показывает, что будет добавлено.

## Структура файлов

| Файл | Что в нём |
|---|---|
| `amem/schema/amem_v1.yaml`, `amem/model_v1.py` (генерируется) | слот `Template.ui`, классы `TemplateUi`, `TemplateUiField` |
| `amem/packs.py` | проверка `ui.fields` по путям шаблона |
| `amem/forms.py` (новый) | `form(conn, target, code) -> list[dict]`, `views(conn, *, target=None, code=None) -> list[dict]` (TemplateView; один вид — `code`) |
| `amem/mine.py` (новый) | `put(conn, code, draft, *, agent) -> dict`, `delete(conn, code, *, agent) -> None`, `templates(conn) -> list`, `as_pack(conn) -> packs.Pack`, `MineError(code)` |
| `amem/db.py` | `load_vocab` сохраняет mine (решение 6) |
| `amem/sql/0012_tasks.sql` (новый) | таблица `task`, индексы, CHECK UUIDv7 |
| `amem/tasks.py` (новый) | `create`, `list_`, `claim`, `release`, `done`, `cancel`, `TaskError(code)` |
| `amem/lookup.py` | `object_search(conn, q, *, limit, cursor) -> dict` |
| `amem/bundle.py` | mine в `export(with_packs)` и в `import_` |
| `amem/api.py` | `templates`, `template_put`, `template_delete`, `object_search`, `object_upload`, `task_create`, `task_list`, `task_claim`, `task_release`, `task_done` |
| `amem/service/http_v1.py` | пути `/templates`, `/packs/mine/templates/{code}`, `/objects` GET/POST, `/tasks` GET/POST |
| `amem/service/problems.py` | `MineError`, `TaskError` → коды и статусы (таблица 3.2) |
| `amem/service/mcp.py` | инструменты `amem_tasks`, `amem_task_claim`, `amem_task_release`, `amem_task_done` |
| `amem/cli/commands/tasks.py` (новый) | `amem tasks list|cancel` |
| `tests/test_forms.py`, `tests/test_mine.py`, `tests/test_tasks.py`, `tests/test_service_4d.py` (новые) | тесты задач 17–21 |

---

## Часть 4d

### Task 16: Спецификация части 4d

**Files:** `docs/superpowers/specs/2026-11-07-amem-subproject-4-service-design.md` (новый разд. «Часть 4d» после разд. 6, строки таблицы ошибок 3.2, строки приёмки разд. 9).

- [ ] Перенести в спецификацию решения 1–11 этого плана — коротко, без кода.
- [ ] Таблица 3.2 — новые коды: `MineError(exists)` → 409 `template_exists`; `MineError(in_use)` → 409 `template_in_use`; `MineError(invalid)` → 422 `template_invalid` (с `issues` в форме `CheckIssue`, `path` — путь в черновике); `object_path_taken` → 409; `docs_unavailable` → 503; `TaskError(not_found)` → 404; `TaskError(closed | claimed)` → 409 `task_closed` / `task_claimed`; `TaskError(forbidden)` → 403.
- [ ] Разд. 9 — строки приёмки 4d со ссылками на тесты задач 17–21.
- [ ] Коммит `docs(spec): subproject 4, part 4d — forms, my kinds, uploads, agent tasks`.

### Task 17: Блок `ui` и форма из шаблона, `GET /templates`

**Files:** `amem/schema/amem_v1.yaml`, `amem/model_v1.py` (через `tools/gen_schema.py`), `amem/packs.py`, `amem/forms.py`, `amem/api.py`, `amem/service/http_v1.py`, `tests/test_forms.py`, `tests/test_service_4d.py`.

- [ ] Падающие тесты `tests/test_forms.py`:
  - пакет с шаблоном, у которого `ui.fields` содержит путь без правила (и не поле `UI_BASE`, не величину словаря), — ошибка пакета, названы файл, шаблон и путь; путь интерфейса, предка и величина словаря — можно;
  - форма вида тестового пакета (`tests/packs/forms`) с `about`, величинами `ui`, `valid_from` и `valid_to`, `tags`, `rank` и `derived_from` даёт типы `object`, `quantity` (с `property` и `unit`), `period`, `tags`, `choice`, `record` (с `accepts`);
  - вид ядра без своего шаблона — форма `about`, `tags`: правила интерфейсов полями не становятся; профиль сущности — не поля;
  - `ui.fields[path].type` перекрывает выведенный тип; подпись из `ui` перекрывает словарь, без `ui` — подпись словаря property;
  - `body` и `widgets` по умолчанию — `wanted` и `[sources, links]`.
- [ ] Схема: слот `ui` (range `TemplateUi`), классы `TemplateUi`, `TemplateUiField`, перечни `TemplateBody`, `TemplateWidget`, `FieldType`; `tools/gen_schema.py` перегенерирует `amem/model_v1.py`; `gen_schema.py --check` чистый.
- [ ] `amem/forms.py` по решению 3; `views` собирает `TemplateView` контракта (`family` по решению 1, `editable` — вид из mine, `records` — число записей вида одним запросом).
- [ ] `api.templates(conn, *, target=None)` — формы всех видов и классов (решение 3), по `target`; путь `GET /templates?target=` в `http_v1.py`.
- [ ] Тест службы в `tests/test_service_4d.py`: ответ по строгой схеме контракта (`tests/contract.py`), `target=link` — 400.
- [ ] Убрать `("/templates", "get")` из `LATER_4D` в `tests/test_service_contract.py`.
- [ ] `ruff`, `--collect-only`, push, зелёный CI. Коммит `feat(templates): ui block, form from a template, GET /templates`.

### Task 18: Пакет «Мои виды» в базе

**Files:** `amem/mine.py`, `amem/db.py`, `amem/api.py`, `amem/service/http_v1.py`, `amem/service/problems.py`, `tests/test_mine.py`, `tests/test_service_4d.py`.

- [ ] Падающие тесты `tests/test_mine.py`:
  - `put` нового кода создаёт понятие вида (`origin = 'mine'`, `family` из черновика), шаблон `version` `1.0.0`, строку `pack` `mine 0.0.1` и делает шаблон действующим; запись этого вида проходит `check.submit`;
  - повторный `put` с тем же черновиком ничего не меняет (версии те же); с другим — шаблон `1.0.1`, пакет `0.0.2`, старая версия остаётся в `template`;
  - код из пакета-файла — `MineError(exists)`; неверный код — `MineError(invalid)`;
  - черновик, не проходящий проверку пакета (путь, которого нет в схеме записи), — `MineError(invalid)` с замечаниями;
  - `family` не по решению 1 — `MineError(invalid)`;
  - `delete` вида с записью — `MineError(in_use)`; без записей — шаблон не действующий, понятия нет, пакет `0.0.N+1`;
  - `db.prepare` повторно — свои виды остаются действующими, понятия на месте (решение 6);
  - пакет-файл с тем же кодом, что у своего вида, — `prepare` отказывает с `MigrationError`, текст называет код;
  - модель (`model:…`) — отказ на `put` и `delete`.
- [ ] `amem/mine.py`: черновик контракта (`TemplateDraft`) → `Template` (`fields` из `FormField.path` и `required`; поле `content.values[property=X]` или `qualifiers[property=X]` — запись в `ui.fields` и правило `content.values` / `qualifiers`, обязательное, если обязательна хоть одна величина (решения 2 и 3: отбора по property у `FieldRule` нет); поле `period` — правила `valid_from` и `valid_to`; `ui` из подписей, подсказок, типов, `body`, `widgets`), понятие вида, проверка через `as_pack` вместе с `packs.load_packs()`, запись в одной транзакции под замком пакетов (свой advisory lock, как `FOLDERS_LOCK`).
- [ ] `db.load_vocab` — решение 6, плюс проверка решения 5.
- [ ] `api.template_put` / `api.template_delete`, пути `PUT` и `DELETE /packs/mine/templates/{code}`, коды ошибок в `problems.py` (таблица 3.2 из задачи 16); ответ `PUT` — `TemplateView` с `editable: true`.
- [ ] Тест службы: человек — 200 и 204; модель — 403; `read_only` — 403; занятый код — 409; ответ по строгой схеме.
- [ ] Убрать оба пути из `LATER_4D`. Push, зелёный CI. Коммит `feat(mine): "My kinds" pack in the database — PUT/DELETE /packs/mine/templates/{code}`.

### Task 19: «Мои виды» в подборках

**Files:** `amem/bundle.py`, `amem/mine.py`, `tests/test_bundle_export.py`, `tests/test_bundle_import.py`.

- [ ] Падающие тесты:
  - `export(with_packs=True)` в базе со своим видом кладёт `packs/mine/` (манифест пакета и шаблоны), запись своего вида в подборке ссылается на него;
  - импорт такой подборки в чистую базу добавляет вид в mine, запись проходит проверку; `dry_run` показывает вид и ничего не пишет;
  - импорт в базу, где тот же код есть с другим содержимым, — коллизия `bundle_pack_conflict` в отчёте, запись в очередь не попадает молча;
  - без `with_packs` подборка со своим видом даёт `bundle_pack_missing` при импорте в чистую базу (как сейчас для пакетов-файлов).
- [ ] `mine.as_pack` пишет пакет на диск (`write_pack(folder)`); `bundle.import_` принимает mine через `mine.put` от агента импорта (права — по правилам подборок: настоящий импорт — только человек).
- [ ] Push, зелёный CI. Коммит `feat(bundle): "My kinds" travel with a bundle (with_packs)`.

### Task 20: Поиск и загрузка объектов

**Files:** `amem/lookup.py`, `amem/api.py`, `amem/service/http_v1.py`, `tests/test_service_4d.py`, `tests/test_lookup_lists.py`.

- [ ] Падающие тесты:
  - `lookup.object_search(q)` находит объект по части имени и по части пути без учёта регистра, курсор листает, `limit` 1–100; пустой `q` — последние объекты;
  - `POST /objects` с новым файлом — 201, файл лежит в `AMEM_DOCS/Загрузки/<имя>`, `ObjectView` по строгой схеме; с `path` — по этому пути;
  - тот же файл ещё раз — 200, второй версии нет; другой файл по занятому пути — 409 `object_path_taken`, файл на диске не тронут;
  - `path` с `..`, абсолютный, NUL — 400; без `AMEM_DOCS` — 503 `docs_unavailable`;
  - больше предела — 413, недокачанное удалено; без `Origin` своей службы — 403; `read_only` — 403;
  - `GET /objects` — по строгой схеме.
- [ ] Загрузка — тем же потоковым разбором multipart, что у `/bundles/inspect` (`http_v1._Upload`), во временный файл рядом с целевым, затем `os.replace` и `objects.ingest`; при ошибке ingest временный файл удаляется, а записанный — остаётся только если ingest прошёл.
- [ ] Убрать оба пути `/objects` из `LATER_4D`. Push, зелёный CI. Коммит `feat(objects): object search and upload — GET/POST /objects`.

### Task 21: Задачи агентам

**Files:** `amem/sql/0012_tasks.sql`, `amem/tasks.py`, `amem/backup.py` (`COUNTED`), `amem/api.py`, `amem/service/http_v1.py`, `amem/service/problems.py`, `amem/service/mcp.py`, `amem/cli/commands/tasks.py`, `amem/cli/commands/__init__.py`, `tests/test_tasks.py`, `tests/test_service_4d.py`, `tests/test_mcp.py`, `tests/test_cli.py`.

- [ ] Миграция `0012_tasks.sql` по решению 10 (CHECK формата UUIDv7 и состояний, частичный уникальный индекс открытых задач по (kind, object, version), внешний ключ на `object_version`); тест миграций на базе с данными; `task` — в `backup.COUNTED`.
- [ ] Падающие тесты `tests/test_tasks.py`:
  - `create` даёт `open`; повтор на ту же версию — тот же id;
  - `claim` моделью — `claimed` с арендой 30 мин; вторая модель — `TaskError(claimed)`; после истечения аренды (подменённые часы) задачу берёт другая;
  - `release` — снова `open`; `done` с `result` — `done`, повторный `done` — `TaskError(closed)`;
  - `cancel` — поставивший или человек; чужая модель — `TaskError(forbidden)`;
  - `claim`/`done` человеком — `TaskError(forbidden)`.
- [ ] Пути `GET /tasks?state=&object=` и `POST /tasks` (202 `{task_id}`) — по строгой схеме; `read_only` — 403.
- [ ] MCP: `amem_tasks`, `amem_task_claim`, `amem_task_release`, `amem_task_done` (запись — `write=True`, `idempotent_hint` у release и done); тест через клиент SDK: поставить задачу HTTP → взять, закрыть через MCP → `GET /tasks` видит `done`.
- [ ] CLI `amem tasks list [--state]` и `amem tasks cancel ID` с кодами выхода разд. 5.1.
- [ ] Убрать пути `/tasks` из `LATER_4D` — список становится пустым; тест «список честный» оставить на будущее (пустое множество проходит).
- [ ] Push, зелёный CI. Коммит `feat(tasks): agent tasks — table, GET/POST /tasks, MCP tools, amem tasks`.

### Task 22: Завершение части 4d

**Files:** `README.md`, `README.ru.md`, `docs/api/README.md`, `web/src/api/schema.d.ts` (если менялся контракт), спецификация разд. 9.

- [ ] README (оба, параллельно): «Мои виды», загрузка файлов, задачи агентам и инструменты MCP задач.
- [ ] `docs/api/README.md` — новые коды ошибок 4d.
- [ ] Если контракт менялся — `cd web && npm run api:types && npm run api:check`, копия контракта в пакете байт в байт.
- [ ] Ревью ветки целиком (субагент, только чтение), проверка на приватное по diff ветки (её делает хук pre-push; вручную — тем же списком слов, что в хуке), правки по ревью.
- [ ] PR `feat: subproject 4, part 4d — forms, my kinds, uploads, agent tasks` с автослиянием (`gh pr merge --auto --merge`); после слияния — сообщить сессии веба, что пути части D реализованы (вместе с невручённым ранее сообщением из `~/projects/amem-sdd/web-notes.md`).

---

## Критерии готовности

- Список `LATER_4D` в `tests/test_service_contract.py` пуст: каждый путь контракта реализован.
- Свои виды переживают перезапуск службы (`db.prepare`), уезжают в подборке с `with_packs` и не пересекаются с пакетами-файлами.
- Запись своего вида проходит те же проверки, что и запись вида из пакета.
- Загрузка не выходит за папку документов и не создаёт дублей по digest.
- Задача, поставленная человеком в вебе, берётся и закрывается агентом через MCP и видна в `GET /tasks`.
- CI зелёный (`test`, `commits`, `web`, `web-service`, `docker`).
