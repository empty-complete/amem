# amemo — подпроект 5, часть C «Небо»: план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Созвездие базы как живой граф. Главная `/` — небо во весь экран: фильтры семей, «Ждут решения», карточка выбранной звезды. Окно неба на странице объекта (справа, 440 px) и на странице записи (виджет «Окрестность», 340 px). Звёзды укладываются на глазах, их можно тянуть, небо — двигать и приближать. Подписи не накладываются. Клавиатура: стрелки по соседям, Enter, Esc, N, глубина `1 2 3`. Компонент даёт API «добавить звезду со вспышкой» для части D. 3D — отдельным ленивым куском по переключателю.

**Architecture:** `web/src/features/sky/`:
- чистая модель (`model.ts`: данные графа → звёзды и рёбра, соседи, приглушение по фильтру, выбор подписей, раскладка подписей без наложений, переход стрелками) — всё с модульными тестами;
- холст (`SkyCanvas.tsx`, ленивый кусок с `force-graph`): рисует модель и отдаёт события;
- окно (`Sky.tsx`): заголовок с глубиной и полноэкранным режимом, холст, честная строка о пределе, панель выбранной звезды, клавиши, `aria-live`.

Главная, страница объекта и страница записи ставят окно в свои слоты. `force-graph` и `3d-force-graph` в первую загрузку не попадают.

Спецификация: `docs/superpowers/specs/2026-11-06-amemo-subproject-5-web-ui-design.md`, разд. 4.4, 5.2, 5.6, 5.13, 7.2, 9.2. Эскизы: `v6-sky`, `v3-object`, `v8-note`. Исходник живого графа эскизов (`graph.js`: укладка, перетаскивание, зум, подписи) — образец для подписей и вида звёзд.

**Tech Stack:** то, что уже есть после частей A–B, плюс `force-graph` 1.52 (canvas 2D, d3-force: укладка, перетаскивание, зум) и `3d-force-graph` 1.80 (WebGL, лениво, только по переключателю «3D»).

**Ветка:** `subproject-5c-sky` от `main`. Worktree: `~/projects/amemo-web-c`.

**Связь с подпроектом 4.** `GET /graph` есть в контракте, но требует `ref`. Для неба-входа нужен обзор базы без `ref`, а для честной строки — число всех звёзд. Изменения контракта (Task 1) — этой веткой; службе сообщить до начала.

---

## Карта файлов

| Файл | За что отвечает |
|---|---|
| `docs/api/http-v1.openapi.yaml` | `GET /graph`: `ref` не обязателен (обзор базы), `limit`, `GraphResult.total`, `GraphNode.pending`, `GraphNode.degree` |
| `web/src/features/sky/model.ts` + `model.test.ts` | Звёзды и рёбра из `GraphResult`, соседи, приглушение, какие подписи видны, раскладка подписей, переход стрелками |
| `web/src/features/sky/colors.ts` | Цвета неба из токенов CSS (`--sky`, `--sky-ink`, `--fam-*`), обновление при смене темы |
| `web/src/features/sky/SkyCanvas.tsx` | Лениво: `force-graph`, рисование звёзд и подписей, события, `add()` со вспышкой, `zoomToFit` |
| `web/src/features/sky/Sky3D.tsx` | Лениво: `3d-force-graph` по переключателю «3D» |
| `web/src/features/sky/Sky.tsx` + `Sky.test.tsx` | Окно неба: заголовок (глубина, 3D, во весь экран), холст, строка о пределе, панель звезды, клавиши, `aria-live`, состояния |
| `web/src/features/sky/StarCard.tsx` | Панель выбранной звезды: плашка вида, статус, заголовок, строка, «Открыть», «Окрестность», «Заметка» |
| `web/src/features/sky/bus.ts` | Событие «запись создана» для вспышки (часть D пишет, небо слушает) |
| `web/src/features/sky/sky.css` | Окно, панель, легенда, подсказки клавиш |
| `web/src/features/home/HomeSky.tsx` | Главная: итог, фильтры, небо во весь экран, карточка справа, легенда и клавиши, пустая база |
| `web/src/routes/index.tsx`, `routes/records.tsx` | `/` — небо; `/records?folder=` — список (бывшая главная части A) |
| `web/src/app/shell/Folders.tsx`, `app/keys.ts` | Ссылки папок ведут на `/records`; `1 2 3`, `N` и `?` — через реестр клавиш |
| `web/src/features/card/CardPage.tsx`, `features/record/RecordPage.tsx` | Окно неба справа на странице объекта; виджет «Окрестность» на записи |
| `web/src/mocks/fixtures/graph-*.json`, `web/tools/make-graph-fixtures.py` | Обзор базы, окрестности, большая база (420 звёзд) для строки о пределе |
| `web/e2e/sky.spec.ts`, `a11y.spec.ts` | e2e неба; axe на главной, объекте и записи |
| `web/tools/check-chunks.mjs` | Проверка манифеста сборки: граф не входит во входной кусок |

