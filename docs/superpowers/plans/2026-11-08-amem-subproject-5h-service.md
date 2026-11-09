# amem — подпроект 5, часть H «Связь со службой»: план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** веб-UI работает с настоящей службой amem. `pip install "amem[web]"` и `amem serve` поднимают `/ui`, и всё, что части A–G показывали на моках, работает на локальной базе. Контракт проверяется с обеих сторон.

**Спецификация:** `docs/superpowers/specs/2026-11-06-amem-subproject-5-web-ui-design.md`, разд. 6, 7.5, 10 (часть H), 13. Служба — `docs/superpowers/specs/2026-11-07-amem-subproject-4-service-design.md`.

**Начинать после слияния части 4a** (ветка `subproject-4a-service`). План написан по её состоянию на 08.11 (коммит `f950ecf`), и в 4a уже сделано:

| Пункт исходного плана | Где сделано в 4a |
|---|---|
| H1 — `/ui` из `amem_web` | `amem/service/ui.py`: файлы с хэшем `immutable`; `index.html` `no-cache` с cookie сессии; SPA; обходы путей → 404 |
| H2 — ответы службы по схемам контракта | тесты службы: `contract.check` у каждого ответа |

За частью H остаются:
- веб-сторона контракта;
- строгая CSP;
- e2e против службы;
- поставка `amem[web]`;
- настоящие снимки в README.

**Ход.** 09.11 — до слияния 4a сделано то, что от неё не зависит: Task 2, Task 3, Task 4 без cookie сессии (PR `subproject-5h-prep`).

**Ветка:** `subproject-5h-service` от `main` после 4a. Worktree: `~/projects/amem-web-h`.

---

### Task 0: Исходная точка
- [x] 4a слита. Worktree, `npm ci`; `.venv` с `pip install -e ".[dev,web]"`. Тесты библиотеки, службы и веба зелёные.
- [x] `npm run api:check` — убедиться, что `schema.d.ts` совпадает с контрактом из `main`. Если служба меняла контракт после 08.11, сначала `npm run api:types`.

### Task 1: Контракт со стороны веба
**Files:** `web/src/api/schema.d.ts` (генерируется), `web/src/api/folders.ts`, `web/src/features/write/useSubmit.ts`, `web/src/features/write/proposal.ts`, `web/src/api/errors.ts`, `web/src/features/review/useDecision.ts`.

В 4a контракт получил:
- `POST /folders`, `DELETE` и `PATCH /folders/{path}` → `FolderRenamed`;
- схемы `Proposal` и `LinkProposal` у `/submit`;
- у `resolve` — `partial`, `uncertain` и `confidence`;
- у `Problem` — `changeset_id` и `warnings` для `check_rejected`;
- ответ 413 у `/submit` и `/bundles/inspect`.

- [x] `npm run api:types`; исправить ошибки типов.
- [x] `api/folders.ts`: прямой `fetch` → типизированный клиент `openapi-fetch` (`createFolder`, `deleteFolder`, `renameFolder`).
  - Путь папки — одним сегментом через `encodeURIComponent` (параметр `FolderPath`).
  - Тест на папку с `/` и пробелом в имени.
- [x] `/submit`: тело собирается по `Proposal` и `LinkProposal` без `as`; поле агента не отправляется (служба берёт агента из сессии).
  - Итог: агент не отправляется; `scope.folder` из тела убран (поля нет в схеме v1 — служба отклоняла), пояснение «простыми словами» подставляется перед каждой отправкой (`withSummary`).
- [x] `resolve`: человек отправляет только `confirmed` или `refuted` — как сейчас. Тип `outcome` сузить в `useDecision`, чтобы `partial` не появился в UI случайно.
- [x] Ошибки `problem+json`:
  - `check_rejected` — показывать все `issues` и `warnings` у полей;
  - 413 — «Файл больше допустимого» или «Запись слишком большая (предел 1 МиБ)» словами в области;
  - `<private>` вырезан — предупреждение `private_removed` тостом.

### Task 2: Моки по контракту во время выполнения
**Files:** `web/src/mocks/contract.ts`, `web/src/test/setup.ts`, `web/package.json`.

Сейчас моки сверяются с контрактом только типами; JSON-образцы и ответы обработчиков во время выполнения не проверяются.
- [x] `contract.ts`: из `../docs/api/http-v1.openapi.yaml` собрать валидаторы ответов по `operationId` и коду (Ajv 2020; `yaml` уже есть или добавить в dev).
- [x] В Vitest — слушатель MSW `response:mocked`: каждый ответ мока сверяется со схемой; расхождение валит тест с путём поля.
- [x] Если найдутся расхождения, правятся моки, а не контракт. Контракт меняется только вместе со службой.
  - Итог 09.11: расхождений нет. Вне контракта `main` только пути папок 4a — временное исключение `AWAITING_4A` в `src/mocks/contract.ts`; убрать в Task 1.

