# amem — подпроект 5 «Веб-интерфейс»: план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Собрать основу веб-интерфейса amem (часть A): контракт HTTP v1, проект `web/` на React 19 + HeroUI v3 + TanStack, оболочку с папками, темой и переводом, моки контракта, первые два экрана (список записей и результаты поиска), дистрибутив `amem-web` и CI. Части B–H описаны задачами; каждая получит свой подробный план перед началом.

**Architecture:** Веб-UI — статика за службой amem (`/ui`), собранная как оболочка с реестром виджетов и плагинов на одной базе дизайна (спецификация `docs/superpowers/specs/2026-11-06-amem-subproject-5-web-ui-design.md`, редакция 2, разд. 7.2). Данные — только через контракт `docs/api/http-v1.openapi.yaml`; до готовности службы (подпроект 4) всё работает на моках MSW того же контракта. Экраны — раскладки из слотов, в слоты ставятся виджеты; ядро amem — первый плагин оболочки.

**Tech Stack:** Node 24, Vite 8, TypeScript 5.9 (`openapi-typescript` 7 требует TS 5.x), React 19.3, `@heroui/react` + `@heroui/styles` 3.2 (Tailwind CSS 4.3, React Aria Components), `@tanstack/react-router` 1.17x (файловые маршруты), `@tanstack/react-query` 5, `openapi-typescript` + `openapi-fetch`, zod 4, i18next + react-i18next, MSW 3 (плагин `msw/vite`), Biome 2, Vitest 5 + Testing Library, Playwright 1.65 + `@axe-core/playwright`, `size-limit` 14; Python-дистрибутив `amem-web` (hatchling).

---

## Карта файлов части A

| Файл | За что отвечает |
|---|---|
| `docs/api/http-v1.openapi.yaml` | Контракт службы для UI (разд. 6 спецификации) — единственный источник типов и моков |
| `web/package.json`, `web/vite.config.ts`, `web/tsconfig.json`, `web/biome.json`, `web/index.html` | Проект, сборка с `base: "/ui/"`, проверки |
| `web/src/styles/theme.css` | Токены (разд. 4.2) поверх переменных HeroUI, светлая и тёмная темы |
| `web/src/styles/app.css` | Штамп Hallmark, импорты Tailwind и HeroUI, базовые правила (`overflow: clip`, фокус) |
| `web/src/api/schema.d.ts` (генерируется), `client.ts`, `errors.ts`, `queries/*.ts` | Типизированный клиент контракта, `ApiError` из `problem+json`, фабрики запросов |
| `web/src/app/plugin.ts`, `registry.ts`, `core-plugin.ts` | Интерфейсы `Plugin`, `Widget`, `Command`, `DataSource`; реестр; ядро amem как первый плагин |
| `web/src/app/theme.ts`, `i18n.ts`, `providers.tsx` | Тема (система / светлая / тёмная), язык ru/en, провайдеры Query и React Aria |
| `web/src/app/shell/TopBar.tsx`, `Folders.tsx`, `AppMenu.tsx`, `Layout.tsx` | Верхняя строка, панель папок, меню, раскладка со слотами без прокрутки страницы |
| `web/src/ui/RegionState.tsx`, `StatusText.tsx`, `KindChip.tsx`, `MetaList.tsx`, `RelativeTime.tsx`, `Highlight.tsx` | Примитивы базы дизайна |
| `web/src/routes/*.tsx`, `routeTree.gen.ts` | Маршруты: оболочка, список записей, результаты поиска, настройки, заглушки остальных |
| `web/src/features/records/RecordList.tsx`, `features/search/SearchResults.tsx` | Первые два экрана на моках |
| `web/src/i18n/ru.json`, `en.json` | Каталоги перевода с одинаковыми ключами |
| `web/src/mocks/fixtures/*.json`, `handlers.ts`, `node.ts` | Нейтральные образцы (метеостанция МС-1) и обработчики контракта |
| `web/e2e/*.spec.ts`, `web/playwright.config.ts` | e2e на моках, axe |
| `web/python/pyproject.toml`, `web/python/amem_web/__init__.py` | Дистрибутив `amem-web`: статика и `static_dir()` |
| `.github/workflows/web.yml` | CI веб-части, отдельно от `ci.yml` ядра |
| `web/.impeccable/surfaces/*.md` | Бриф поверхности с контрактом направления (разд. 4.1) |

Каждая папка `features/*` — одна задача человека; фичи общаются через маршруты и `ui/`. Компоненты HeroUI оборачиваются только там, где обёртка добавляет поведение amem.

---

## Часть A — основа (ветка `subproject-5a-web-foundation`)

### Task 0: Исходная точка

**Files:** нет изменений кода.

- [ ] **Step 1: Ветка от свежего `main`**

```bash
cd ~/projects/amem && git fetch origin && git worktree add ../amem-web-a -b subproject-5a-web-foundation origin/main
cd ../amem-web-a && git log --oneline -1
```
Expected: последний коммит `main` (слияние PR с этой спецификацией и планом).

- [ ] **Step 2: Инструменты**

```bash
node --version && npm --version && python3 --version
```
Expected: Node 24.x, npm 11.x, Python 3.12+. Если Node младше 24 — поставить через `nvm install 24`.

- [ ] **Step 3: Проверить, что ядро зелёное (ничего в нём не трогаем)**

```bash
pip install -e ".[dev]" -q && pytest -q -p no:cacheprovider -x 2>&1 | tail -3
```
Expected: `passed`, без `failed`. Тестовые базы — по памяти `amem-test-db-ports` (5446/5447 локально).

### Task 1: Контракт HTTP v1

**Files:**
- Create: `docs/api/http-v1.openapi.yaml`
- Create: `docs/api/README.md`
- Test: `web/tests/contract.test.ts` (появится в Task 7; здесь — проверка линтером)

- [ ] **Step 1: Написать контракт по таблице разд. 6 спецификации**

Скелет (дописать все пути таблицы; схемы ответов повторяют то, что отдаёт библиотека: `recipes.exact_fact`, `amem.card/1`, `Submitted`, пункты `review.items`, `Imported`):