---

### Task 0: Исходная точка

- [ ] **Step 1:** `cd ~/projects/amemo && git fetch origin && git worktree add ../amemo-web-c -b subproject-5c-sky origin/main`
- [ ] **Step 2:** `cd ../amemo-web-c/web && npm ci && npm test` — зелёные.
- [ ] **Step 3:** `npm install --no-audit --no-fund force-graph@^1.52 3d-force-graph@^1.80`
- [ ] **Step 4:** Проверить типы: `node -e "require.resolve('force-graph/dist/force-graph.d.ts')"`. Если типов нет, написать `src/types/force-graph.d.ts` с нужным подмножеством API: `graphData`, `nodeCanvasObject`, `nodePointerAreaPaint`, `linkColor`, `onNodeClick`, `onNodeHover`, `onNodeDrag`, `onBackgroundClick`, `onRenderFramePost`, `zoomToFit`, `centerAt`, `zoom`, `cooldownTime`, `warmupTicks`, `d3ReheatSimulation`, `graph2ScreenCoords`, `width`, `height`, `_destructor`.
- [ ] **Step 5: Commit** `web: зависимости части C (force-graph, 3d-force-graph)`.

### Task 1: Контракт графа

**Files:** Modify `docs/api/http-v1.openapi.yaml`, `docs/api/README.md` (раздел «Изменения»).

Перед правкой — сообщение сессии подпроекта 4 с перечнем изменений.

- [ ] **Step 1:** `/graph`:
  - `ref` — `required: false`, описание: «Без ref — обзор базы: все сущности и самые связанные записи до `limit`; у большой базы — в пределах `scope.project`, если он задан параметром `project`»;
  - параметры `limit` (`integer`, 1–1000, по умолчанию 300) и `project` (`string`).
- [ ] **Step 2:** `GraphResult`: `ref` — `[string, "null"]`; поле `total: { type: integer, description: "Сколько звёзд было бы без предела" }`.
- [ ] **Step 3:** `GraphNode`: `pending: { type: boolean, description: "Есть открытый пункт проверки" }` и `degree: { type: integer, description: "Число связей в базе, а не только в выдаче" }`. Ни то ни другое не обязательно: UI считает степень по выдаче, если `degree` нет.
- [ ] **Step 4:** Линтер redocly и `npm run api:types` — чисто.
- [ ] **Step 5: Commit** `api: обзор базы в GET /graph без ref, предел и total, pending и degree у звезды`.

### Task 2: Образцы графа

**Files:** Create `web/tools/make-graph-fixtures.py`, `web/src/mocks/fixtures/graph-base.json`, `graph-e3.json`, `graph-a3.json`, `graph-big.json`; Modify `web/src/mocks/handlers-b.ts` (или новый `handlers-c.ts`), `web/src/mocks/{browser,node}.ts`, `web/tests/contract.test.ts`.

