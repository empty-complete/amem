# amemo — подпроект 4 «Служба, CLI и память агентов»: план реализации

> **Для исполнителей-агентов:** задачи выполняются через superpowers:subagent-driven-development — свежий субагент на задачу, ревью после каждой. Шаги — с флажками (`- [ ]`).

07.11.2026. Исполняет `docs/superpowers/specs/2026-11-07-amemo-subproject-4-service-design.md` (редакция 1 с правками по ревью).

**Цель:** служба HTTP (контракт веба v1) и MCP, CLI с кодами выхода, хуки и установщик для Claude Code и Codex — поверх библиотеки, дополненной в части 4.0.

**Архитектура:**
- `amemo/api.py` — операции в форме ответов контракта, без Starlette;
- `amemo/service/` — тонкий слой Starlette: маршруты, сессия, защита, `problem+json`, `/mcp`, `/ui`;
- `amemo/cli/` — команды на `argparse`;
- `amemo/agents/` — хуки, матрица платформ, установщик.

**Стек:** Python 3.11+, PostgreSQL 18/16, psycopg 3 + `psycopg_pool`, Starlette + uvicorn, `mcp` (официальный SDK), `python-multipart`, jsonschema (тесты).

**Формат:** каждая задача — падающий тест → реализация → focused → полный прогон на обеих базах → коммит. Красный тест не пропускается. Противоречие спецификации — сначала правится спецификация с причиной.

**Части и ветки** (PR с автослиянием после зелёной проверки `test`, затем обновить `main` и удалить ветку):
- **4.0** — `subproject-4-0-library`: задачи 1–4;
- **4a** — `subproject-4a-service`: задачи 5–9;
- **4b** — `subproject-4b-cli-mcp`: задачи 10–12;
- **4c** — `subproject-4c-agents`: задачи 13–15.

**Команды:**

```bash
cd ~/projects/amemo
export AMEMO_TEST_DSNS="postgresql://test:test@127.0.0.1:<pg18>/test,postgresql://test:test@127.0.0.1:<pg16>/test"
export AMEMO_PG_BIN=<bin клиента PostgreSQL 18>
env -u PYTHONPATH .venv/bin/pytest -q -p no:cacheprovider; echo "exit=$?"
.venv/bin/python tools/gen_schema.py --check
```

Правила:
- тестовые данные нейтральны;
- сообщения коммитов начинаются с `lib:`, `service:`, `cli:`, `mcp:`, `agents:` или `docs:`, называют число новых тестов и кончаются строкой `Co-Authored-By`;
- код возврата pytest проверяется явно.

---

## Часть 4.0 — библиотека для службы

### Task 1: Папки

**Files:** `amemo/sql/0008_folders.sql`, `amemo/folders.py`, `amemo/db.py` (четыре папки при первом `base_id`), `amemo/recipes.py` (события `folder`), `amemo/backup.py` (`COUNTED` + `folder`, `folder_log`), `tests/test_folders.py`, `tests/test_db.py`, `tests/test_sql_schema.py`.

- [ ] Падающие тесты:
  - **`folders.check`:**
    - принимает `Проекты/Альфа`;
    - отвергает (`FolderError`, код `invalid`): пустой сегмент, «/» в конце, `.` и `..`, управляющий символ, сегмент из 101 знака, 9 уровней, путь `-`;
    - приводит к NFC и обрезает пробелы у сегментов.
  - **`move`:**
    - атом переходит в папку, у него нет новой ревизии, `content_hash` прежний;
    - в `folder_log` — строка `from`/`to`/агент;
    - родители появляются в реестре;
    - перенос в `None` — «без папки»;
    - модель вправе переносить.
  - **`create`:** повтор — код `exists`.
  - **`delete`:** удаляет пустую; если в папке запись или вложенная папка — `not_empty`.
  - **`rename`:**
    - `a` → `b` переносит `a/x` в `b/x` и записи с журналом по каждой;
    - занятый новый путь — `exists`;
    - перенос в собственного потомка — `invalid`.
  - **`tree`:**
    - пустая папка видна;
    - `count` по вложенности;
    - `unfiled` и `total`;
    - порядок детей — по имени.
  - **`db.prepare` новой базы:**
    - четыре папки в реестре («Проекты», «Области», «Ресурсы», «Архив»);
    - повторный `prepare` их не дублирует;
    - удалённая пользователем папка не возвращается.
  - **`what_changed`:** событие `folder` с `from`/`to`.
  - **Таблицы:** `folder_log` неизменяем, триггеры и TRUNCATE запрещены (`PROTECTED` в `test_db`).