### Task 3: Строгая CSP
**Files:** `web/index.html`, `web/public/theme-boot.js`, `web/src/features/source/PdfPage.tsx`, `web/vite.config.ts`.

Служба отдаёт `/ui` с CSP:

```
default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:;
font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'
```

- [x] Встроенный скрипт темы в `index.html` будет заблокирован, и страница мигнёт чужой темой.
  - Вынесен в `public/boot.js`: обычный `<script src>` без `async`/`defer`, до стилей.
  - Проверяет e2e-проект `csp`.
  - Там же найдено и исправлено: zod 4 при первом разборе проверяет, разрешён ли `Function`, и сама проверка нарушает CSP. `boot.js` до модулей ставит `globalThis.__zod_globalConfig.jitless`; `z.config` в коде приложения не успевает — общий кусок `schemas` разбирает раньше.
- [x] pdf.js:
  - в pdf.js 6 генерации кода нет вовсе (и опции `isEvalSupported` тоже), исключение не нужно;
  - воркер — файл с того же источника (`script-src 'self'` его разрешает);
  - сканы с JPX требуют WebAssembly (`'wasm-unsafe-eval'`). Проверить на образце-скане; если нужно — договориться со службой о добавлении в CSP. Иначе честная строка «Страница не отрисована: формат изображения не поддержан», цитата текстом.
- [x] KaTeX (шрифты `font-src 'self' data:`), CodeMirror (стили — `'unsafe-inline'` разрешён), force-graph и three.js — проверить в e2e по журналу консоли: ни одного нарушения CSP.
- [x] `vite preview` отдаёт те же заголовки CSP, чтобы нарушения ловились раньше.
  - В `vite dev` CSP нет: горячая замена модулей вставляет встроенные скрипты.
  - Проект e2e `csp` собирает `build:mock` и проверяет сборку под CSP службы.
  - `build:mock` раньше собирался без моков (их отключало условие `DEV`); исправлено.

### Task 4: Разработка против службы
**Files:** `web/vite.config.ts`, `web/README.md`.
- [x] Прокси `/api` по умолчанию на `http://127.0.0.1:8767`. Сейчас стоит 8765 — порт старого контейнера v0. `AMEM_URL` по-прежнему переопределяет.
- [x] Cookie сессии: служба ставит её при выдаче `index.html` (`session.grant`). Через прокси Vite её нет, поэтому `npm run dev` перед стартом берёт сессию у службы запросом `GET /ui/`. Сверить с 4a, какое имя cookie и путь; если нужно — маленький плагин Vite.
  - Итог: плагин не нужен. Сессию служба выдаёт на `GET /api/v1/session` с `Sec-Fetch-Site: same-origin` (через прокси так и есть), записи пропускает с `AMEM_UI_ORIGINS=http://127.0.0.1:5173`. Подменять `Origin` в прокси нельзя — чужая страница писала бы через dev-сервер. Описано в `web/README.md`.
- [x] `web/README.md`: три режима — `dev:mock`, `dev` против `amem serve`, сборка в `amem_web`.

### Task 5: e2e против настоящей службы
**Files:** `docker-compose.yml` (профиль `web`), `web/e2e/service/*.spec.ts`, `web/playwright.service.config.ts`, `tools/seed_sample.py`, `.github/workflows/web.yml`.
- [x] **Образец базы.** `tools/seed_sample.py` заводит базу-метеостанцию тем же содержимым, что фикстуры моков:
  - Итог: 20 записей, папки, PDF и xlsx, два открытых пункта; фикстуры моков с ним не сверяются тестом — общая часть (виды, подписи словаря) взята из ядра.
  - папки PARA, сущности, записи всех трёх семей, образец PDF в хранилище, очередь с пунктами всех причин;
  - запись через `amem` API, а не через SQL — так проходят автопроверки.

  Одни данные для моков и для службы: фикстуры JSON генерируются из того же описания (`web/tools/make-*-fixtures.py` переходят на общий источник) или сверяются с ним тестом.
- [x] **Compose, профиль `web`:** PostgreSQL 18, `amem serve` с собранным `amem_web`, образец базы при старте.
  - Итог: вместо compose — `playwright.service.config.ts` сам пишет образец и поднимает `python -m amem.service`; в CI — сервис PostgreSQL 18.
- [x] **Сценарии** (`@service`, отдельный конфиг Playwright, `baseURL` службы):
  1. главная — небо со звёздами, поиск находит запись;
  2. запись — свойства и цитата подсвечена на странице PDF;
  3. быстрая запись по `N` → звезда вспыхнула → «Отменить» → записи нет; повтор без отмены → запись в «Изменениях»;
  4. проверка: `J`, `Y`, тост, после окна отмены пункт решён в службе; второй раз — «Уже решено»;
  5. папки: создать, перетащить запись, переименовать, удалить пустую;
  6. подборка: антология → zip и отчёт открываются; пробный импорт показывает отчёт;
  7. консоль без ошибок и без нарушений CSP на всех шагах; axe на главной, записи, проверке.