- [ ] **Step 1:** Генератор берёт записи из `records.json` и строит граф:
  - узлы — все 31 запись: семья по `familyOf`, `pending` — у `needs_review`;
  - рёбра — `about` (атом → сущность), `part_of` (датчики и мачта → станция → площадка) и связи из `links-a3.json`;
  - `graph-e3.json` — окрестность «Датчик влажности В-2», глубина 2;
  - `graph-a3.json` — окрестность записи «Погрешность влажности В-2», глубина 2;
  - `graph-big.json` — 420 синтетических звёзд «Узел N» вокруг 12 объектов; выдача обрезана до 300, `total: 420`, `truncated: true`.
- [ ] **Step 2:** Обработчик `GET /api/v1/graph`:
  - без `ref` — `graph-base.json`, а при `?project=big` — `graph-big.json`;
  - `ref` E3 или A3 — их окрестности; глубина 1 — только `depth ≤ 1`;
  - неизвестный `ref` — `{ref, nodes: [], edges: [], truncated: false, total: 0}`;
  - запрос «пусто» (`?project=empty`) — пустая база.
- [ ] **Step 3:** Проверка схемой `GraphResult` для всех четырёх в `tests/contract.test.ts`.
- [ ] **Step 4: Commit** `web: образцы графа — обзор базы, окрестности объекта и записи, большая база; обработчик /graph`.

### Task 3: Модель неба

**Files:** Create `web/src/features/sky/model.ts`, `model.test.ts`.

- [ ] **Step 1: Тесты**

```ts
import base from "../../mocks/fixtures/graph-base.json";
import { arrowNeighbour, buildSky, dimmed, placeLabels, visibleLabels } from "./model";

const E3 = "ent:0193b7c2-5e1a-7d40-9f2e-000000000003";
const A3 = "atm:0193b7c2-5e1a-7d40-9f2e-00000000000b";

test("звёзды: объекты крупнее и растут со степенью, атомы — точки; ждущие помечены", () => {
  const s = buildSky(base as never);
  const e3 = s.byId.get(E3)!;
  const a3 = s.byId.get(A3)!;
  expect(e3.object).toBe(true);
  expect(e3.r).toBeGreaterThan(a3.r);
  expect(a3.pending).toBe(true);
  expect(s.neighbours.get(A3)?.has(E3)).toBe(true);
});

test("фильтр приглушает, а не убирает", () => {
  const s = buildSky(base as never);
  const d = dimmed(s, { families: new Set(["object"]), pendingOnly: false });
  expect(d.has(A3)).toBe(true);
  expect(d.has(E3)).toBe(false);
  expect(s.nodes.length).toBe(31);
});

test("подписи: у объектов всегда, у атомов — у выбранного и его соседей", () => {
  const s = buildSky(base as never);
  expect(visibleLabels(s, null).has(A3)).toBe(false);
  expect(visibleLabels(s, A3).has(A3)).toBe(true);
  expect(visibleLabels(s, null).has(E3)).toBe(true);
});

test("раскладка подписей: справа, слева, под, над — без наложений, иначе прячет", () => {
  const stars = [
    { id: "a", x: 0, y: 0, r: 4, w: 60, h: 14 },
    { id: "b", x: 20, y: 0, r: 4, w: 60, h: 14 },
    { id: "c", x: 10, y: 2, r: 4, w: 60, h: 14 },
  ];
  const placed = placeLabels(stars, 2);
  const boxes = [...placed.values()].filter(Boolean);
  for (const p of boxes) for (const q of boxes) if (p !== q) expect(overlap(p!, q!)).toBe(false);
  expect(placed.get("a")?.side).toBe("right");
});

test("стрелки: ближайший сосед в направлении нажатия", () => {
  const pos = new Map([["c", { x: 0, y: 0 }], ["r", { x: 10, y: 1 }], ["l", { x: -10, y: 0 }], ["u", { x: 0, y: -10 }]]);
  const nb = new Set(["r", "l", "u"]);
  expect(arrowNeighbour("c", nb, pos, "ArrowRight")).toBe("r");
  expect(arrowNeighbour("c", nb, pos, "ArrowUp")).toBe("u");
  expect(arrowNeighbour("c", new Set(), pos, "ArrowUp")).toBeNull();
});

const overlap = (a: { x: number; y: number; w: number; h: number }, b: typeof a) =>
  a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
```