- [ ] **Миграция 0008:**
  - `ALTER TABLE atom|entity ADD folder text` с CHECK (`folder IS NULL OR (folder <> '' AND length(folder) <= 900)`);
  - индексы по `folder`;
  - `folder` (`path text PRIMARY KEY`, `created_at`, `created_by` → `agent`);
  - `folder_log` (`id` UUIDv7, `target` atom|entity, `record_id`, `folder_from`, `folder_to`, `agent`, `changed_at`) с триггерами `amemo_forbid_change`.
- [ ] **Реализация.**
  - **`amemo/folders.py`:** `FolderError(ValueError)` с `code`; функции `check`, `move`, `create`, `delete`, `rename`, `tree`.
  - **SQL:** префикс — `folder = %s OR starts_with(folder, %s || '/')`, без `LIKE`.
  - **Блокировки** — как у `records.set_status`:
    1. сначала агент;
    2. затем блокировка записи `FOR NO KEY UPDATE`;
    3. время — не раньше последнего изменения записи.
  - **`rename`** блокирует все записи папки по возрастанию id.
  - **`db.prepare`** создаёт четыре папки в той же транзакции, где впервые ставится `base_id`. Агент — служебный `model:amemo-init`, или поле `created_by` допускает NULL — выбрать и обосновать.
- [ ] Focused, полный прогон, коммит `lib: папки — реестр, перенос без ревизии, журнал, дерево; четыре папки новой базы`.

### Task 2: Ссылки по ключу, список записей, подписи

**Files:** `amemo/records.py` (`resolve`, `RecordNotFound`), `amemo/lookup.py` (`list_records`, `labels`, `get` принимает ref), `amemo/recipes.py`, `amemo/profile.py`, `tests/test_lookup_lists.py`.

- [ ] Падающие тесты:
  - **`records.resolve`:**
    - `atm:<uuid>`, `atm:<ключ>` и `ent:<ключ>` дают `(target, uuid)`;
    - неизвестная ссылка — `RecordNotFound` (подкласс `RecordError`);
    - мусор — `RecordError`.
  - **По ключу:** `what_changed(ref=…)`, `around_entity`, `similar("atm:<ключ>")`, `profile.card("ent:<ключ>")` находят запись.
  - **`lookup.list_records`:**
    - фильтры `folder` (с вложенными; `-` — без папки), `kinds`, `statuses`, `tag`, `about` (`ent:` ссылка);
    - курсор по `(recorded_at, id)` текущей ревизии: страницы без пропусков и повторов при 120 записях и `limit` 50;
    - `total` — по фильтру;
    - поля сводки: `ref`, `target`, `label` (ru), `kind_or_class`, `status`, `folder`, `about` (ссылки), `tags`, `recorded_at`, `agent`.
  - **`lookup.labels(conn, refs)`:**
    - один запрос: подпись, вид или класс, статус;
    - неизвестные ссылки — без ключа в ответе.
- [ ] Реализация. Ответы — JSON-совместимые словари, время — ISO 8601. Существующие вызовы с UUID работают как прежде.
- [ ] Focused, полный прогон, коммит.

### Task 3: Рецепты, польза, очередь, словарь, база, бэкапы