- [x] **CI:** задача `web-service` в `web.yml` (сервис PostgreSQL 18, `pip install -e ".[web]"`, сборка, seed, Playwright). Обязательной для `main` её сделать после двух зелёных прогонов.
  - Сделать задачу обязательной для `main` — после двух зелёных прогонов (настройка правил ветки — за владельцем).

### Task 6: Поставка `amem[web]`
**Files:** `web/python/pyproject.toml`, `pyproject.toml`, `.github/workflows/web.yml`.
- [x] Колесо `amem-web` собирается из `web/python` со статикой `dist` внутри; версия совпадает с `amem`.
- [x] Проверка в CI на чистом окружении: `pip install ./dist/amem-*.whl ./web/python/dist/amem_web-*.whl`, `amem serve` → `GET /ui/` 200 с CSP, `GET /ui/assets/<хэш>.js` — `immutable`, `GET /ui/records` → `index.html`.
  - `tools/check_ui_wheel.py` — и локально, и в CI.
- [x] Без `amem[web]` — 404 с подсказкой «pip install "amem[web]"» (это делает 4a; проверить текст).
  - Проверяется тестами службы 4a (`test_without_package_404_with_hint`).

### Task 7: Настоящие снимки в README
**Files:** `docs/assets/readme/*`, `tools/readme_assets.py`, `README.md`, `README.ru.md`.
- [x] Заглушки снимков заменить снимками веб-UI на службе с образцом базы: небо, запись с источником, проверка — в светлой и тёмной теме, en и ru.
  - Итог: небо, запись, проверка — со службы; карточка остаётся заглушкой до пакета области с профилем в образце, агент — до 4b.
- [x] `tools/readme_assets.py` снимает их через Playwright из compose-профиля `web`, а не рисует заглушки.
  - Итог: снимает `web/tools/readme-shots.mjs`; `readme_assets.py` рисует только оставшиеся заглушки.
- [x] В README снять пометку «на моках»: быстрый старт ведёт на `amem serve` и `/ui`.
  - `amem serve` ещё нет (4b) — быстрый старт ведёт на `python -m amem.service` и образец.

### Task 8: Проверки и PR
- [x] lint, `api:check`, typecheck, vitest, build, chunks, size, e2e на моках и e2e против службы.
- [x] Тесты библиотеки и службы на PostgreSQL 18 и 16.
- [x] Проверка на приватное по дереву и снимкам.
- [x] PR с автослиянием; память.

## Что нашла связь со службой

Расхождения, которых моки не показывали; каждое исправлено, мок теперь ведёт себя как служба:

1. Пояснение «простыми словами» ядро требует у каждого атома (шаблон `has_label`) — быстрая запись и значение из карточки отклонялись.
2. `scope.folder` в теле — не по схеме v1; папку задаёт перенос (`PATCH /records/{ref}/folder`).
3. `/review/items` без `state` отдаёт пункты в любом состоянии — открытые просим как `queued` и `claimed`.
4. Антология с `with_packs` — 400; флажок пакетов при антологии недоступен.
5. Карточка без профиля — 200 с пустыми `fields` и значениями в `extra` (а не 404); показываем «Значения вне профиля».
6. `details` пункта очереди в форме ядра: коды замечаний и риска строками, кандидаты отдельно — показываем словами и ссылками.
7. Подписи словаря ядра строчные — с заглавной при показе; подписи моков взяты из ядра.
8. Ядро: кандидат из той же пачки в пункте очереди оставался `@именем` — теперь ссылка на запись (`check._details`, тест в `tests/test_check_submit.py`).

Служба ещё не отдаёт `/templates` (часть 4d) — интерфейс живёт без шаблонов, e2e против службы допускает эту 404.

## Риски

| Риск | Что делаем |
|---|---|
| Контракт поменяется в 4b–4d | Task 2 ловит расхождение моков, тесты службы — расхождение службы; меняется только `http-v1.openapi.yaml` |
| WebAssembly для сканов под строгой CSP | Task 3: проверка на образце; либо `'wasm-unsafe-eval'` по согласованию со службой, либо честная строка |
| Образцы для моков и службы разойдутся | Один источник данных (Task 5) и тест сверки |
| e2e против службы медленные или нестабильные | Отдельный конфиг и задача CI; моки остаются основной проверкой интерфейса |

## Самопроверка по спецификации

- Разд. 10, часть H:
  - e2e против службы в compose — Task 5;
  - `/ui` из `amem[web]` — 4a и Task 6;
  - контракт с обеих сторон — Task 1, 2 и тесты службы 4a.
- Разд. 7.5 (поставка) — Task 6.
- Разд. 13 (связь с подпроектом 4): `problem+json`, агент из сессии, `/ui` — Task 1, 3, 4.