```yaml
openapi: 3.1.0
info:
  title: amem HTTP API for the web UI
  version: 1.0.0
  description: >-
    Контракт v1 между службой amem (подпроект 4) и веб-интерфейсом (подпроект 5).
    Изменения — только правкой этого файла в PR, который проходит обе стороны.
servers:
  - url: /api/v1
paths:
  /session:
    get:
      operationId: getSession
      summary: Кто вошёл и что умеет служба
      responses:
        "200":
          content:
            application/json:
              schema: { $ref: "#/components/schemas/Session" }
        "401": { $ref: "#/components/responses/Problem" }
  /search:
    get:
      operationId: search
      parameters:
        - { name: q, in: query, required: true, schema: { type: string } }
        - { name: kind, in: query, schema: { type: array, items: { type: string } }, style: form, explode: true }
        - { name: status, in: query, schema: { type: array, items: { type: string } }, style: form, explode: true }
        - { name: entity_class, in: query, schema: { type: array, items: { type: string } }, style: form, explode: true }
        - { name: target, in: query, schema: { type: string, enum: [atom, entity] } }
        - { name: limit, in: query, schema: { type: integer, minimum: 1, maximum: 100, default: 10 } }
      responses:
        "200":
          content:
            application/json:
              schema: { $ref: "#/components/schemas/SearchResult" }
  /records:
    get:
      operationId: listRecords
      summary: Список записей для панели папок и «Все записи»
      parameters:
        - { name: folder, in: query, schema: { type: string }, description: "scope.folder; пусто — все" }
        - { name: kind, in: query, schema: { type: array, items: { type: string } }, style: form, explode: true }
        - { name: status, in: query, schema: { type: array, items: { type: string } }, style: form, explode: true }
        - { name: limit, in: query, schema: { type: integer, minimum: 1, maximum: 200, default: 50 } }
        - { name: cursor, in: query, schema: { type: string } }
      responses:
        "200":
          content:
            application/json:
              schema: { $ref: "#/components/schemas/RecordList" }
  /folders:
    get:
      operationId: getFolders
      summary: Дерево папок (scope.folder) со счётчиками
      responses:
        "200":
          content:
            application/json:
              schema: { $ref: "#/components/schemas/FolderTree" }
  /records/{ref}:
    get:
      operationId: getRecord
      parameters: [{ name: ref, in: path, required: true, schema: { type: string, pattern: "^(atm|ent):.+" } }]
      responses:
        "200": { content: { application/json: { schema: { $ref: "#/components/schemas/RecordView" } } } }
        "404": { $ref: "#/components/responses/Problem" }
  # ... /records/{ref}/history, /records/{ref}/links, /entities/{ref}/card, /graph, /changes,
  # /objects/{id}, /objects/{id}/versions/{n}/content, /objects/{id}/versions/{n}/text,
  # /review/items, /review/items/{id}, /review/items/{id}/resolve, /review/enqueue, /review/stats,
  # /submit, /vocab/{scheme}, /base, /backups, /bundles/export, /bundles/{id}/download,
  # /bundles/{id}/report, /bundles/inspect, /bundles/import — по таблице разд. 6
components:
  responses:
    Problem:
      description: Ошибка в формате RFC 9457
      content:
        application/problem+json:
          schema: { $ref: "#/components/schemas/Problem" }
  schemas:
    Problem:
      type: object
      required: [type, title, status]
      properties:
        type: { type: string }
        title: { type: string }
        status: { type: integer }
        detail: { type: string }
        code: { type: string }
        issues: { type: array, items: { $ref: "#/components/schemas/CheckIssue" } }
    CheckIssue:
      type: object
      required: [code, severity, message]
      properties:
        code: { type: string }
        severity: { type: string, enum: [violation, warning, info] }
        message: { type: string }
        path: { type: string }
        ref: { type: string }
    Session:
      type: object
      required: [agent, base, amem_version, semantic, can_write]
      properties:
        agent: { type: string, pattern: "^(person|model):.+" }
        base: { type: string, format: uuid }
        amem_version: { type: string }
        semantic: { type: string, enum: [used, unavailable] }
        can_write: { type: boolean }
    Status:
      type: string
      enum: [draft, needs_review, auto_verified, verified, rejected, deprecated, superseded]
    SearchHit:
      type: object
      required: [ref, revision, label, snippet, status, review_state, score, matches]
      properties:
        ref: { type: string }
        revision: { type: integer }
        label: { type: string, nullable: true }
        snippet: { type: string }
        status: { $ref: "#/components/schemas/Status" }
        review_state: { type: string, enum: [none, pending, accepted, declined] }
        kind: { type: string }
        entity_class: { type: string }
        about: { type: array, items: { $ref: "#/components/schemas/RefLabel" } }
        score: { type: number }
        matches: { type: array, items: { type: object, properties: { channel: { type: string }, rank: { type: integer } } } }
    SearchResult:
      type: object
      required: [recipe, semantic, candidate_count, items, retrieval_id]
      properties:
        recipe: { type: string }
        semantic: { type: string, enum: [used, unavailable] }
        channels: { type: object }
        candidate_count: { type: integer }
        items: { type: array, items: { $ref: "#/components/schemas/SearchHit" } }
        retrieval_id: { type: string, nullable: true }
    RefLabel:
      type: object
      required: [ref, label]
      properties: { ref: { type: string }, label: { type: string }, kind: { type: string }, entity_class: { type: string } }
    RecordSummary:
      type: object
      required: [ref, label, kind_or_class, status, recorded_at, agent]
      properties:
        ref: { type: string }
        label: { type: string }
        kind_or_class: { type: string }
        target: { type: string, enum: [atom, entity] }
        status: { $ref: "#/components/schemas/Status" }
        folder: { type: string, nullable: true }
        about: { type: array, items: { $ref: "#/components/schemas/RefLabel" } }
        recorded_at: { type: string, format: date-time }
        agent: { type: string }
    RecordList:
      type: object
      required: [items]
      properties:
        items: { type: array, items: { $ref: "#/components/schemas/RecordSummary" } }
        next_cursor: { type: string, nullable: true }
        total: { type: integer }
    Folder:
      type: object
      required: [path, name, count, children]
      properties:
        path: { type: string }
        name: { type: string }
        count: { type: integer }
        children: { type: array, items: { $ref: "#/components/schemas/Folder" } }
    FolderTree:
      type: object
      required: [folders, unfiled]
      properties:
        folders: { type: array, items: { $ref: "#/components/schemas/Folder" } }
        unfiled: { type: integer }
    RecordView:
      type: object
      description: Запись с текущей ревизией, источниками, открытыми пунктами и полезностью (lookup.get + revisions_sources + review.items)
      required: [ref, target, revision, payload, status, review_state, recorded_at, agent, sources, open_items]
      properties:
        ref: { type: string }
        target: { type: string, enum: [atom, entity] }
        revision: { type: integer }
        payload: { type: object, description: "тело amem.atom/1 или сущности как есть" }
        status: { $ref: "#/components/schemas/Status" }
        review_state: { type: string }
        recorded_at: { type: string, format: date-time }
        agent: { type: string }
        folder: { type: string, nullable: true }
        sources: { type: array, items: { $ref: "#/components/schemas/SourceView" } }
        open_items: { type: array, items: { $ref: "#/components/schemas/ReviewItem" } }
        usefulness: { type: number, nullable: true }
    SourceView:
      type: object
      required: [object, object_version, verdict]
      properties:
        object: { type: string }
        object_name: { type: string }
        object_kind: { type: string, enum: [file, web, message] }
        media_type: { type: string }
        object_version: { type: integer }
        selectors: { type: array, items: { type: object } }
        quote: { type: string }
        role: { type: string, enum: [primary, secondary, derived] }
        verdict: { type: string, enum: [ok, moved, fuzzy, by_locator, unresolved, not_found, no_file, no_text, external, error] }
    ReviewItem:
      type: object
      required: [id, ref, reason, state, created_at]
      properties:
        id: { type: string, format: uuid }
        ref: { type: string }
        label: { type: string }
        kind_or_class: { type: string }
        reason: { type: string, enum: [semantic, warning, high_risk, semantic_doubt, edit, source_changed, audit, calibration, imported] }
        state: { type: string, enum: [queued, claimed, done, obsolete] }
        details: { type: object }
        created_at: { type: string, format: date-time }
        created_by: { type: string }
        author: { type: string, nullable: true }
    VocabEntry:
      type: object
      required: [code, label]
      properties:
        code: { type: string }
        label: { type: object, properties: { ru: { type: string }, en: { type: string } } }
        pack: { type: string }
        broader: { type: string, nullable: true }
```

Для остальных путей — схемы `Card` (`amem.card/1`), `GraphResult` (`nodes` с `ref`, `label`, `kind_or_class`, `status`, `family`; `edges` с `src`, `dst`, `rel`), `ChangesResult` (события `what_changed` + `label` записи), `ReviewItemView` (пункт + запись + для `edit` две ревизии + для `source_changed` две версии), `ResolveRequest` (`outcome`, `note`), `EnqueueRequest`, `ReviewStats`, `SubmitRequest`/`Submitted`, `Base`, `Backup`, `BundleExportRequest`/`BundleExport`, `BundleInspect`, `BundleImportRequest`/`Imported`. Поля и имена — как в `amem/schema/amem_v1.yaml` и докстрингах библиотеки (`amem/recipes.py`, `amem/review.py`, `amem/profile.py`, `amem/bundle.py`).

- [ ] **Step 2: Прогнать линтер контракта**

```bash
npx --yes @redocly/cli@latest lint docs/api/http-v1.openapi.yaml
```
Expected: `No problems were found` (предупреждения о `nullable` в 3.1 исправить на `type: [string, "null"]`).

- [ ] **Step 3: README контракта**

`docs/api/README.md`: что это, кто реализует (подпроект 4), кто потребляет (веб-UI), как менять (правка файла в PR; UI — `npm run api:check`, служба — тест сверки ответов), формат ошибок `problem+json`, правило «агент записи — из сессии».

- [ ] **Step 4: Commit**

```bash
git add docs/api && git commit -m "web: контракт HTTP v1 для веб-интерфейса (OpenAPI 3.1), README контракта"
```

### Task 2: Проект `web/`