**Files:** `amemo/search.py`, `amemo/recipes.py`, `amemo/usefulness.py`, `amemo/review.py`, `amemo/schema/amemo_v1.yaml` (+ генерация), `amemo/packs/core/**` (1.3.0, `family`), `amemo/db.py`, `amemo/backup.py`, `tests/test_service_lib.py`, правки существующих тестов.

- [ ] Падающие тесты:
  - **Поиск:** `exact_fact`/`similar` с `kind=["fact","term"]` и `entity_class=[…]`.
  - **`log=False`:** в `retrieval` ничего, `retrieval_id is None`.
  - **`what_changed(limit=…, who="person")`:** у событий ревизий и связей есть `agent`, `limit` режет самые старые.
  - **`usefulness.session_activity(conn, "mcp:x")`:**
    - одна задача на метку, вид `session`;
    - поиск с этой задачей и `mark_helpful` с ней проходят;
    - выдача другой задачи — отказ.
  - **`ReviewError.code`:**
    - `closed` (у ошибки есть `by`, `at`);
    - `forbidden`;
    - `bad_outcome`;
    - `stale`;
    - `claimed`.
  - **`Concept.family`:** поле в схеме; ядро 1.3.0 размечает свои виды; понятие вида без `family` считается `work` (функция `vocab.family(conn, kind)` или поле в `concept.data`).
  - **Имя базы:** `db.set_base_name` и чтение имени.
  - **`backup.backups`:** отдаёт `created_at` и `size`.
- [ ] Реализация; `gen_schema.py` и `--check`; тесты, сверявшие ядро 1.2.0, обновить по смыслу.
- [ ] Focused, полный прогон, коммит.

### Task 4: Объект для карточки документа и лист xlsx

**Files:** `amemo/lookup.py` (`object_view`), `amemo/objects.py` или `amemo/extract.py` (`sheet`), `tests/test_object_view.py`.

- [ ] Падающие тесты:
  - **`object_view`:**
    - `cited_by` — источники текущих ревизий: запись, версия, селекторы, цитата, итог сверки;
    - `pages` — из кэша текста или `None`;
    - `sheets` — листы xlsx/xlsm из извлечённого текста, у остальных `None`;
    - `status` — строка последней отметки или `None`.
  - **`objects.sheet(conn, store, id, n, name, "B2:D4")`:**
    - строки ячеек;
    - лист не найден — `ObjectError` (код `not_found`);
    - больше 10 000 ячеек — код `too_large`;
    - неверный диапазон — `ObjectError`.
- [ ] Реализация: `openpyxl` read_only по копии из хранилища.
- [ ] Focused, полный прогон, коммит.

### Завершение части 4.0

- [ ] Ревью ветки субагентом; Critical и Important исправлены.
- [ ] Полный прогон, `gen_schema --check`, проверка на приватное, пуш, PR, автослияние, обновить `main`.

---

## Часть 4a — служба и HTTP

### Task 5: Настройки, пул, приложение, ошибки, защита

**Files:** `pyproject.toml`, `amemo/settings.py`, `amemo/private.py`, `amemo/service/__init__.py`, `app.py`, `session.py`, `problems.py`, `tests/test_service_core.py`.

- [ ] **Зависимости:** `starlette`, `uvicorn`, `psycopg_pool`, `python-multipart`; `jsonschema` уже в dev.
- [ ] Падающие тесты (`starlette.testclient`, база `pg`):
  - **Настройки:** порядок «аргумент → окружение → `amemo.toml`»; агент по умолчанию из имени пользователя ОС.
  - **Защита:**
    - `Host: evil.example` — 421;
    - `Origin: http://evil.example` на запись — 403;
    - запись с `text/plain` — 415;
    - `/health` — `ok`.
  - **Локальная служба:**
    - `GET /session` без cookie — `model:local`;
    - cookie `amemo_session` выдают `/ui/index.html` и `GET /session` при `Sec-Fetch-Site: same-origin` или `Origin` из `AMEMO_UI_ORIGINS` (чужой `Origin` — без cookie); запрос с ней — `person:…`.
  - **Общая служба** (`AMEMO_TOKENS` во временном файле):
    - без токена — 401;
    - токен только для чтения — 403 на запись;
    - верный — `200`, агент из токена.
  - **`problem+json`:** перевод каждого исключения по таблице разд. 3.2; 500 не раскрывает подробности.
  - **`private.strip`:** закрытая и незакрытая метки, несколько меток.