- [ ] **Step 2:** `npx vitest run src/features/sky/model.test.ts` — FAIL.
- [ ] **Step 3: Реализация** (чистые функции, без DOM):
  - `buildSky(g: GraphResult): Sky` возвращает `{ nodes, links, byId, neighbours }`. У звезды:
    - `id`, `label`, `kind`, `family`, `status`, `pending` (поле `pending` или статус `needs_review`), `object` (семья `object`), `depth`;
    - `degree` — `node.degree ?? степень по выдаче`;
    - `r` — у объекта `5 + 1.6·√degree` (не больше 14), у атома `2.6`.
  - `dimmed(sky, { families, pendingOnly })` — множество приглушённых `id`.
  - `visibleLabels(sky, selected)` — объекты, выбранная звезда и её соседи.
  - `placeLabels(items, gap)` — жадная раскладка в порядке важности (выбранная, объекты по степени, соседи). Для каждой подписи пробует стороны справа → слева → под → над. Нельзя пересекать уже поставленные подписи и чужие звёзды (квадрат `r + gap`). Не нашлось места — `null`, подпись не рисуется, звезда остаётся с подсказкой при наведении. Алгоритм как в `graph.js` эскизов, функция `free()`.
  - `arrowNeighbour(id, neighbours, positions, key)` — сосед с наименьшим `расстояние × (1 + 2·|угол отклонения|)` в полуплоскости направления; иначе `null`.
- [ ] **Step 4:** Тесты зелёные. **Step 5: Commit** `web: модель неба — звёзды, соседи, приглушение, подписи без наложений, переход стрелками`.

### Task 4: Холст неба

**Files:** Create `web/src/features/sky/colors.ts`, `SkyCanvas.tsx`, `sky.css`.

- [ ] **Step 1: Цвета.** `skyColors(el)` читает через `getComputedStyle`:
  - `--sky`, `--sky-2`, `--sky-ink`, `--sky-muted`, `--fam-source`, `--fam-work`, `--fam-object`, `--focus`;
  - цвета ни разу не пишутся литералами в JS — правило sloplint 48 из части A.

  Хук `useSkyColors(ref)` перечитывает их, когда меняется `data-theme` на `<html>` (`MutationObserver`) и `prefers-color-scheme` (`matchMedia`).
- [ ] **Step 2: `SkyCanvas`** (default export, грузится через `lazy`). Props:
  - `sky`, `selected`, `dim: Set<string>`, `colors`, `reducedMotion`;
  - события `onSelect(id|null)`, `onOpen(id)`, `onHover(id|null)`;
  - `ref` для API: `add(node, links)`, `focus(id)`, `fit()`, `screen(id)` — последний для e2e.

  Внутри — `ForceGraph()(div)`:
  - `graphData` — копии звёзд, позиции сохраняются между обновлениями по `id`;
  - `nodeCanvasObject` рисует звезду:
    - круг цвета семьи;
    - у объекта — тонкое кольцо `--sky-ink` с прозрачностью 0.5;
    - у ждущей решения — пунктирное кольцо;
    - выбранная звезда больше, с кольцом `--sky-ink`;
    - приглушённые — прозрачность 0.18;
  - `nodePointerAreaPaint` — круг `r + 4` (по маленьким звёздам легко попасть);
  - `linkColor` — `--sky-muted`; рёбра выбранной звезды ярче, приглушённые почти невидимы; `linkWidth` 1 или 1.6;
  - `onRenderFramePost(ctx, scale)` — подписи: `visibleLabels`, затем `placeLabels` в экранных координатах. Подписи рисуются шрифтом `--font` 12 px поверх, со скруглённой подложкой `--sky` прозрачностью 0.7, и зум на их размер не влияет;
  - `onNodeClick` — выбор; двойное нажатие на звезду (два клика за 300 мс по одному `id`) — `onOpen`; `onBackgroundClick` — снять выбор; двойное нажатие на фон — `zoomToFit(400, 40)`;
  - `onNodeDrag` — звезда тянется; после отпускания `fx/fy` сбрасываются, раскладка остывает;
  - `cooldownTime(1600)`. При `reducedMotion`: `warmupTicks(300)`, `cooldownTicks(0)`, без анимации зума — укладка сразу, движение только от руки;
  - `ResizeObserver` на контейнере — `width/height`;
  - при размонтировании — `_destructor()`.