**Files:**
- Create: `web/package.json`, `web/vite.config.ts`, `web/tsconfig.json`, `web/tsconfig.node.json`, `web/biome.json`, `web/index.html`, `web/.gitignore`, `web/src/main.tsx`, `web/src/vite-env.d.ts`, `web/src/styles/app.css`, `web/src/styles/theme.css`, `web/.size-limit.json`
- Modify: `.gitignore` (корень) — добавить `web/node_modules/`, `web/python/amem_web/dist/`, `web/test-results/`, `web/playwright-report/`, `.hallmark/`

- [ ] **Step 1: `package.json`**

```json
{
  "name": "amem-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "engines": { "node": ">=24" },
  "scripts": {
    "dev": "vite",
    "dev:mock": "VITE_MOCK=1 vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "typecheck": "tsc -b --noEmit",
    "lint": "biome check .",
    "format": "biome format --write .",
    "test": "vitest run",
    "test:watch": "vitest",
    "e2e": "playwright test",
    "api:types": "openapi-typescript ../docs/api/http-v1.openapi.yaml -o src/api/schema.d.ts",
    "api:check": "openapi-typescript ../docs/api/http-v1.openapi.yaml -o src/api/schema.d.ts --check",
    "size": "size-limit"
  },
  "dependencies": {
    "@heroui/react": "^3.2.7",
    "@heroui/styles": "^3.2.7",
    "@tanstack/react-query": "^5.106.1",
    "@tanstack/react-router": "^1.170.46",
    "i18next": "^26.7.2",
    "openapi-fetch": "^0.17.0",
    "react": "^19.3.1",
    "react-aria-components": "^1.15.0",
    "react-dom": "^19.3.1",
    "react-i18next": "^17.1.13",
    "tailwind-variants": "^3.0.0",
    "zod": "^4.6.7"
  },
  "devDependencies": {
    "@axe-core/playwright": "^4.14.0",
    "@biomejs/biome": "^2.6.6",
    "@playwright/test": "^1.65.0",
    "@size-limit/file": "^14.3.0",
    "@tailwindcss/vite": "^4.3.4",
    "@tanstack/router-plugin": "^1.168.48",
    "@testing-library/jest-dom": "^6.6.0",
    "@testing-library/react": "^16.3.3",
    "@testing-library/user-event": "^14.6.0",
    "@types/react": "^19.3.0",
    "@types/react-dom": "^19.3.0",
    "@vitejs/plugin-react": "^6.2.1",
    "ajv": "^8.20.0",
    "ajv-formats": "^3.0.1",
    "jsdom": "^31.0.0",
    "msw": "^3.0.4",
    "openapi-typescript": "^7.13.0",
    "size-limit": "^14.3.0",
    "tailwindcss": "^4.3.4",
    "typescript": "~5.9.3",
    "vite": "^8.3.6",
    "vitest": "^5.1.0",
    "yaml": "^2.8.0"
  }
}
```
Версии — не ниже указанных; при `npm install` взять последние стабильные тех же мажорных веток и закрепить `package-lock.json`. Версию `react-aria-components` взять ту, что требует `@heroui/react` (см. его `peerDependencies`).

- [ ] **Step 2: `vite.config.ts`**

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import { msw } from "msw/vite";

export default defineConfig({
  base: "/ui/",
  plugins: [
    tanstackRouter({ target: "react", autoCodeSplitting: true }),
    react(),
    tailwindcss(),
    msw(),
  ],
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8765", changeOrigin: true } },
  },
  build: {
    outDir: "python/amem_web/dist",
    emptyOutDir: true,
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}", "tests/**/*.test.ts"],
  },
});
```
Если экспорт плагина маршрутизатора называется иначе в установленной версии (`TanStackRouterVite`), взять имя из `node_modules/@tanstack/router-plugin/dist/esm/vite.d.ts`.

- [ ] **Step 3: `tsconfig.json`, `biome.json`, `index.html`, `.gitignore`**

`tsconfig.json`: `"strict": true`, `"jsx": "react-jsx"`, `"moduleResolution": "bundler"`, `"types": ["vite/client", "vitest/globals", "msw/vite/client"]`, `"paths": { "@/*": ["./src/*"] }`, `"include": ["src", "tests", "e2e", "vite.config.ts"]`.

`biome.json`: `"formatter": { "indentStyle": "space", "indentWidth": 2, "lineWidth": 110 }`, `"linter": { "rules": { "recommended": true, "a11y": { "recommended": true } } }`, `"files": { "ignore": ["src/routeTree.gen.ts", "src/api/schema.d.ts", "python/**"] }`.

`index.html`: `lang="ru"`, `<title>amem</title>`, `<meta name="color-scheme" content="light dark">`, инлайн-скрипт до первого рендера: прочитать `localStorage.getItem("amem.theme")` в `try/catch` и выставить `data-theme`, `class` на `<html>`; `<div id="root">`, `<script type="module" src="/src/main.tsx">`.

- [ ] **Step 4: Токены и штамп**

`web/src/styles/theme.css` — значения из разд. 4.2 спецификации (взяты из `shared.css` эскизов): переопределение переменных HeroUI под `:root, [data-theme="light"]` и `[data-theme="dark"]`, плюс свои токены `--fam-source`, `--fam-work`, `--fam-object`, их `-wash`, `--sky`, `--sky-2`, `--sky-ink`, `--sky-muted`, `--mark`, `--press`, `--press-ink`, `--select`, шкала шрифта `--t-*`, отступы `--s-*`, радиусы, длительности. `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { ... } }` повторяет тёмный блок.

`web/src/styles/app.css`:

```css
/* Hallmark · v2.0.0 · shape: app screen · genre: modern-minimal · theme: custom (vibe: "calm apple grouped lists, a night sky of knowledge") · posture: full-palette · modes: light+dark · signature: the claim beside its source, the constellation beside the claim */
/* critique: part A of the amem web UI: shell, folders, record list, search; the sweep runs per part */
@import "tailwindcss";
@import "@heroui/styles";
@import "./theme.css";

html, body { height: 100%; overflow: clip; }
body { margin: 0; background: var(--background); color: var(--foreground); font-family: var(--font); font-synthesis: none; -webkit-font-smoothing: antialiased; }
:where(a, button, input, select, textarea, [tabindex]):focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { transition-duration: 0ms !important; animation-duration: 0ms !important; } }
```
Сверить порядок импортов и имя пакета стилей с текущей страницей установки HeroUI v3 (heroui.com/docs/react/getting-started/installation): Tailwind первым, `@heroui/styles` после него.

- [ ] **Step 5: `main.tsx` с моками по флагу**

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles/app.css";
import { App } from "./app/App";

async function boot() {
  if (import.meta.env.DEV && import.meta.env.VITE_MOCK === "1") {
    const { network } = await import("virtual:msw");
    const { handlers } = await import("./mocks/handlers");
    network.configure({ handlers });
    await network.enable();
  }
  createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
}
boot();
```
`src/app/App.tsx` до Task 8 — заглушка `<main>amem</main>`.

- [ ] **Step 6: Установить, собрать пустой проект**

```bash
cd web && npm install && npm run typecheck && npm run build && ls python/amem_web/dist | head
```
Expected: `index.html`, `assets/`. Предупреждений о версиях нет.

- [ ] **Step 7: Commit**

```bash
git add web .gitignore && git commit -m "web: проект Vite + React 19 + HeroUI v3, токены темы, штамп, сборка в amem_web/dist"
```

### Task 3: Клиент контракта

**Files:**
- Create: `web/src/api/client.ts`, `web/src/api/errors.ts`, `web/src/api/schema.d.ts` (генерируется), `web/src/api/errors.test.ts`

- [ ] **Step 1: Сгенерировать типы**

```bash
npm run api:types && head -20 src/api/schema.d.ts
```
Expected: `export interface paths { "/session": ...`.

- [ ] **Step 2: Тест `ApiError`**

```ts
// src/api/errors.test.ts
import { ApiError, problemFromResponse } from "./errors";

test("problem+json становится ApiError с кодом и замечаниями", async () => {
  const res = new Response(JSON.stringify({ type: "about:blank", title: "Отклонено", status: 422, code: "level1", issues: [{ code: "has_label", severity: "violation", message: "Нет подписи" }] }),
    { status: 422, headers: { "content-type": "application/problem+json" } });
  const err = await problemFromResponse(res);
  expect(err).toBeInstanceOf(ApiError);
  expect(err.status).toBe(422);
  expect(err.code).toBe("level1");
  expect(err.issues[0].message).toBe("Нет подписи");
});

test("ответ без тела становится ApiError по статусу", async () => {
  const err = await problemFromResponse(new Response(null, { status: 503 }));
  expect(err.status).toBe(503);
  expect(err.title).toBe("Служба недоступна");
});
```