- [ ] Реализация:
  - `create_app(settings)`;
  - lifespan открывает и закрывает пул;
  - промежуточный слой защиты и сессии;
  - обработчики исключений по порядку «от частного к общему».
- [ ] Focused, полный прогон, коммит.

### Task 6: Операции чтения (`amemo/api.py`) и пути чтения

**Files:** `amemo/api.py`, `amemo/service/http_v1.py`, копия контракта `amemo/service/http-v1.openapi.yaml` (+ тест совпадения с `docs/api/`), правка контракта (разд. 3.3), `tests/test_service_read.py`, `tests/contract.py` (загрузчик схем и проверка ответа).

- [ ] **Правка контракта** по таблице разд. 3.3:
  - папки;
  - `about`;
  - поля, которые могут быть `null`;
  - `changes` и `warnings` — массивы.

  Проверка — `npx @redocly/cli lint …`, если `node` есть; иначе — загрузка YAML и jsonschema-метасхема.
- [ ] Пути с тестом сверки ответа по схеме контракта:
  - `/session`;
  - `/search`, `/similar`;
  - `/folders`, `/records`;
  - `/records/{ref}`, `/history`, `/links`;
  - `/entities/{ref}/card`;
  - `/graph` (обрезка до 500 узлов, `truncated`);
  - `/changes`;
  - `/objects/{id}`, `/versions/{n}/content` (`Range`, белый список типов, `nosniff`, `attachment`), `/text`, `/sheet`;
  - `/vocab/{scheme}`;
  - `/base`;
  - `/backups`.
- [ ] **Ошибки:** 404 на неизвестную ссылку и объект.
- [ ] Focused, полный прогон, коммит.

### Task 7: Очередь, запись, папки (пути записи)

**Files:** `amemo/api.py`, `amemo/service/http_v1.py`, `tests/test_service_write.py`.

- [ ] Пути с тестом сверки:
  - **Очередь:** `/review/items`, `/review/items/{id}` (для `edit` и `imported` — текущая и предложенная ревизии), `/resolve` (409 у закрытого с `by`/`at`), `/review/enqueue`, `/review/stats`.
  - **`/submit`:**
    - агент — из сессии, поле агента в теле игнорируется;
    - 422 с `issues`, у которых есть `ref` и `path`;
    - `<private>` вырезан, предупреждение `private_removed`.
  - **Папки:** `PATCH /records/{ref}/folder`, `POST /folders` (201, 409, 422), `DELETE /folders/{path}` (409 непустая), `PATCH /folders/{path}`.
- [ ] Focused, полный прогон, коммит.

### Task 8: Подборки, `/ui`, журнал запросов

**Files:** `amemo/api.py`, `amemo/service/http_v1.py`, `amemo/service/ui.py`, `amemo/journal.py`, `tests/test_service_bundles.py`, `tests/test_service_ui.py`.

- [ ] **Подборки:**
  - `/bundles/export` — id UUIDv7, `download`; `anthology: true` без модуля — 501;
  - `/download`, `/report` (`CSP sandbox`);
  - `/inspect` — потоковая загрузка с пределом, 413, `Origin` обязателен;
  - `/import` — `dry_run` по умолчанию;
  - чужой и несуществующий id — 404;
  - срок хранения 24 часа (подменить часы).
- [ ] **`/ui`** с поддельным пакетом `amemo_web`, который подставляется в `sys.modules` и указывает на временную папку:
  - `immutable` у файлов с хэшем;
  - `no-cache` и cookie у `index.html`;
  - неизвестный путь — `index.html`;
  - `../` и симлинк наружу — 404;
  - без пакета — 404 с подсказкой.