- [ ] **Step 3: `add(node, links)`** — вспышка новой звезды:
  - новая звезда ставится рядом с той, о чём она (`x/y` = соседа ± 12 px);
  - `d3ReheatSimulation()` с малым `alpha` (0.3) — укладываются только её окрестности, остальное почти не двигается;
  - кольцо вспышки 600 мс: радиус `r → r+14`, прозрачность 1 → 0; при `reducedMotion` вспышки нет, звезда просто выбрана.
- [ ] **Step 4:** Модульного теста холста нет: jsdom не рисует canvas. Поведение проверяют e2e (Task 9), а логику — модель (Task 3).
- [ ] **Step 5: Commit** `web: холст неба на force-graph — звёзды по семьям, кольца, выбор и соседи, подписи без наложений, вспышка`.

### Task 5: Окно неба и панель звезды

**Files:** Create `web/src/features/sky/Sky.tsx`, `StarCard.tsx`, `bus.ts`, `Sky.test.tsx`; Modify `web/src/api/queries/index.ts` (`q.graph`), `web/src/i18n/{ru,en}.json` (раздел `sky`).

- [ ] **Step 1: Запрос** `q.graph({ ref?, depth, project?, limit })`, `staleTime` минута.
- [ ] **Step 2: Тест окна** (холст подменён `vi.mock("./SkyCanvas")` — фальшивка рисует кнопки звёзд и вызывает `onSelect`/`onOpen`):

```tsx
test("выбор звезды показывает панель; Открыть ведёт на запись; Esc снимает выбор", async () => {
  const { router } = await renderWithApp(<Sky centerRef={E3} depth={2} height={440} />, `/entity/${E3}`);
  await userEvent.click(await screen.findByRole("button", { name: "звезда Погрешность влажности В-2: ±2 %" }));
  const card = screen.getByRole("region", { name: "Выбранная звезда" });
  expect(card).toHaveTextContent("Параметр");
  expect(card).toHaveTextContent("Ждёт проверки");
  await userEvent.click(within(card).getByRole("link", { name: "Открыть" }));
  expect(decodeURIComponent(router.state.location.pathname)).toBe(`/atom/${A3}`);
});

test("глубина 1·2·3 меняет запрос; предел — честная строка", async () => {
  await renderWithApp(<Sky project="big" depth={2} height={440} />, "/");
  expect(await screen.findByText("Показано 300 звёзд из 420: объекты и самые связанные записи. Ищите или откройте объект.")).toBeInTheDocument();
});

test("клавиши: стрелки по соседям, Enter открывает, aria-live говорит, что выбрано", async () => { /* … */ });
test("пусто, загрузка и ошибка — словами", async () => { /* … */ });
```