- [ ] **Step 3: Запустить — должен упасть**

```bash
npx vitest run src/api/errors.test.ts
```
Expected: FAIL, `Cannot find module './errors'`.

- [ ] **Step 4: Реализация**

```ts
// src/api/errors.ts
import type { components } from "./schema";
type Problem = components["schemas"]["Problem"];
const TITLES: Record<number, string> = { 401: "Нужен вход", 403: "Только чтение", 404: "Не найдено", 409: "Уже решено", 422: "Отклонено проверкой", 503: "Служба недоступна" };

export class ApiError extends Error {
  constructor(public status: number, public title: string, public detail?: string, public code?: string, public issues: NonNullable<Problem["issues"]> = []) { super(detail ?? title); }
}

export async function problemFromResponse(res: Response): Promise<ApiError> {
  const ct = res.headers.get("content-type") ?? "";
  if (ct.includes("json")) {
    try { const p = (await res.json()) as Problem; return new ApiError(p.status ?? res.status, p.title ?? TITLES[res.status] ?? "Ошибка", p.detail, p.code, p.issues ?? []); } catch { /* тело не JSON */ }
  }
  return new ApiError(res.status, TITLES[res.status] ?? "Ошибка");
}
```

```ts
// src/api/client.ts
import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "./schema";
import { problemFromResponse } from "./errors";

const problem: Middleware = {
  async onResponse({ response }) { if (!response.ok) throw await problemFromResponse(response); return response; },
};
export const api = createClient<paths>({ baseUrl: "/api/v1" });
api.use(problem);
```

- [ ] **Step 5: Тест проходит**

```bash
npx vitest run src/api/errors.test.ts
```
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add src/api && git commit -m "web: типы контракта, клиент openapi-fetch, ApiError из problem+json"
```

### Task 4: Реестр оболочки: плагины, виджеты, команды, источники данных

**Files:**
- Create: `web/src/app/plugin.ts`, `web/src/app/registry.ts`, `web/src/app/registry.test.ts`, `web/src/app/core-plugin.ts`

- [ ] **Step 1: Тест реестра**

```ts
// src/app/registry.test.ts
import { createRegistry } from "./registry";
import type { Plugin } from "./plugin";

const plugin: Plugin = {
  id: "test",
  widgets: [{ id: "test.hello", title: { ru: "Привет", en: "Hello" }, slots: ["side"], component: () => null }],
  commands: [{ id: "test.say", title: { ru: "Сказать", en: "Say" }, run: () => {} }],
  dataSources: [{ id: "test.data", kind: "records", search: async () => ({ items: [] }) }],
};

test("плагин регистрирует виджеты, команды и источники данных", () => {
  const r = createRegistry();
  r.register(plugin);
  expect(r.widgets.get("test.hello")?.slots).toContain("side");
  expect(r.commands.get("test.say")).toBeDefined();
  expect(r.dataSources.get("test.data")?.kind).toBe("records");
});

test("повторная регистрация того же id — ошибка", () => {
  const r = createRegistry();
  r.register(plugin);
  expect(() => r.register(plugin)).toThrow(/test/);
});