- [ ] **Журнал** (`amemo/journal.py`): строка на явный поиск через HTTP; `AMEMO_QUERY_LOG=off` — пусто; ответы не пишутся.
- [ ] Focused, полный прогон, коммит.

### Task 9: Полнота контракта и запуск

**Files:** `tests/test_service_contract.py`, `amemo/service/__main__.py` или `amemo/cli` заготовка `serve`, README.

- [ ] **Полнота:** каждый путь и метод контракта реализован; маршруты службы вне контракта — только исключения (`openapi.json`, `/health`, `/mcp`, `/ui`).
- [ ] **Запуск:** `amemo serve` (временный вход через `python -m amemo.service`) поднимает uvicorn на `127.0.0.1:8767`. Предупреждение, если указан `--host` без токенов и без `--no-auth` (отказ) или с `--no-auth`.
- [ ] **README:** раздел «Служба».
- [ ] Ревью ветки, полный прогон, проверка на приватное, PR, автослияние; сообщить вебу (часть H может начинаться).

---

## Часть 4b — CLI и MCP

### Task 10: CLI

**Files:** `amemo/cli/__init__.py` (`main`), `amemo/cli/commands/*.py`, `pyproject.toml` (скрипт `amemo`), `tests/test_cli.py`.

- [ ] Падающие тесты (`main(argv)`, перехват stdout/stderr):
  - **Команды:** `init`, `search`, `timeline`, `get`, `card`, `submit`, `review list|claim|resolve|stats`, `folders tree|create|delete|rename|move`, `export|inspect|import`, `backup create|restore|verify`, `token create|list|revoke`, `base name`, `doctor`.
  - **Коды выхода** по таблице 5.1 на своих случаях:
    - 1 — база недоступна;
    - 2 — неверный аргумент;
    - 3 — неоднозначность;
    - 4 — нет записи;
    - 5 — отказ проверки;
    - 6 — пункт решён или папка занята.
  - **`--json`** совпадает с ответом HTTP той же операции.
  - **Агент по окружению:** `CLAUDECODE=1` — `model:claude-code`; `--agent person:x` при `CLAUDECODE=1` — код 2.
  - **`token create`:** выводит токен один раз; в файле — только хэш; права файла 0600.
- [ ] Focused, полный прогон, коммит.

### Task 11: MCP

**Files:** `pyproject.toml` (`mcp`), `amemo/service/mcp.py`, монтирование `/mcp` в `app.py`, `amemo mcp` (stdio) в CLI, `tests/test_mcp.py`.

- [ ] Падающие тесты (клиент SDK через память):
  - список инструментов по разд. 4;
  - **поиск в три шага:** `amemo_search` → `amemo_timeline` → `amemo_get`;
  - `amemo_helpful` с `retrieval_id` той же сессии проходит, а из другой сессии — ошибка;
  - **`amemo_submit`:** агент `model:` (из `--agent` или `X-Amemo-Agent`); `person:` в заголовке отвергается;
  - `amemo_move`;
  - `amemo_review_claim` → `release` → `resolve` для `semantic`;
  - **неоднозначность:** `ambiguous: true` и кандидаты;
  - `/mcp` через testclient: `Host`/`Origin` защищены, сессия получает свою задачу.
- [ ] Реализация:
  - инструменты зовут `amemo/api.py` через `anyio.to_thread`;
  - stdio-сервер держит маленький пул с переподключением;
  - менеджер сессий `/mcp` — в lifespan службы.
- [ ] Focused, полный прогон, коммит.

### Task 12: Завершение части 4b

- [x] **README:** разделы «CLI» и «MCP».
- [x] **Журнал запросов:** проверить, что строки пишут явные поиски CLI и MCP.
- [ ] Ревью ветки, полный прогон, проверка на приватное, PR, автослияние.

---

## Часть 4c — память агентов

### Task 13: Хуки Claude Code

**Files:** `amemo/agents/hooks.py`, `amemo hook` в CLI, `tests/test_hooks.py`.