- [ ] **Step 3: Реализация `Sky`.** Props: `centerRef?`, `project?`, `depth` (по умолчанию 2), `height`, `filter?`, `onSelect?`, `full?`.
  - **Заголовок** (поверх неба, тонкий): глубина `1 · 2 · 3` (`ToggleButtonGroup`), «3D», «Во весь экран» (`Modal` HeroUI на весь экран с тем же небом), «Вписать» (`fit`).
  - **Холст** — `lazy(() => import("./SkyCanvas"))`. Скелет — тёмный прямоугольник `--sky` той же высоты с «Загрузка».
  - **Строка о пределе** при `truncated`.
  - **Панель звезды** под небом (`StarCard`).
  - **Клавиши** на контейнере неба (`tabIndex=0`, `role="application"`, `aria-roledescription="небо записей"`, подпись «Небо: N звёзд, M связей; стрелки — по соседям, Enter — открыть»):
    - стрелки — `arrowNeighbour`, без выбора — центр или первый объект;
    - `Enter` — открыть;
    - `Esc` — снять выбор;
    - `N` — `/new?about=<ref>` (заглушка до части D);
    - `1 2 3` — глубина;
    - `F` — во весь экран.
  - **`aria-live="polite"`**: «Выбрано: Параметр «Погрешность влажности В-2: ±2 %», ждёт проверки, 3 связи».
  - **Подписка на `bus`:** событие `record-created` вызывает `canvas.add()`.
  - **Состояния:** загрузка, ошибка («Повторить»), пусто («В окрестности пока ничего нет»).
- [ ] **Step 4: `StarCard`** (`section aria-label="Выбранная звезда"`): плашка вида, статус словом, заголовок, одна строка. Строка — `snippet` из поиска по `ref` или `summary_plain` из `q.record(ref)`, лениво и только для выбранной звезды. Кнопки:
  - «Открыть» — ссылка на `recordPath`;
  - «Окрестность» — небо от этой звезды: на главной — смена центра, на странице объекта — переход на её страницу;
  - «Заметка» — `/new?about=…`.
- [ ] **Step 5: `bus.ts`** — маленький типизированный `EventTarget`: `emit("record-created", { node, links })`, `on(...)`. Регистрируется в реестре оболочки как сервис ядра, чтобы плагины могли его слушать.
- [ ] **Step 6: Commit** `web: окно неба — глубина, во весь экран, честный предел, панель звезды, клавиши и aria-live, вспышка по событию`.

### Task 6: Небо как вход

**Files:** Create `web/src/features/home/HomeSky.tsx`, `home.css`, `HomeSky.test.tsx`, `web/src/routes/records.tsx`; Modify `web/src/routes/index.tsx`, `web/src/app/shell/Folders.tsx`, `web/src/app/core-plugin.ts`, `web/e2e/shell.spec.ts`, `web/e2e/search.spec.ts`.

- [ ] **Step 1: Списки — на `/records`.** Маршрут `/records?folder=` получает бывшую главную части A (`RecordList`). Ссылки папок, «Все записи» и «Без папки» ведут туда. Команда реестра «Все записи». Тесты и e2e части A перенести на `/records`.
- [ ] **Step 2: Тест главной**:
  - итоговая строка из `base` и графа: «31 запись о 8 объектах, 3 ждут решения»;
  - плашки-фильтры: нажатие «Объекты» передаёт в холст приглушённые атомы (`aria-pressed`);
  - выбор звезды открывает карточку справа;
  - пустая база (`?project=empty`) — строка по центру и «Записать заметку»;
  - `G H` ведёт на главную.
- [ ] **Step 3: Реализация** по эскизу `v6-sky` и разд. 5.2.
  - Небо занимает всю область `main`: страница не прокручивается (`.main__in:has(> .home)` без отступов, высота 100 %).
  - Поверх, слева сверху:
    - имя базы и строка итога;
    - плашки «Из источников · Из работы · Объекты · Ждут решения» — `ToggleButton`, цвет семьи точкой, несколько сразу;
    - выбор фильтров живёт в адресе (`?f=source,work&pending=1`).
  - Справа — `StarCard` плавающей панелью, когда звезда выбрана.
  - Снизу — легенда (три семьи, кольцо объекта, пунктир «ждёт решения») и подсказки клавиш (`/ поиск · N заметка · 1 2 3 глубина · Esc снять выбор`). На телефоне легенда сворачивается в кнопку «Легенда».
  - «Окрестность» в карточке меняет центр (`?center=ref`); «Всё небо» возвращает обзор.