test("widgetsFor отдаёт виджеты слота в порядке регистрации", () => {
  const r = createRegistry();
  r.register(plugin);
  expect(r.widgetsFor("side").map((w) => w.id)).toEqual(["test.hello"]);
  expect(r.widgetsFor("main")).toEqual([]);
});
```

- [ ] **Step 2: Запустить — упадёт** (`Cannot find module './registry'`).

- [ ] **Step 3: Интерфейсы и реестр**

```ts
// src/app/plugin.ts
import type { ComponentType } from "react";
export type Lang = "ru" | "en";
export type Text = Record<Lang, string>;
export type Slot = "main" | "side" | "rail" | "bottom";
export interface WidgetProps { ref?: string; params?: Record<string, string> }
export interface Widget { id: string; title: Text; slots: Slot[]; component: ComponentType<WidgetProps>; states?: ("loading" | "empty" | "error" | "full")[] }
export interface Command { id: string; title: Text; keys?: string; run: (ctx: { navigate: (to: string) => void }) => void | Promise<void> }
export interface DataSource { id: string; kind: "records" | "files" | "graph"; search: (q: string) => Promise<{ items: unknown[] }> }
export interface Plugin { id: string; widgets?: Widget[]; commands?: Command[]; dataSources?: DataSource[]; routes?: string[] }
```

```ts
// src/app/registry.ts
import type { Plugin, Widget, Command, DataSource, Slot } from "./plugin";
export function createRegistry() {
  const widgets = new Map<string, Widget>(), commands = new Map<string, Command>(), dataSources = new Map<string, DataSource>(), plugins = new Map<string, Plugin>();
  function put<T extends { id: string }>(map: Map<string, T>, items: T[] | undefined, owner: string) {
    for (const it of items ?? []) { if (map.has(it.id)) throw new Error(`${owner}: id ${it.id} уже зарегистрирован`); map.set(it.id, it); }
  }
  return {
    widgets, commands, dataSources, plugins,
    register(p: Plugin) {
      if (plugins.has(p.id)) throw new Error(`плагин ${p.id} уже зарегистрирован`);
      put(widgets, p.widgets, p.id); put(commands, p.commands, p.id); put(dataSources, p.dataSources, p.id); plugins.set(p.id, p);
    },
    widgetsFor(slot: Slot) { return [...widgets.values()].filter((w) => w.slots.includes(slot)); },
  };
}
export type Registry = ReturnType<typeof createRegistry>;
```

`core-plugin.ts` регистрирует плагин `amem` с источником данных `amem.records` (поиск через `api.GET("/search")`) и командами `amem.search` (`⌘K`), `amem.new` (`N`), `amem.theme`; виджеты добавляются по мере частей.

- [ ] **Step 4: Тесты проходят, commit**

```bash
npx vitest run src/app && git add src/app && git commit -m "web: интерфейсы Plugin/Widget/Command/DataSource, реестр оболочки, ядро amem как первый плагин"
```

### Task 5: Тема и перевод

**Files:**
- Create: `web/src/app/theme.ts`, `web/src/app/theme.test.ts`, `web/src/app/i18n.ts`, `web/src/i18n/ru.json`, `web/src/i18n/en.json`, `web/src/i18n/keys.test.ts`, `web/src/app/providers.tsx`, `web/src/test/setup.ts`

- [ ] **Step 1: Тесты**

```ts
// src/app/theme.test.ts
import { applyTheme, readTheme } from "./theme";
test("тема пишется в data-theme и класс html", () => {
  applyTheme("dark");
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(document.documentElement.classList.contains("dark")).toBe(true);
});
test("«как в системе» снимает атрибут", () => {
  applyTheme("system");
  expect(document.documentElement.dataset.theme).toBeUndefined();
});
test("без localStorage тема по умолчанию — system", () => {
  const ls = window.localStorage; Object.defineProperty(window, "localStorage", { get() { throw new Error("blocked"); }, configurable: true });
  expect(readTheme()).toBe("system");
  Object.defineProperty(window, "localStorage", { value: ls, configurable: true });
});
```

```ts
// src/i18n/keys.test.ts
import ru from "./ru.json"; import en from "./en.json";
const flat = (o: object, p = ""): string[] => Object.entries(o).flatMap(([k, v]) => typeof v === "object" && v ? flat(v, `${p}${k}.`) : [`${p}${k}`]);
test("ru и en имеют одинаковые ключи", () => { expect(flat(en).sort()).toEqual(flat(ru).sort()); });
```

- [ ] **Step 2: Запустить — упадут.**

- [ ] **Step 3: Реализация**

`theme.ts`: тип `Theme = "system" | "light" | "dark"`; `readTheme()` — `localStorage.getItem("amem.theme")` в `try/catch`; `applyTheme(t)` — `data-theme` и классы `light`/`dark` (для `system` — снять атрибут, класс по `matchMedia`), запись в `localStorage` в `try/catch`; подписка на `prefers-color-scheme` при `system`.

`i18n.ts`: `i18next.use(initReactI18next).init({ resources: { ru: { translation: ru }, en: { translation: en } }, lng: readLang(), fallbackLng: "ru", interpolation: { escapeValue: false } })`; `readLang()` — `localStorage` → `navigator.language`. Множественные формы — суффиксы `_one`, `_few`, `_many`, `_other`.

Первые ключи `ru.json`: `app.name`, `nav.search`, `nav.review`, `nav.changes`, `nav.write`, `nav.menu`, `folders.title`, `folders.all`, `folders.tags`, `folders.unfiled`, `folders.new`, `records.title`, `records.empty`, `search.placeholder`, `search.results_one/few/many/other`, `search.semantic_off`, `search.exact_code`, `status.*` (7 статусов словами), `family.source`, `family.work`, `family.object`, `region.loading`, `region.error`, `region.retry`, `settings.*`, `theme.system|light|dark`, `lang.ru|en`.

`providers.tsx`: `QueryClientProvider` (`retry: 1`, `staleTime: 30_000`), `I18nProvider` из `react-aria-components` с `locale` из i18next, `I18nextProvider`.

`src/test/setup.ts`: `import "@testing-library/jest-dom/vitest"`, `matchMedia` заглушка, `i18n` инициализация с `ru`.

- [ ] **Step 4: Тесты проходят, commit**

```bash
npx vitest run && git add src && git commit -m "web: тема system/light/dark с защитой localStorage, i18n ru/en с проверкой ключей, провайдеры"
```

### Task 6: Примитивы базы дизайна

**Files:**
- Create: `web/src/ui/RegionState.tsx`, `RegionState.test.tsx`, `StatusText.tsx`, `StatusText.test.tsx`, `KindChip.tsx`, `MetaList.tsx`, `RelativeTime.tsx`, `Highlight.tsx`, `web/src/ui/families.ts`

- [ ] **Step 1: Тесты**

```tsx
// src/ui/RegionState.test.tsx
import { render, screen } from "@testing-library/react";
import { RegionState } from "./RegionState";
test("загрузка показывает скелет с ролью status", () => {
  render(<RegionState state="loading" skeleton={<div data-testid="sk" />}>{() => <p>данные</p>}</RegionState>);
  expect(screen.getByRole("status")).toBeInTheDocument(); expect(screen.getByTestId("sk")).toBeInTheDocument();
});
test("пусто — одна строка и одно действие", () => {
  render(<RegionState state="empty" empty={{ text: "Очередь пуста", action: { label: "Записать", onPress: () => {} } }}>{() => null}</RegionState>);
  expect(screen.getByText("Очередь пуста")).toBeInTheDocument(); expect(screen.getByRole("button", { name: "Записать" })).toBeInTheDocument();
});
test("ошибка — что сломалось и «Повторить»", () => {
  const retry = vi.fn();
  render(<RegionState state="error" error={{ message: "Нет связи со службой", retry }}>{() => null}</RegionState>);
  screen.getByRole("button", { name: "Повторить" }).click(); expect(retry).toHaveBeenCalled();
});
```

```tsx
// src/ui/StatusText.test.tsx
import { render, screen } from "@testing-library/react";
import { StatusText } from "./StatusText";
test("статус передаётся словом и значком, не только цветом", () => {
  render(<StatusText status="needs_review" />);
  expect(screen.getByText("Ждёт проверки")).toBeInTheDocument();
  expect(document.querySelector("svg[aria-hidden='true']")).not.toBeNull();
});
```

- [ ] **Step 2: Запустить — упадут.**

- [ ] **Step 3: Реализация**

`families.ts`: `kindFamily(kind)` → `source | work | object` (параметр, факт, термин, требование — `source`; объекты — `object`; остальное — `work`; неизвестный вид — `work`); `familyLabel`.

`RegionState`: пропсы `state`, `skeleton`, `empty`, `error`, `children: () => ReactNode`; `role="status"` у загрузки и `aria-live="polite"`; кнопки — `Button` HeroUI (`variant="outline"`).

`StatusText`: статус словом из i18n (`status.*`), значок (галочка / часы / крест / тире) из `@gravity-ui/icons` или своих SVG, цвет из токенов `--success/--warning/--danger`; никогда только цвет.

`KindChip`: плашка семьи с точкой (`.kind--source|work|object` из эскизов, перенесённые в CSS-модуль), текст — подпись вида из `vocab`.

`MetaList`: `<dl>` «подпись — значение». `RelativeTime`: `Intl.RelativeTimeFormat` с `<time dateTime>`. `Highlight`: подсветка совпадения в фрагменте (`<mark>`).

- [ ] **Step 4: Тесты проходят, commit**

```bash
npx vitest run src/ui && git add src/ui && git commit -m "web: примитивы базы дизайна: состояния области, статус словом, плашки семей, метаданные, время"
```

### Task 7: Моки контракта и проверка фикстур

**Files:**
- Create: `web/src/mocks/fixtures/session.json`, `folders.json`, `records.json`, `search.json`, `vocab-kind.json`, `vocab-entity_class.json`, `base.json`; `web/src/mocks/handlers.ts`, `web/src/mocks/node.ts`, `web/tests/contract.test.ts`

- [ ] **Step 1: Фикстуры**

Образцы нейтральные (метеостанция МС-1, датчики Т-1, В-2, Д-3, мачта М-2, руководство, паспорт; как в эскизах `docs/superpowers/specs/2026-11-06-amem-web-ui-variants/`): 29 записей с `folder` из набора PARA (`Проекты/Метеоплощадка`, `Области/Приборы`, `Ресурсы/Источники`, `Архив/Станция 2024`), 3 со статусом `needs_review`, 2 `draft`; `search.json` — ответ `exact_fact` на «погрешность» с точным совпадением кода первой строкой и `semantic: "used"`; второй вариант `search-semantic-off.json` с `semantic: "unavailable"`.

- [ ] **Step 2: Тест фикстур по контракту**

```ts
// tests/contract.test.ts
import { readFileSync } from "node:fs";
import { parse } from "yaml";
import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import session from "../src/mocks/fixtures/session.json";
import folders from "../src/mocks/fixtures/folders.json";
import records from "../src/mocks/fixtures/records.json";
import search from "../src/mocks/fixtures/search.json";

const spec = parse(readFileSync(new URL("../../docs/api/http-v1.openapi.yaml", import.meta.url), "utf8"));
const ajv = new Ajv2020({ strict: false, allErrors: true }); addFormats(ajv);
ajv.addSchema({ $id: "openapi", components: spec.components });
const check = (name: string, data: unknown) => {
  const ok = ajv.validate({ $ref: `openapi#/components/schemas/${name}` }, data);
  expect(ajv.errorsText(ajv.errors, { dataVar: name })).toBe("No errors"); expect(ok).toBe(true);
};
test("session.json соответствует Session", () => check("Session", session));
test("folders.json соответствует FolderTree", () => check("FolderTree", folders));
test("records.json соответствует RecordList", () => check("RecordList", records));
test("search.json соответствует SearchResult", () => check("SearchResult", search));
```

- [ ] **Step 3: Запустить — упадёт на отсутствующих фикстурах; написать фикстуры; прогнать до зелёного**

```bash
npx vitest run tests/contract.test.ts
```
Expected: 4 passed. Любое расхождение фикстуры и контракта — ошибка, а не предупреждение.

- [ ] **Step 4: Обработчики**

```ts
// src/mocks/handlers.ts
import { http, HttpResponse, delay } from "msw/http";
import session from "./fixtures/session.json"; import folders from "./fixtures/folders.json";
import records from "./fixtures/records.json"; import search from "./fixtures/search.json";
import vocabKind from "./fixtures/vocab-kind.json"; import vocabClass from "./fixtures/vocab-entity_class.json";
import base from "./fixtures/base.json";