- [x] Падающие тесты (образцы JSON событий):
  - **`SessionStart`:**
    - `cwd` с git-корнем `alpha` и сущностью-проектом `ent:alpha` — `additionalContext` с 3–5 атомами и строками-напоминаниями;
    - проекта нет — только напоминание.
  - **`UserPromptSubmit`:**
    - запрос с маркой — список с id;
    - без уверенных находок — пустой ответ;
    - `<private>` вырезан до поиска.
  - **Без записи:** в `retrieval` и в журнал ничего не пишется.
  - **Бюджет и сбои:**
    - «зависшая» база (`pg_sleep` через подмену запроса или `statement_timeout`) — пустой ответ за ≤ 1,5 с, код 0;
    - нет `AMEMO_DSN` — пустой ответ, код 0, строка в `hooks.log`.
- [x] Реализация по протоколу хуков Claude Code: вход — stdin JSON, выход — `hookSpecificOutput.additionalContext`. Формат сверен по документации (context7 и code.claude.com/docs/en/hooks) — спецификация, разд. 6.1; `PreCompact` принят (stdout идёт в указания к сжатию).
- [x] Focused, полный прогон, коммит.

### Task 14: Установщик и навыки

**Files:** `amemo/agents/platforms.py`, `amemo/agents/install.py`, `amemo install|uninstall` в CLI, `amemo/packs/core/skills/amemo-remember/SKILL.md`, `amemo-answer/SKILL.md`, `amemo-verify/SKILL.md`, `pyproject.toml` (`package-data` навыков), `tests/test_install.py`.

- [ ] Форматы конфигов Claude Code и Codex CLI (MCP, хуки, навыки, `AGENTS.md`, `--project`) проверить по документации (context7) и записать в модуль с версией формата.
- [ ] Падающие тесты на временном `HOME` и проекте:
  - **Claude Code, глобально:**
    - есть заглушка `claude` в `PATH` — вызывается `claude mcp add …`;
    - без неё — правка `~/.claude.json` с предупреждением;
    - хуки в `~/.claude/settings.json`;
    - навыки в `~/.claude/skills/`.
  - **Claude Code, `--project`:** `.mcp.json`, `.claude/settings.json`, `.claude/skills/`.
  - **Codex, глобально:** блок `# amemo:begin…end` в `config.toml`, блок в `AGENTS.md`.
  - **Codex, `--project`:** по документации или с предупреждением.
  - **Чужие ключи** и чужие хуки на месте; резервная копия `.amemo-backup`.
  - **Повтор и предпросмотр:** повторная установка ничего не меняет; `--dry-run` ничего не пишет.
  - **`uninstall`:** разобранное содержимое (JSON и TOML) и текст Markdown равны исходным.
- [ ] **Навыки:** тексты на русском и английском (одна страница каждый), без сведений о конкретных компаниях.
- [ ] Focused, полный прогон, коммит.

### Task 15: compose, `doctor`, документация, завершение

**Files:** `Dockerfile`, `docker-compose.yml` (служба `amemo`, профиль `web`), `amemo doctor`, README и README.ru (установка одной командой, агенты, хуки, навыки, расписание `amemo-verify`), `.github/workflows/ci.yml` (шаг «одной командой»: `amemo init`, `amemo install claude-code --project tmp`, `amemo doctor`).

- [x] `amemo doctor`: проверка базы, хранилища, модели, установленных агентов; коды выхода.
- [x] Шаг CI и тест `doctor`.
- [ ] Ревью всей части, полный прогон, проверка на приватное, PR, автослияние; сообщить вебу.

---

## Критерии готовности

- Все тесты зелёные на PostgreSQL 18 и 16; CI зелёный у каждого PR.
- Каждая строка приёмки спецификации (разд. 9) связана с тестом.
- Ревью каждой задачи и каждой части пройдены; Critical и Important исправлены.
- Публичный репозиторий не получил ничего приватного.