- [ ] **Step 4: Commit** `web: главная — небо как вход: итог, фильтры семей и «Ждут решения», карточка звезды, легенда и клавиши; списки — на /records`.

### Task 7: Небо на страницах объекта и записи

**Files:** Modify `web/src/features/card/CardPage.tsx`, `card.css`, `web/src/features/record/RecordPage.tsx`, `Widgets.tsx`, `record.css`.

- [ ] **Step 1: Объект** (разд. 4.1, FIRST VIEWPORT).
  - Две колонки на ширине от 64rem: слева карточка, справа окно неба 440 px с центром в объекте (глубина 2) и `StarCard` под ним.
  - Колонки прокручиваются сами, страница — нет, как на записи в части B.
  - Уже 64rem — небо уходит под карточку, высота 340 px.
- [ ] **Step 2: Запись** (разд. 5.6). Виджет «Окрестность» между «Связями» и «Историей»:
  - небо 340 px с центром в записи, глубина 2;
  - выбор звезды подсвечивает её и в «Связях», если связь прямая.
- [ ] **Step 3:** Тесты экранов из части B дополнить: окно неба есть (`role="application"` с подписью «Небо…»), центр — нужный `ref` (`q.graph` с нужным `ref`).
- [ ] **Step 4: Commit** `web: небо на странице объекта (справа, 440 px) и на записи (виджет «Окрестность», 340 px)`.

### Task 8: 3D по требованию

**Files:** Create `web/src/features/sky/Sky3D.tsx`; Modify `Sky.tsx`.

- [ ] **Step 1:** Переключатель «3D» в заголовке неба:
  - грузит `lazy(() => import("./Sky3D"))`;
  - те же данные, цвета, выбор и открытие;
  - подписи — только у объектов и выбранной звезды (спрайты);
  - камера облетает выбранную звезду.
- [ ] **Step 2:** Без WebGL (`!canvas.getContext("webgl2")`) кнопка неактивна, подсказка «3D недоступно в этом браузере». При `reducedMotion` облёта нет.
- [ ] **Step 3: Commit** `web: небо в 3D по переключателю — отдельным ленивым куском`.

### Task 9: e2e, доступность, бюджеты, дизайн

**Files:** Create `web/e2e/sky.spec.ts`, `web/tools/check-chunks.mjs`; Modify `web/e2e/a11y.spec.ts`, `web/.size-limit.json`, `web/vite.config.ts` (`build.manifest: true`), `web/package.json` (скрипт `chunks`), `.github/workflows/web.yml`.

- [ ] **Step 1: Ручка для e2e.** В сборке с моками (`import.meta.env.VITE_MOCK`) окно неба кладёт в `window.__amemoSky` функцию `screen(ref) → {x, y}`. В продакшене её нет.
- [ ] **Step 2: e2e:**
  - главная: небо видно, итог словами, «Объекты» приглушает атомы (проверка через `__amemoSky.dim()`);
  - нажатие на звезду по её экранным координатам — карточка; «Открыть» ведёт на запись;
  - клавиатура: фокус на небе, стрелка, Enter — запись открыта; `Esc` снимает выбор;
  - глубина `1` уменьшает число звёзд;
  - большая база — строка о пределе;
  - объект: небо справа, центр — объект;
  - запись: виджет «Окрестность»;
  - вспышка: в dev-моках событие `record-created` из консоли добавляет звезду (`__amemoSky.count()` +1);
  - телефон: небо на главной на всю ширину, легенда сворачивается.