export const handlers = [
  http.get("/api/v1/session", () => HttpResponse.json(session)),
  http.get("/api/v1/folders", () => HttpResponse.json(folders)),
  http.get("/api/v1/records", async ({ request }) => {
    await delay(150);
    const url = new URL(request.url); const folder = url.searchParams.get("folder");
    const items = folder ? records.items.filter((r) => r.folder?.startsWith(folder)) : records.items;
    return HttpResponse.json({ items, total: items.length, next_cursor: null });
  }),
  http.get("/api/v1/search", async ({ request }) => {
    await delay(200);
    const q = new URL(request.url).searchParams.get("q") ?? "";
    if (!q.trim()) return HttpResponse.json({ ...search, items: [], candidate_count: 0 });
    if (q === "ошибка") return HttpResponse.json({ type: "about:blank", title: "Служба недоступна", status: 503 }, { status: 503, headers: { "content-type": "application/problem+json" } });
    return HttpResponse.json(search);
  }),
  http.get("/api/v1/vocab/kind", () => HttpResponse.json(vocabKind)),
  http.get("/api/v1/vocab/entity_class", () => HttpResponse.json(vocabClass)),
  http.get("/api/v1/base", () => HttpResponse.json(base)),
];
```
`node.ts`: `export const server = setupServer(...handlers)` из `msw/node`; в `src/test/setup.ts` — `beforeAll(() => server.listen({ onUnhandledRequest: "error" }))`, `afterEach(() => server.resetHandlers())`, `afterAll(() => server.close())`.

- [ ] **Step 5: Commit**

```bash
git add src/mocks tests && git commit -m "web: фикстуры-образцы и обработчики MSW по контракту, проверка фикстур схемами OpenAPI"
```

### Task 8: Оболочка, папки, список записей, результаты поиска

**Files:**
- Create: `web/src/app/App.tsx`, `web/src/app/shell/Layout.tsx`, `TopBar.tsx`, `Folders.tsx`, `AppMenu.tsx`, `web/src/api/queries/session.ts`, `folders.ts`, `records.ts`, `search.ts`, `vocab.ts`, `web/src/routes/__root.tsx`, `index.tsx`, `search.tsx`, `settings.tsx`, заглушки `atom.$ref.tsx`, `entity.$ref.tsx`, `review.tsx`, `review.$itemId.tsx`, `changes.tsx`, `new.tsx`, `base.tsx`, `bundles.tsx`, `web/src/features/records/RecordList.tsx`, `RecordList.test.tsx`, `web/src/features/search/SearchResults.tsx`, `SearchResults.test.tsx`, `web/src/features/search/params.ts`, `params.test.ts`

- [ ] **Step 1: Тест параметров поиска в URL**

```ts
// src/features/search/params.test.ts
import { searchParams } from "./params";
test("параметры поиска валидны и переживают ссылку", () => {
  expect(searchParams.parse({ q: "погрешность", kind: ["parameter"], status: ["verified"], limit: "10" })).toEqual({ q: "погрешность", kind: ["parameter"], status: ["verified"], class: [], limit: 10 });
  expect(searchParams.parse({ q: "x", limit: "999" }).limit).toBe(100);
  expect(searchParams.parse({}).q).toBe("");
});
```

- [ ] **Step 2: Тесты списка и результатов (на моках `node.ts`)**

```tsx
// src/features/records/RecordList.test.tsx
import { render, screen } from "@testing-library/react";
import { withProviders } from "@/test/with-providers";
import { RecordList } from "./RecordList";
test("список записей: сначала скелет, потом строки со статусом словом", async () => {
  render(withProviders(<RecordList folder={null} />));
  expect(screen.getByRole("status")).toBeInTheDocument();
  expect(await screen.findByText("Диапазон температуры: −40…+60 °C")).toBeInTheDocument();
  expect(screen.getAllByText("Проверено").length).toBeGreaterThan(0);
});
test("папка фильтрует список", async () => {
  render(withProviders(<RecordList folder="Архив" />));
  expect(await screen.findByText(/Станция/)).toBeInTheDocument();
});
```

```tsx
// src/features/search/SearchResults.test.tsx
test("точное совпадение кода идёт первым с подписью", async () => {
  render(withProviders(<SearchResults params={{ q: "погрешность", kind: [], status: [], class: [], limit: 10 }} />));
  const rows = await screen.findAllByRole("link");
  expect(screen.getByText("Точное совпадение кода")).toBeInTheDocument();
  expect(rows[0]).toHaveTextContent("Погрешность");
});
test("смысловой канал выключен — тихая строка, список есть", async () => { /* server.use с search-semantic-off.json */ });
test("ошибка службы — что сломалось и «Повторить»", async () => { /* q=ошибка → 503 → RegionState error */ });
```
`src/test/with-providers.tsx` оборачивает в `QueryClientProvider` с `retry: false`, `I18nextProvider`, память роутера.

- [ ] **Step 3: Запустить — упадут.**

- [ ] **Step 4: Реализация**

`queries/*.ts` — `queryOptions({ queryKey: ["records", folder], queryFn: () => api.GET("/records", { params: { query: { folder } } }).then((r) => r.data!) })` и т. п.; компоненты не знают путей API.

`params.ts`:
```ts
import { z } from "zod";
const list = z.preprocess((v) => (v == null ? [] : Array.isArray(v) ? v : [v]), z.array(z.string()));
export const searchParams = z.object({ q: z.string().default(""), kind: list, status: list, class: list, limit: z.coerce.number().int().min(1).max(100).catch(100).default(10) });
export type SearchParams = z.infer<typeof searchParams>;
```

`__root.tsx` — `Layout`: сетка `grid-template-columns: 248px minmax(0,1fr) [side]`, высота `calc(100dvh - 56px)`, прокрутка внутри слотов (разд. 7.2 «как приложение»); `TopBar` (знак `amem`, поле поиска `SearchField` HeroUI с `⌘K`, «Проверка» со счётчиком из `/review/stats` — до части E счётчик из фикстуры `base.json`, «Изменения», «Записать», тема, меню); `Folders` — дерево из `/folders` с «Все записи», «Теги», «Без папки», «+ Папка» (в части A — только показ; создание и перенос — часть D); `<Outlet />` в слоте `main`. Слот `side` пустой до части C.

`index.tsx` — «Все записи» (`RecordList`) с параметром `?folder=`. `search.tsx` — `validateSearch: searchParams.parse`, `SearchResults` со строкой фильтров (`Select` HeroUI, множественный выбор из `vocab`), «Показать ещё» до 100. `settings.tsx` — тема и язык (`RadioGroup`). Остальные маршруты — заглушка «Экран появится в части B/C/D/E/F» через `RegionState` в состоянии `empty`.

Клавиши части A: `/` и `⌘K` — фокус в поиск; `G` затем `H` — главная; `⌘,` — настройки (`src/app/keys.ts`, по `event.code`, не в полях ввода).

- [ ] **Step 5: Тесты проходят; запустить вживую**

```bash
npx vitest run && npm run dev:mock
```
Открыть `http://localhost:5173/ui/`: панель папок, список записей; `http://localhost:5173/ui/search?q=погрешность` — результаты; переключить тему и язык в настройках.

- [ ] **Step 6: Commit**

```bash
git add src && git commit -m "web: оболочка без прокрутки страницы, верхняя строка, папки, список записей, результаты поиска с параметрами в URL, настройки"
```

### Task 9: e2e и доступность

**Files:**
- Create: `web/playwright.config.ts`, `web/e2e/shell.spec.ts`, `web/e2e/search.spec.ts`, `web/e2e/a11y.spec.ts`

- [ ] **Step 1: Конфиг**

```ts
import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "e2e", fullyParallel: true, retries: process.env.CI ? 1 : 0, reporter: process.env.CI ? [["html", { open: "never" }], ["github"]] : "list",
  use: { baseURL: "http://127.0.0.1:5173/ui/", trace: "retain-on-failure" },
  webServer: { command: "npm run dev:mock", url: "http://127.0.0.1:5173/ui/", reuseExistingServer: !process.env.CI },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } } },
    { name: "phone", use: { ...devices["Pixel 7"] } },
  ],
});
```

- [ ] **Step 2: Тесты**

`shell.spec.ts`: папки видны, «Все записи» показывает строки, страница не прокручивается (`document.documentElement.scrollHeight <= clientHeight` на desktop), тема переключается (`html[data-theme=dark]`), язык меняет подпись «Проверка» → «Review». `search.spec.ts`: ввод «погрешность» + Enter → `/ui/search?q=…`, первая строка с подписью точного совпадения, фильтр вида в URL, «Показать ещё». `a11y.spec.ts`: `AxeBuilder` на `/`, `/search?q=погрешность`, `/settings` в обеих темах; `expect(results.violations.filter(v => ["serious","critical"].includes(v.impact!))).toEqual([])`.

- [ ] **Step 3: Запустить**

```bash
npx playwright install --with-deps chromium && npm run e2e
```
Expected: все зелёные на двух проектах.

- [ ] **Step 4: Commit**

```bash
git add playwright.config.ts e2e && git commit -m "web: e2e оболочки и поиска на моках, axe в обеих темах, ширины 375 и 1280"
```

### Task 10: Дистрибутив `amem-web` и extra `web`

**Files:**
- Create: `web/python/pyproject.toml`, `web/python/amem_web/__init__.py`, `web/python/amem_web/dist/.gitkeep` (сам `dist/` в `.gitignore`), `web/python/tests/test_static.py`
- Modify: `pyproject.toml` (корень) — `web = ["amem-web==0.1.0.dev0"]` в `optional-dependencies`

- [ ] **Step 1: Тест**

```python
# web/python/tests/test_static.py
import pytest, amem_web
def test_static_dir_points_to_built_index():
    d = amem_web.static_dir()
    if not (d / "index.html").exists():
        pytest.skip("статика не собрана: npm run build")
    assert (d / "assets").is_dir()
    assert "<div id=\"root\">" in (d / "index.html").read_text(encoding="utf-8")
```

- [ ] **Step 2: Реализация**

```toml
# web/python/pyproject.toml
[project]
name = "amem-web"
version = "0.1.0.dev0"
description = "Статика веб-интерфейса amem; служба отдаёт её по /ui"
license = {text = "MIT"}
requires-python = ">=3.11"
[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"
[tool.hatch.build.targets.wheel]
packages = ["amem_web"]
artifacts = ["amem_web/dist/**"]
```

```python
# web/python/amem_web/__init__.py
"""Статика веб-интерфейса amem. Служба (подпроект 4) монтирует static_dir() по /ui."""
from importlib import resources
from pathlib import Path
__version__ = "0.1.0.dev0"
def static_dir() -> Path:
    """Папка со сборкой: index.html и assets/ с хэшами в именах."""
    return Path(str(resources.files("amem_web") / "dist"))
```

- [ ] **Step 3: Собрать и проверить**

```bash
npm run build && cd python && pip install -e . -q && pytest -q tests && cd .. && python -c "import amem_web; print(amem_web.static_dir())"
```
Expected: тест прошёл, путь на `dist`.

- [ ] **Step 4: Commit**

```bash
git add web/python pyproject.toml && git commit -m "web: дистрибутив amem-web со статикой и static_dir(), extra amem[web]"
```

### Task 11: Бюджеты и CI

**Files:**
- Create: `web/.size-limit.json`, `.github/workflows/web.yml`

- [ ] **Step 1: `.size-limit.json`**

```json
[
  { "name": "JS первой загрузки", "path": "python/amem_web/dist/assets/index-*.js", "limit": "220 kB", "gzip": true },
  { "name": "CSS", "path": "python/amem_web/dist/assets/*.css", "limit": "40 kB", "gzip": true }
]
```

- [ ] **Step 2: `web.yml`**

```yaml
name: web
on:
  push: { paths: ["web/**", "docs/api/**", ".github/workflows/web.yml"] }
  pull_request: { paths: ["web/**", "docs/api/**", ".github/workflows/web.yml"] }
jobs:
  web:
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: web } }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 24, cache: npm, cache-dependency-path: web/package-lock.json }
      - run: npm ci
      - run: npm run lint
      - run: npm run api:check
      - run: npm run typecheck
      - run: npm test
      - run: npm run build
      - run: npm run size
      - run: npx playwright install --with-deps chromium
      - run: npm run e2e
      - uses: actions/upload-artifact@v4
        if: failure()
        with: { name: playwright-report, path: web/playwright-report, retention-days: 7 }
```

- [ ] **Step 3: Прогнать локально то же, что CI**

```bash
npm run lint && npm run api:check && npm run typecheck && npm test && npm run build && npm run size && npm run e2e
```
Expected: всё зелёное; размеры в бюджете (при превышении — отложить ленивые куски, проверить, что HeroUI импортируется поимённо).

- [ ] **Step 4: Commit**

```bash
git add .size-limit.json ../.github/workflows/web.yml && git commit -m "web: бюджеты размера и workflow web.yml"
```

### Task 12: Бриф поверхности и проход по дизайну

**Files:**
- Create: `web/.impeccable/surfaces/shell.md` (через `impeccable surface-brief write`), `web/.hallmark/log.json`
- Modify: `web/src/styles/app.css` (строки штампа при изменениях)

- [ ] **Step 1: Бриф поверхности с контрактом направления (разд. 4.1 спецификации)**

```bash
cd web && "$HOME/.claude/skills/impeccable/scripts/impeccable" context
"$HOME/.claude/skills/impeccable/scripts/impeccable" surface-brief write src/app/shell/Layout.tsx /tmp/claude-1000/brief.md
```
В `brief.md` — шесть блоков THESIS / OWN-WORLD / STORY / FIRST VIEWPORT / FORM / FINISH из разд. 4.1, дословно.

- [ ] **Step 2: Линтеры дизайна на двух экранах**

```bash
npm run dev:mock &
node "$HOME/.claude/skills/hallmark/scripts/sloplint.mjs" src/styles/app.css src/styles/theme.css --scope app --genre modern-minimal --url http://127.0.0.1:5173/ui/ --render
node "$HOME/.claude/skills/hallmark/scripts/sloplint.mjs" src/styles/app.css --scope app --url "http://127.0.0.1:5173/ui/search?q=погрешность" --render
"$HOME/.claude/skills/impeccable/scripts/impeccable" detect --json src/ http://127.0.0.1:5173/ui/
```
Expected: `0 FAIL`; каждый `REFLEX` исправлен или снят строкой `/* Hallmark · waive <gate> · <guard> · <reason> */` в `app.css`; `impeccable detect` без находок уровня error.

- [ ] **Step 3: Commit**

```bash
git add .impeccable src/styles && git commit -m "web: бриф поверхности с контрактом направления, проход sloplint и impeccable detect"
```

### Завершение части A

- [ ] Все тесты и e2e зелёные локально; `npm run build` в бюджете.
- [ ] README (en/ru): одна строка в разделе о состоянии — «веб-UI в работе: часть A, `web/`, `npm run dev:mock`» (полные разделы — в части G).
- [ ] PR в `empty-complete/amem` с автослиянием после зелёных `test` и `web`:

```bash
git push -u origin subproject-5a-web-foundation
gh pr create --repo empty-complete/amem --title "Подпроект 5, часть A: контракт HTTP v1, проект web/, оболочка, папки, список и поиск на моках, amem-web, CI" --body-file /tmp/claude-1000/pr.md
gh pr merge --repo empty-complete/amem --merge --auto
```
- [ ] После слияния: `git worktree remove ../amem-web-a`, ветку удалить локально и на origin; добавить проверку `web` в набор правил `main` только в части G.

---

## Части B–H — задачами (у каждой свой план перед началом)

### Часть B — чтение (ветка `subproject-5b-reading`)

- **Task B1. Страница записи, представление «для человека»** (`features/record/`): заголовок, свойства из шаблона (`GET /vocab/kind`, шаблоны — `GET /vocab/template` добавить в контракт), тело Markdown (`micromark` + плагин `[[ссылок]]`, KaTeX по требованию), виджеты «Источники», «Связи», низ с ревизией. Тест: Markdown с формулой и `[[ссылкой]]` отрисован; `[[Имя]]` ведёт на `/atom|entity/:ref` по `label`.
- **Task B2. Исходник и «Как видит агент»**: исходник YAML+Markdown только для чтения (CodeMirror 6 в режиме `readOnly`), экран `?view=agent` с телом `amem.atom/1` (YAML для чтения, JSON «Скопировать»). Тест: перевод записи в документ и обратно даёт тот же атом (функция `recordToDocument` / `documentToRecord` в `features/record/doc.ts`, таблица правил разд. 5.4).
- **Task B3. Панель источника** (`features/source/`): PDF-страница с подсветкой цитаты (`pdfjs-dist` ленивым куском, слой текста, поиск цитаты с нормализацией пробелов), текстовые фрагменты для md/xlsx/docx (`/objects/{id}/versions/{n}/text?page`), сайт и переписка, итог сверки словами, несколько источников, `basis` без источника. Тест: цитата найдена в спанах слоя текста PDF-образца (фикстура `fixtures/manual.pdf`, 2 страницы, нейтральный текст).
- **Task B4. Страница источника** (`features/source/ObjectPage.tsx`, разд. 5.12): превью по формату (таблица листами с подсветкой цитируемых диапазонов, PDF страницами, текст, картинка), путь и «Показать в папке» (`POST /objects/{id}/reveal` — добавить в контракт; в вебе — копирование пути), версии, «Ссылаются на этот файл», «Не разобрано» с «Попросить агента» (`POST /tasks` — контракт части D).
- **Task B5. Страница объекта** (`features/card/`): заголовок с путём по `part_of`, полоса полноты, группы профиля `amem.card/1` с состояниями known / conflict / na / asked / missing, умолчание серым, «из: предок»; вкладки «Атомы» и «История». Тест: карточка-фикстура со всеми состояниями отрисована; обязательное пустое помечено «Нужно».
- **Task B6. Связи, похожие, изменения**: вкладки записи, страница `/changes` по дням с фильтрами «Люди / Агенты» и период.
- **Task B7. Командная строка** у поля поиска: комбобокс React Aria, до 6 записей по `exact_fact` и команды реестра; Enter без выбора — результаты.
- **Task B8. e2e чтения**: поиск → запись → цитата подсвечена; объект → карточка; источник → превью; `?view=agent`; axe на всех маршрутах части.

### Часть C — небо (ветка `subproject-5c-sky`)

- **Task C1. Компонент `sky`** (`features/sky/`): `force-graph` 2D на canvas, данные из `GET /graph`, семьи и статусы как в эскизах (кольцо у объектов, пунктир у ждущих, выбранная звезда и соседи ярче), подписи без наложений (перенос алгоритма из `graph.js` эскизов на `nodeCanvasObject`), наведение, выбор, двойное нажатие — переход, перетаскивание, зум, `dblclick` — вернуть вид, предел 300 звёзд со строкой, `prefers-reduced-motion`.
- **Task C2. Виджет неба в стопке справа**: слот `side` оболочки, сворачивание, «Ссылки сюда», «Слои» (пакеты, личное, скрытый слой через фильтр по `visibility`/пакету).
- **Task C3. Небо как вход**: главная `/` заменяет список (список остаётся под «Все записи»), фильтры семей и «Ждут решения», карточка выбранной звезды, клавиши `/`, `N`, `Esc`, `1 2 3`.
- **Task C4. Вспышка новой звезды и `addNode`** — API компонента для части D; 3D (`3d-force-graph`) ленивым куском по переключателю.
- **Task C5. e2e**: небо на главной и на записи; куски графа не входят в первую загрузку (проверка манифеста сборки); 300+ узлов — строка.

### Часть D — запись человека (ветка `subproject-5d-writing`)

- **Task D1. Контракт записи**: `POST /submit` с `proposals` из документа; `PATCH /records/{ref}/folder`; `GET /vocab/template` и `PUT /packs/mine/templates/{code}` (конструктор); `POST /tasks` («Попросить агента»); фикстуры и проверка по схемам.
- **Task D2. Правка записи на месте** (карандаш, `⌘E`): свойства по шаблону (объект, запись, число с единицей из словаря `property`, дата, выбор, теги, «+ Свойство»), тело в CodeMirror 6 с панелью B/I/код/H2/цитата/список/`[[ ]]`/формула, исходник редактируемый (`⌘\`), перевод в атом (`documentToRecord`), отказ уровней 1–2 — замечания у полей; своя запись → новая ревизия.
- **Task D3. Новая запись**: `/new` — тот же экран в правке с подстановкой «О чём»; окно по `N` (свёрнутый вариант: одно поле, вид из текста, «Все поля»); строка «Добавить заметку» в карточке объекта; заполнение пустого поля карточки и «Принять» умолчание; окно отмены 6 с с `keepalive`.
- **Task D4. Источники в записи**: «+ Источник» — выбор объекта или добавление файла (`POST /objects` multipart — в контракт), место в файле по виду (страница и цитата; лист и диапазон с выбором в превью; `bbox` рамкой на картинке; раздел и строки).
- **Task D5. Папки**: «+ Папка», перетаскивание записи между папками (`PATCH …/folder`), переименование; начальные папки PARA у новой базы (фикстура и правило службы).
- **Task D6. Конструктор вида**: выдвижная панель «настроить»: свойства и типы, «нужно», тело, виджеты; сохранение в пакет «Мои виды»; проверка шаблона теми же правилами, что у пакетов из файлов (`amem/check/templates.py`, через контракт).
- **Task D7. e2e**: заметка, вопрос, параметр, умолчание, отмена, запись по шаблону пакета с источником-таблицей, свой вид из конструктора, правка с цитатой, перенос в папку.

### Часть E — проверка (ветка `subproject-5e-review`)

- **Task E1. Очередь в две панели** (`features/review/`): список с фильтрами, пункт с утверждением и источником (тот же компонент, что на записи), замечания, сравнение ревизий для `edit`, версии для `source_changed`, вердикт модели для `semantic_doubt`.
- **Task E2. Решения**: `useUndoableDecision` (6 с, `keepalive`), 409 «Уже решено», клавиши `J K Y N S /`, «Поставить на проверку» из меню записи, счётчик в верхней строке по `review/stats`.
- **Task E3. База `/base`** со статистикой очереди, статусами, пакетами, бэкапами.
- **Task E4. e2e** очереди с клавиатуры.

### Часть F — подборки (ветка `subproject-5f-bundles`)

- **Task F1. `amem/anthology.py`** в ядре: отбор `verified` + `preferred`, подборка `amem.bundle/1` и HTML-отчёт; тесты на PostgreSQL 18 и 16 (в `ci.yml`).
- **Task F2. Экран подборок**: экспорт с отбором и антологией, импорт (inspect → dry_run → import) с отчётами; экспорт/импорт конфига (папки, виды, виджеты) частью `ui` подборки.
- **Task F3. e2e** пробного импорта.

### Часть G — отделка (ветка `subproject-5g-finish`)

- **Task G1.** `/impeccable critique`, `audit`, `polish`, `harden` по каждому экрану; `sloplint --scope app --render` по всем маршрутам; снимки-эталоны в CI.
- **Task G2.** Финальный обзор свежим взглядом (агент `impeccable-finish-reviewer`), вердикт «ship»; `/impeccable document` → `web/DESIGN.md`.
- **Task G3.** README (en/ru): разделы о веб-UI, `amem[web]`, `npm run dev:mock`; проверка `web` в набор правил `main`.

### Часть H — связь со службой (после подпроекта 4, ветка `subproject-5h-service`)

- **Task H1.** Служба отдаёт `/ui` из `amem_web.static_dir()`: хэшированные файлы `immutable`, `index.html` `no-cache`, неизвестные пути под `/ui/` → `index.html`.
- **Task H2.** Тест службы: каждый ответ контракта v1 проходит схему `http-v1.openapi.yaml`; UI — `api:check`.
- **Task H3.** e2e против настоящей службы в compose (профиль `web`): поиск, запись, решение, подборка.

---

## Самопроверка плана по спецификации

- Разд. 6 (контракт) — Task 1 (+ дополнения контракта в B1, B4, D1); разд. 7.1 (папки проекта) — Task 2, 8; разд. 7.2 (оболочка, виджеты, плагины, «как приложение») — Task 4, 8; разд. 4.2 (токены) — Task 2; разд. 4.3 (правила минимализма) — Task 8, 12; разд. 5.1, 5.3, 5.10 (настройки), 5.11 (папки), 5.13 (клавиши части A) — Task 8; разд. 7.3 (данные и состояние) — Task 3, 8; разд. 7.4 (перевод) — Task 5; разд. 7.5 (поставка) — Task 10; разд. 9 (качество) — Task 6, 9, 11, 12; разд. 10 — структура частей.
- Главная в части A — список «Все записи»; небо как вход (разд. 5.2) приходит в части C (Task C3) и заменяет её, список остаётся под «Все записи».
- Имена и сигнатуры: `createRegistry` / `widgetsFor` (Task 4) используются в Task 8; `ApiError` / `problemFromResponse` (Task 3) — в `RegionState` ошибках (Task 6, 8); `searchParams` (Task 8) — в e2e (Task 9); `static_dir()` (Task 10) — в части H.