- [ ] **Step 3: axe** на `/`, `/?center=<E3>`, `/entity/<E3>`, `/atom/<A3>` в обеих темах. Холст — `role="application"` с подписью; кнопки и карточка — обычные элементы.
- [ ] **Step 4: Бюджеты и манифест.**
  - `.size-limit.json`: `SkyCanvas-*.js` (force-graph + d3) ≤ 70 КБ gzip; `Sky3D-*.js` (three) ≤ 230 КБ; входной кусок остаётся ≤ 220 КБ.
  - `tools/check-chunks.mjs` читает `dist/.vite/manifest.json`, обходит статические `imports` входа и падает, если среди них есть `SkyCanvas`, `Sky3D`, `PdfPage`, `SourceView` или `katex`. Запуск — в `web.yml` после сборки.
- [ ] **Step 5: Дизайн.**
  - `sloplint --scope app` по всем CSS одним файлом;
  - `impeccable detect` по `/`, `/entity/…`, `/atom/…`: 0 FAIL, REFLEX исправлены;
  - снимки обеих тем сверить с `v6-sky` и `v3-object` и скопировать в папку черновиков («Часть C — снимки»).
- [ ] **Step 6:** Полный прогон как в CI:
  - `npm run lint && npm run api:check && npm run typecheck && npm test`;
  - `npm run build && npm run chunks && npm run size && npm run e2e`.
- [ ] **Step 7: Commit** `web: e2e и axe неба, бюджеты и проверка манифеста — граф не во входном куске, проход линтеров дизайна`.

### Завершение части C

- [ ] Проверка дерева на приватное — чисто.
- [ ] PR «Подпроект 5, часть C: небо — живое созвездие на главной, объекте и записи» с автослиянием. В описании — изменения контракта и что служба предупреждена.
- [ ] После слияния: память `amemo-pivot`, worktree `~/projects/amemo-web-c` убрать.

---

## Чего в части C нет (и где будет)

- **«Слои»** (пакеты, личное, скрытый слой для агента) — нужны поля `visibility` и пакет у звезды. Это часть D вместе с онтологией пакетов; фильтр в окне неба делается так, чтобы слой добавился ещё одной плашкой.
- **«Ссылки сюда» в стопке справа** у страниц источника — в части B это виджет «Ссылаются на этот файл»; на небе файл звездой не показывается, пока у объектов хранилища нет узлов в графе.
- **cosmos.gl** для больших баз — путь роста (разд. 4.4); сейчас предел 300 и обзор по проекту.

## Самопроверка плана по спецификации

- Разд. 4.4: звёзды, подписи, наведение, выбор, двойное нажатие, глубина, предел, вспышка, клавиши, живое небо, `reduced-motion`, 2D/3D — Task 3–5, 8.
- Разд. 5.2: небо как вход, итог, фильтры (приглушают, не убирают), карточка, клавиши, предел, пустая база — Task 6.
- Разд. 5.5 и FIRST VIEWPORT: небо 440 px справа на странице объекта — Task 7.
- Разд. 5.6: небо 340 px на записи, глубина 2, во весь экран — Task 5, 7. В проверке — часть E (то же окно).
- Разд. 5.13: `1 2 3`, стрелки, Enter, Esc, N — Task 5, 6.
- Разд. 9.2: граф и 3D — отдельными кусками; проверка манифеста — Task 9.
- Контракт (разд. 6): обзор без `ref`, `total`, `pending`, `degree` — Task 1.
- Имена: `buildSky`, `dimmed`, `visibleLabels`, `placeLabels`, `arrowNeighbour` (Task 3) используются в `SkyCanvas` (Task 4) и `Sky` (Task 5); `skyColors`/`useSkyColors` (Task 4) — в `SkyCanvas` и `Sky3D` (Task 8); `bus` (Task 5) слушает часть D.
