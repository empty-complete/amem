# amem — подпроект 5, часть B «Чтение»: план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Человек читает базу: страница записи как заметка (свойства, тело Markdown с формулами, источники, связи, история, похожие), панель источника с цитатой на странице файла, страница источника с превью, страница объекта с карточкой профиля, лента изменений и командная строка у поля поиска. Всё на моках контракта; правка — часть D.

**Architecture:** Новые фичи `web/src/features/{record,source,card,changes,palette}`, каждая со своими компонентами, запросами и тестами; общий код — только через `web/src/ui` и `web/src/api/queries`. Тяжёлое (pdf.js, KaTeX, CodeMirror) грузится ленивыми кусками, первая загрузка остаётся в бюджете 220 КБ. Маршруты-заглушки части A (`/atom/$ref`, `/entity/$ref`, `/changes`) заменяются экранами. Спецификация — `docs/superpowers/specs/2026-11-06-amem-subproject-5-web-ui-design.md`, разд. 5.4, 5.5, 5.8, 5.12; эскизы `v8-note`, `v9-source`, `v3-object`, `v4-notes`.

**Tech Stack:** то же, что в части A, плюс `markdown-it` 15 (рендер тела, `html: false`), `dompurify` 3 (санитайз и готовый DOM-фрагмент), `katex` 0.19 (формулы, лениво), `pdfjs-dist` 6 (страница PDF и слой текста, лениво, воркер отдельным файлом), `@codemirror/view` + `@codemirror/state` + `@codemirror/lang-markdown` 6 (исходник только для чтения, лениво), `yaml` 2 (шапка документа).

**Ветка:** `subproject-5b-reading` от `main` после слияния PR #14 (CI `web` на `127.0.0.1`). Worktree: `~/projects/amem-web-b`.

**Связь с подпроектом 4.** Службу пишет сессия «AtomDB схема и хранилище» по контракту `docs/api/http-v1.openapi.yaml`. Договорено (07.11): папка — метаданные записи `scope.folder` (не ревизия), журнал переносов, реестр пустых папок, четыре папки PARA у новой базы; пути `POST /folders`, `DELETE /folders/{path}` и событие `folder` в «Изменениях» вносит в контракт служба своим PR. Изменения контракта части B (Task 1) — этой веткой, с сообщением службе заранее.

---

## Карта файлов

| Файл | За что отвечает |
|---|---|
| `docs/api/http-v1.openapi.yaml` | Дополнения контракта (Task 1): `ObjectCitation`, `GET /objects/{id}/versions/{n}/sheet` (предел 10 000 ячеек, 413), `pages`/`sheets`/`status` у `ObjectView` |
| `web/src/features/record/doc.ts` + `doc.test.ts` | Запись ↔ документ (шапка YAML + тело Markdown): правила разд. 5.4, обе стороны |
| `web/src/features/record/markdown.ts` + `markdown.test.ts` | Рендер тела: markdown-it без HTML, `[[ссылки]]`, `$…$`/`$$…$$` → KaTeX, санитайз DOMPurify |
| `web/src/features/record/RecordPage.tsx` | Экран записи: путь, режимы, заголовок, свойства, тело, виджеты, низ |
| `web/src/features/record/Properties.tsx` | Свойства как в Obsidian (только чтение в части B) |
| `web/src/features/record/Body.tsx` | Тело: санитайзнутый DOM-фрагмент вставляется через `ref` |
| `web/src/features/record/SourceView.tsx` | Исходник записи только для чтения (CodeMirror, лениво) |
| `web/src/features/record/AgentView.tsx` | «Как видит агент»: тело `amem.atom/1` в YAML, «Скопировать JSON» |
| `web/src/features/record/LinksWidget.tsx`, `HistoryWidget.tsx`, `SimilarWidget.tsx` | Виджеты под телом |
| `web/src/features/source/quote.ts` + `quote.test.ts` | Поиск цитаты в спанах слоя текста: нормализация, разрывы строк, переносы |
| `web/src/features/source/SourcePanel.tsx` | Панель источника справа: переключатель источников, итог сверки, просмотр |
| `web/src/features/source/PdfPage.tsx` | Страница PDF с подсветкой цитаты (pdf.js, лениво) |
| `web/src/features/source/TextFragment.tsx` | Фрагмент текста версии (md, docx, xlsx как текст) с подсветкой |
| `web/src/features/source/ObjectPage.tsx`, `SheetPreview.tsx` | Страница источника: свойства, превью, «Ссылаются», «Версии», «Не разобрано» |
| `web/src/features/card/CardPage.tsx`, `CardTable.tsx`, `card.ts` + `card.test.ts` | Страница объекта: путь по `part_of`, полоса полноты, группы, состояния полей |
| `web/src/features/changes/ChangesPage.tsx`, `group.ts` + `group.test.ts` | Лента изменений по дням |
| `web/src/features/palette/CommandField.tsx` | Командная строка у поля поиска (комбобокс React Aria) |
| `web/src/routes/atom/$ref.tsx`, `entity/$ref.tsx`, `object/$id.tsx`, `changes.tsx` | Маршруты экранов |
| `web/src/mocks/fixtures/record-*.json`, `card-*.json`, `object-*.json`, `history-*.json`, `links-*.json`, `changes.json`, `similar-*.json`, `text-*.json`, `sheet-*.json`, `manual.pdf` | Образцы |
| `web/tools/make-sample-pdf.py`, `web/tools/make-fixtures-b.py` | Однократная генерация образцов |
| `web/e2e/reading.spec.ts`, `a11y.spec.ts` (дополнить) | e2e чтения, axe на новых маршрутах |

---

### Task 0: Исходная точка

- [ ] **Step 1:** `cd ~/projects/amem && git fetch origin && git worktree add ../amem-web-b -b subproject-5b-reading origin/main`
- [ ] **Step 2:** `cd ../amem-web-b/web && npm ci && npm test && npm run e2e` — всё зелёное (пришло из части A).
- [ ] **Step 3:** зависимости части B:

```bash
npm install --no-audit --no-fund markdown-it@^15 dompurify@^3 katex@^0.19 pdfjs-dist@^6 @codemirror/view@^6 @codemirror/state@^6 @codemirror/lang-markdown@^6 @codemirror/language@^6 yaml@^2
npm install --no-audit --no-fund -D @types/markdown-it@^14
```

- [ ] **Step 4: Commit** `web: зависимости части B (markdown-it, dompurify, katex, pdfjs-dist, codemirror, yaml)`.

### Task 1: Дополнения контракта

**Files:** Modify `docs/api/http-v1.openapi.yaml`, `docs/api/README.md` (раздел «Изменения»).

Перед правкой — сообщение сессии подпроекта 4 с перечнем изменений.

- [ ] **Step 1: Схема `ObjectCitation` и сведения об объекте**

```yaml
    ObjectCitation:
      type: object
      required: [record, version, selectors]
      properties:
        record: { $ref: "#/components/schemas/RefLabel" }
        version: { type: integer }
        selectors: { type: array, items: { type: object } }
        quote: { type: [string, "null"] }
        verdict: { type: string, enum: [ok, moved, fuzzy, by_locator, unresolved, not_found, no_file, no_text, external, error] }
```
В `ObjectView.cited_by` — `items: { $ref: "#/components/schemas/ObjectCitation" }`; в `ObjectView` добавить `pages: { type: [integer, "null"] }` (из кэша текста; `null`, пока текст не извлекался), `sheets: { type: [array, "null"], items: { type: string } }` (только xlsx/xlsm) и `status: { type: string, enum: [parsed, partial, skipped] }` (`object_status` библиотеки). Чего в библиотеке нет, в контракт не идёт: «бриф» — тело записи вида `source` с `about` на этот объект (UI ищет её `GET /records?about=`), «Не разобрано» UI считает сам — листы и страницы без цитат в `cited_by` при `status: partial`, «Следит» появится с плагином asearch (подпроект 6).

- [ ] **Step 2: Путь листа таблицы**

```yaml
  /objects/{id}/versions/{n}/sheet:
    get:
      tags: [objects]
      operationId: getObjectSheet
      summary: "Ячейки листа таблицы: для превью и подсветки цитируемых диапазонов"
      parameters:
        - { $ref: "#/components/parameters/ObjectId" }
        - { $ref: "#/components/parameters/VersionN" }
        - { name: name, in: query, required: true, schema: { type: string } }
        - { name: range, in: query, schema: { type: string, description: "A1:F40; по умолчанию — первые 40 строк и 12 столбцов" } }
      responses:
        "200":
          description: OK
          content:
            application/json:
              schema:
                type: object
                required: [name, range, rows]
                properties:
                  name: { type: string }
                  range: { type: string }
                  rows: { type: array, items: { type: array, items: { type: [string, number, "null"] } } }
        "413": { $ref: "#/components/responses/Problem", description: "Больше 10 000 ячеек — сузить range" }
        default: { $ref: "#/components/responses/Problem" }
```

- [ ] **Step 3:** `npx @redocly/cli@2 lint docs/api/http-v1.openapi.yaml --config docs/api/redocly.yaml` — без ошибок; `cd web && npm run api:types` — типы пересобраны.
- [ ] **Step 4: Commit** `api: ObjectCitation с местом в файле, лист таблицы для превью, сведения об объекте для страницы источника`.

### Task 2: Образцы для чтения

**Files:** Create `web/tools/make-sample-pdf.py`, `web/tools/make-fixtures-b.py`, `web/src/mocks/fixtures/manual.pdf`, `record-a3.json`, `record-a14.json`, `record-e3.json`, `card-e3.json`, `object-manual.json`, `object-sheet.json`, `text-manual-2.json`, `sheet-v2.json`, `history-a3.json`, `links-a3.json`, `similar-a3.json`, `changes.json`; Modify `web/src/mocks/handlers.ts`, `web/src/mocks/node.ts`, `web/tests/contract.test.ts`.

- [ ] **Step 1: PDF-образец**

```python
# web/tools/make-sample-pdf.py — запуск один раз из venv ядра (pymupdf есть в зависимостях amem)
import sys, fitz  # pymupdf
font = sys.argv[1] if len(sys.argv) > 1 else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
doc = fitz.open()
pages = {
    11: ["4.1 Комплект", "Метеостанция МС-1 поставляется с мачтой М-2, тремя датчиками и блоком питания 12 В."],
    12: ["4.2 Датчики",
         "Датчик температуры Т-1 измеряет температуру воздуха в диапазоне от −40 до +60 °C с погрешностью не более ±0,3 °C.",
         "При температуре ниже −40 °C показания датчика Т-1 не нормируются.",
         "Датчик влажности В-2 измеряет относительную влажность от 0 до 100 %.",
         "Погрешность ±2 % в диапазоне от 10 до 90 %, вне его погрешность не нормируется."],
}
for n, lines in pages.items():
    p = doc.new_page(width=595, height=842)
    p.insert_font(fontname="dv", fontfile=font)
    y = 72
    for i, line in enumerate(lines):
        p.insert_textbox(fitz.Rect(72, y, 523, y + 60), line, fontname="dv", fontsize=14 if i == 0 else 11)
        y += 44 if i == 0 else 40
    p.insert_text((290, 800), str(n), fontname="dv", fontsize=9)
doc.set_metadata({"title": "Руководство по эксплуатации МС-1 (образец)", "author": "amem sample"})
doc.save("src/mocks/fixtures/manual.pdf", garbage=4, deflate=True)
```
Страницы файла — 1 и 2, их подписи в документе — «11» и «12»; источники ссылаются на `page` со значением `2` и подписью `label: "12"`.

Run (из `web/`): `~/projects/amem/.venv/bin/python tools/make-sample-pdf.py`. Expected: `manual.pdf` < 30 КБ; `python -c "import fitz;print(fitz.open('src/mocks/fixtures/manual.pdf')[1].get_text()[:80])"` печатает «4.2 Датчики…».

- [ ] **Step 2: Фикстуры** — скриптом `tools/make-fixtures-b.py` из тех же данных метеостанции, что `records.json` части A (ref-ы те же):
  - `record-a3.json` — `RecordView` параметра «Погрешность влажности В-2»: `payload` (kind `parameter`, `label`, `summary_plain`, `body` с разделами «Суть источника», «Моя мысль» и формулой Магнуса `$$…$$`, `[[Нужен ли обогрев В-2 зимой?]]`, `about`, `content.values`, `tags`, `qualifiers.maturity: "🌱 росток"`), `sources` → объект руководства, версия 2, `selectors: [{type: page, value: 2, label: "12"}]`, цитата «Погрешность ±2 % в диапазоне от 10 до 90 %», `verdict: ok`; `open_items` с пунктом `semantic_doubt`;
  - `record-a14.json` — урок с двумя источниками (PDF и xlsx `B4:C9`), `basis` нет;
  - `record-n1.json` — заметка человека без источников, `basis: author`;
  - `record-e3.json` — сущность датчика;
  - `card-e3.json` — `amem.card/1` со всеми состояниями: known, conflict (два кандидата с цитатами), na, asked, missing обязательное «Рабочая температура», умолчание `60 с`, унаследованное `inherited_from` «Мачта М-2»;
  - `object-manual.json`, `object-sheet.json` — `ObjectView` с `cited_by` (место и цитата), версиями, `status`, `sheets`/`pages`, `logical_paths`; плюс `record-src-manual.json` — запись вида `source` о руководстве (бриф);
  - `text-manual-2.json` — `{pages: [...]}`; `sheet-v2.json` — лист «В-2» 10×5 как в эскизе v9;
  - `history-a3.json`, `changes.json` — события всех пяти типов за три дня, агенты `person:` и `model:`;
  - `links-a3.json` — связи в обе стороны; `similar-a3.json` — `SearchResult`.

- [ ] **Step 3: Обработчики** — `GET /records/:ref` (по ref выбирает фикстуру, иначе 404 `problem+json` «Записи … нет»), `/records/:ref/history`, `/links`, `/similar`, `/entities/:ref/card`, `/objects/:id`, `/objects/:id/versions/:n/content` (руководство — байты `manual.pdf`, `content-type: application/pdf`; остальное — 415 «Нет превью в браузере»), `/text`, `/sheet`, `/changes` (фильтры `who`, `since`).

```ts
import manualPdfUrl from "./fixtures/manual.pdf?url";
http.get("/api/v1/objects/:id/versions/:n/content", async ({ params }) => {
  if (params.id !== OBJECT_MANUAL) return problem(415, "Нет превью в браузере");
  const buf = await (await fetch(manualPdfUrl)).arrayBuffer();
  return HttpResponse.arrayBuffer(buf, { headers: { "content-type": "application/pdf" } });
}),
```
В node-тестах `?url` не работает: `node.ts` подменяет этот один обработчик, читая файл через `readFileSync`.

- [ ] **Step 4: Проверка фикстур схемами** — в `tests/contract.test.ts` по строке на файл: `RecordView`, `Card`, `ObjectView`, `ChangesResult`, `LinkView[]`, `SearchResult`. Run: `npx vitest run tests` — зелёные.

- [ ] **Step 5: Commit** `web: образцы для чтения — PDF руководства, записи, карточка, объекты, история, изменения; обработчики и проверка схемами`.

### Task 3: Документ записи (запись ↔ шапка + тело)

**Files:** Create `web/src/features/record/doc.ts`, `doc.test.ts`.

- [ ] **Step 1: Тест**

```ts
import rec from "../../mocks/fixtures/record-a3.json";
import { documentToRecord, recordToDocument } from "./doc";

test("запись → документ: шапка YAML и тело Markdown по правилам разд. 5.4", () => {
  const d = recordToDocument(rec.payload as never, rec.sources as never);
  expect(d.startsWith("---\nkind: parameter\n")).toBe(true);
  expect(d).toContain("about: [[Датчик влажности В-2]]");
  expect(d).toContain("\n---\n# Погрешность влажности В-2: ±2 %\n");
  expect(d).toContain("> Погрешность ±2 % в диапазоне от 10 до 90 %");
  expect(d).toContain("maturity: 🌱 росток");
});

test("документ → запись: заголовок, первый абзац, цитата, свои ключи, ссылки", () => {
  const p = documentToRecord(recordToDocument(rec.payload as never, rec.sources as never));
  expect(p.label).toBe("Погрешность влажности В-2: ±2 %");
  expect(p.summary_plain).toBe(rec.payload.summary_plain);
  expect(p.quote).toBe("Погрешность ±2 % в диапазоне от 10 до 90 %");
  expect(p.qualifiers).toEqual({ maturity: "🌱 росток" });
  expect(p.links).toContainEqual({ rel: "see_also", label: "Нужен ли обогрев В-2 зимой?" });
});

test("туда и обратно — тот же атом", () => {
  const once = documentToRecord(recordToDocument(rec.payload as never, rec.sources as never));
  const twice = documentToRecord(recordToDocument({ ...rec.payload, ...once } as never, rec.sources as never));
  expect(twice).toEqual(once);
});
```

- [ ] **Step 2:** `npx vitest run src/features/record/doc.test.ts` — FAIL, модуля нет.

- [ ] **Step 3: Реализация**

```ts
// doc.ts — документ записи: шапка YAML (поля и свои ключи) + тело Markdown; правила разд. 5.4.
import { parse, stringify } from "yaml";

const KNOWN = new Set(["kind", "about", "source", "page", "tags", "basis", "values", "when"]);

export interface Payload {
  kind: string; label: string; summary_plain: string; body?: string; tags?: string[]; basis?: string;
  about?: { ref?: string; label: string }[]; qualifiers?: Record<string, string>;
}
export interface Source { object_name?: string; quote?: string; selectors?: { type: string; value?: unknown; label?: string }[] }
export interface DocRecord {
  kind: string; label: string; summary_plain: string; body: string; about: string[]; tags: string[];
  basis?: string; quote?: string; source?: string; page?: string; qualifiers: Record<string, string>;
  links: { rel: "see_also"; label: string }[];
}

const wiki = (s: string) => [...s.matchAll(/\[\[([^\]]+)\]\]/g)].map((x) => x[1] as string);

export function recordToDocument(p: Payload, sources: Source[] = []): string {
  const head: Record<string, unknown> = { kind: p.kind };
  if (p.about?.length) head.about = p.about.map((a) => `[[${a.label}]]`).join(", ");
  const s = sources[0];
  if (s?.object_name) {
    head.source = s.object_name;
    const page = s.selectors?.find((x) => x.type === "page");
    if (page) head.page = page.label ?? String(page.value);
  }
  if (p.tags?.length) head.tags = p.tags;
  if (p.basis) head.basis = p.basis;
  for (const [k, v] of Object.entries(p.qualifiers ?? {})) head[k] = v;
  const yaml = stringify(head, { lineWidth: 0 }).replace(/"(\[\[[^"]+\]\])"/g, "$1");
  const quote = s?.quote ? `\n## Цитата\n> ${s.quote}\n` : "";
  return `---\n${yaml}---\n# ${p.label}\n\n${p.summary_plain}\n${quote}${p.body ? `\n${p.body}\n` : ""}`;
}

export function documentToRecord(doc: string): DocRecord {
  const m = doc.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/);
  const head = (m ? parse((m[1] ?? "").replace(/^(\w+): (\[\[.*\]\])$/gm, '$1: "$2"')) : {}) as Record<string, unknown>;
  const text = (m ? (m[2] ?? "") : doc).replace(/^\n+/, "");
  const lines = text.split("\n");
  const label = (lines[0] ?? "").replace(/^#\s+/, "").trim();
  const rest = lines.slice(1).join("\n").trim();
  const summary_plain = (rest.split(/\n\s*\n/)[0] ?? "").trim();
  const qm = rest.match(/##\s*Цитата\s*\n>\s?(.+(?:\n>\s?.+)*)/);
  const quote = qm ? (qm[1] ?? "").replace(/\n>\s?/g, " ").trim() : undefined;
  const body = rest.slice(summary_plain.length).replace(/\n?##\s*Цитата\s*\n(>.*\n?)+/, "").trim();
  const qualifiers: Record<string, string> = {};
  for (const [k, v] of Object.entries(head)) if (!KNOWN.has(k)) qualifiers[k] = String(v);
  return {
    kind: String(head.kind ?? "note"), label, summary_plain, body, about: wiki(String(head.about ?? "")),
    tags: Array.isArray(head.tags) ? head.tags.map(String) : [], basis: head.basis ? String(head.basis) : undefined,
    quote, source: head.source ? String(head.source) : undefined, page: head.page ? String(head.page) : undefined,
    qualifiers, links: wiki(body).map((l) => ({ rel: "see_also" as const, label: l })),
  };
}
```

- [ ] **Step 4:** тест зелёный (при расхождении — править реализацию, не ожидания: ожидания — это правила спецификации). **Step 5: Commit** `web: запись ↔ документ (шапка YAML + тело Markdown) по правилам разд. 5.4`.

### Task 4: Рендер тела

**Files:** Create `web/src/features/record/markdown.ts`, `markdown.test.ts`, `Body.tsx`, `record.css`.

- [ ] **Step 1: Тест**

```ts
import { renderMarkdown } from "./markdown";

const html = async (src: string, resolve?: (l: string) => string) => {
  const host = document.createElement("div");
  host.replaceChildren(await renderMarkdown(src, resolve));
  return host.innerHTML;
};

test("HTML в тексте не исполняется и не попадает в DOM", async () => {
  const out = await html("<img src=x onerror=alert(1)> **жирно**");
  expect(out).not.toContain("<img");
  expect(out).toContain("<strong>жирно</strong>");
});
test("[[ссылка]] — ссылка на запись по подписи", async () => {
  const out = await html("см. [[Нужен ли обогрев В-2 зимой?]]", (l) => `/ui/search?q=${encodeURIComponent(l)}`);
  expect(out).toMatch(/<a class="wiki" href="\/ui\/search\?q=[^"]+">Нужен ли обогрев В-2 зимой\?<\/a>/);
});
test("формулы: строчная и выключная через KaTeX", async () => {
  const out = await html("при $T = 2$ °C\n\n$$T_d = \\frac{b\\gamma}{a-\\gamma}$$");
  expect(out).toContain('class="katex"');
  expect(out).toContain('class="katex-display"');
});
test("цитата блоком получает класс источника", async () => {
  expect(await html("> цитата")).toContain('<blockquote class="quote">');
});
```

- [ ] **Step 2:** FAIL. **Step 3: Реализация** — `renderMarkdown(src, resolve): Promise<DocumentFragment>`:
  - `markdown-it` с `html: false, linkify: false, typographer: false`;
  - своё правило `inline` для `[[…]]` (токен `wiki_link`, рендер `<a class="wiki" href="${resolve(label)}">` с экранированием подписи `md.utils.escapeHtml`);
  - правило `inline` для `$…$` и `block` для строки `$$…$$` (токены `math_inline` / `math_block`, рендер `katex.renderToString(src, { displayMode, throwOnError: false, output: "htmlAndMathml" })`); KaTeX подгружается `await import("katex")` только если в тексте есть `$`;
  - `blockquote_open` рендерит `<blockquote class="quote">`;
  - итог: `DOMPurify.sanitize(htmlString, { RETURN_DOM_FRAGMENT: true, ADD_TAGS: ["math", "semantics", "annotation", "mrow", "mi", "mo", "mn", "msub", "msup", "mfrac", "msqrt", "mspace", "mtext"], ADD_ATTR: ["aria-hidden", "encoding"] })` — функция возвращает уже очищенный DOM-фрагмент, HTML-строка наружу не выходит.

  `Body.tsx`: `const ref = useRef<HTMLDivElement>(null)`; в `useEffect` — `renderMarkdown(body, resolve).then((frag) => ref.current?.replaceChildren(frag))` с отменой при смене тела; `<div ref={ref} className="prose" />`; клик по `a.wiki` перехватывается делегированием и идёт через `navigate`. CSS KaTeX (`katex/dist/katex.min.css`) импортируется в том же ленивом модуле, что и KaTeX. Стили `.prose`, `.quote`, `.wiki` — из эскиза v8 в `record.css`.

- [ ] **Step 4:** зелёный. **Step 5: Commit** `web: рендер тела — markdown-it без HTML, [[ссылки]], формулы KaTeX лениво, DOM-фрагмент DOMPurify`.

### Task 5: Страница записи

**Files:** Create `web/src/features/record/RecordPage.tsx`, `Properties.tsx`, `LinksWidget.tsx`, `HistoryWidget.tsx`, `SimilarWidget.tsx`, `SourceView.tsx`, `AgentView.tsx`, `RecordPage.test.tsx`; Modify `web/src/routes/atom/$ref.tsx`, `web/src/api/queries/index.ts`, `web/src/i18n/{ru,en}.json`.

- [ ] **Step 1: Запросы** — `q.record(ref)`, `q.history(ref)`, `q.links(ref)`, `q.similar(ref)` по образцу части A.
- [ ] **Step 2: Тест экрана**

```tsx
test("запись: путь, заголовок, свойства, тело, источники, связи; технические поля скрыты", async () => {
  await renderWithApp(<RecordPage recordRef={A3} view="human" />, `/atom/${A3}`);
  expect(await screen.findByRole("heading", { level: 1, name: "Погрешность влажности В-2: ±2 %" })).toBeInTheDocument();
  expect(screen.getByRole("navigation", { name: "О чём" })).toHaveTextContent("Датчик влажности В-2");
  expect(screen.getByRole("term", { name: "Вид" }).nextElementSibling).toHaveTextContent("Параметр");
  expect(screen.getByText("±2 %")).toBeInTheDocument();
  expect(screen.getByText(/Ждёт решения: модель сомневается/)).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Связи" })).toHaveTextContent("см. также");
  expect(screen.queryByText(/sha256-c1:/)).not.toBeInTheDocument();
});
test("исходник — шапка и тело текстом, только чтение", async () => {
  await renderWithApp(<RecordPage recordRef={A3} view="source" />, `/atom/${A3}?view=source`);
  expect(await screen.findByLabelText("Исходник записи")).toHaveTextContent("kind: parameter");
});
test("как видит агент — тело amem.atom/1 с content_hash", async () => {
  await renderWithApp(<RecordPage recordRef={A3} view="agent" />, `/atom/${A3}?view=agent`);
  expect(await screen.findByText(/content_hash:/)).toBeInTheDocument();
});
test("заметка человека без источника — «Основание: ваше слово»", async () => {
  await renderWithApp(<RecordPage recordRef={N1} view="human" />, `/atom/${N1}`);
  expect(await screen.findByText(/Основание: слово автора/)).toBeInTheDocument();
});
test("нет записи — 404 словами", async () => {
  await renderWithApp(<RecordPage recordRef="atm:нет" view="human" />, "/atom/atm:нет");
  expect(await screen.findByRole("alert")).toHaveTextContent("Записи atm:нет нет");
});
```

- [ ] **Step 3: Реализация** по эскизу `v8-note` и разд. 5.4:
  - строка пути: `about` записи и цепочка `part_of` (ссылки на `/entity/$ref`), `nav` с `aria-label="О чём"`; справа статус словом, карандаш неактивен с подсказкой «Правка — в части D», кнопка исходника (`?view=source`), «⋯» (`Dropdown` HeroUI: «Как видит агент» → `?view=agent`, «Скопировать ссылку atm:…», «Скопировать как Markdown»);
  - `h1` — `label`; строка «Ждёт решения: …» под ним, если есть `open_items` (ссылка на `/review/$itemId`, заглушка до части E);
  - `Properties` — `<dl>` строк «значок типа · имя · значение» только для заполненных: Вид (плашка семьи и пакет), О чём (плашки-ссылки), Значения (`content.values`: величина, число, единица, табличные цифры; значение параметра ещё и крупно над телом), Когда, Теги, Основание словами, свои ключи `qualifiers`, Записал (агент; кто подтвердил — из истории), уверенность модели;
  - тело — `Body`;
  - виджеты: «Источники» (тип файла плашкой, имя, версия, место, цитата, итог сверки; нажатие выбирает источник в панели справа), `LinksWidget` (`section` с `aria-label="Связи"`, исходящие и обратные), «История» и «Похожие» под раскрытиями (`Disclosure` HeroUI);
  - низ: кто и когда, ревизия, `atm:` моноширинно;
  - справа — `SourcePanel` (Task 6); обе колонки прокручиваются сами, страница — нет.

  `SourceView.tsx` — `React.lazy`: CodeMirror `EditorView` с `EditorState.readOnly.of(true)`, `EditorView.editable.of(false)`, `markdown()`, текст — `recordToDocument(payload, sources)`, `aria-label="Исходник записи"`. `AgentView.tsx` — `stringify(payload)` из `yaml` в `<pre>`, «Скопировать JSON» (`navigator.clipboard.writeText` в `try/catch`, «Скопировано» в `aria-live`).

  Маршрут `atom/$ref.tsx`: `validateSearch: z.object({ view: z.enum(["human", "source", "agent"]).catch("human") })`.

- [ ] **Step 4:** тесты зелёные; `npm run dev:mock`, `/ui/atom/<ref a3>` сверить с эскизом v8 в обеих темах.
- [ ] **Step 5: Commit** `web: страница записи — путь, свойства, тело, источники, связи, история, похожие; исходник и вид для агента`.

### Task 6: Панель источника и подсветка цитаты

**Files:** Create `web/src/features/source/quote.ts`, `quote.test.ts`, `SourcePanel.tsx`, `PdfPage.tsx`, `TextFragment.tsx`, `source.css`, `SourcePanel.test.tsx`.

- [ ] **Step 1: Тест поиска цитаты в спанах**

```ts
import { findQuote, normalize } from "./quote";

test("нормализация: пробелы, неразрывные пробелы, переносы, кавычки, минусы", () => {
  expect(normalize("от −40 до +60 °C")).toBe(normalize("от -40 до +60 °C"));
  expect(normalize("погреш-\nность")).toBe("погрешность");
});
test("цитата через несколько спанов — начало и конец по спанам", () => {
  const spans = ["Датчик влажности В-2 измеряет относительную влажность от 0 до 100 %.", "Погрешность ±2 % в диапазоне", " от 10 до 90 %, вне его погрешность не нормируется."];
  expect(findQuote(spans, "Погрешность ±2 % в диапазоне от 10 до 90 %")).toEqual({ start: { span: 1, offset: 0 }, end: { span: 2, offset: 14 } });
});
test("цитаты нет — null", () => {
  expect(findQuote(["совсем другой текст"], "Погрешность ±2 %")).toBeNull();
});
```

- [ ] **Step 2:** FAIL. **Step 3: Реализация**
  - `normalize`: NFKC, `−–—` → `-`, `«»„“”` → `"`, перенос `-\n` убрать, любые пробелы → один, trim, нижний регистр;
  - `findQuote(spans, quote)`: нормализовать каждый спан с картой «позиция в склейке → (спан, смещение в исходном спане)», склеить, `indexOf` нормализованной цитаты, вернуть начало и конец (конец — исключительно) по карте; `null`, если не найдено;
  - `PdfPage.tsx` (лениво): `GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString()`; `getDocument({ url, rangeChunkSize: 65536 })` → `getPage(n)` → `getViewport({ scale })` по ширине панели → `page.render({ canvas, viewport }).promise` → `new TextLayer({ textContentSource: page.streamTextContent(), container, viewport }).render()` → `findQuote` по текстам спанов слоя → обернуть найденные части в `<mark>` (разбивая текстовые узлы по смещениям) → прокрутить к первой; цитаты нет — строка «Цитату на странице найти не удалось» над страницей; смена источника отменяет рендер (`RenderingCancelledException` молча);
  - `TextFragment.tsx`: `GET …/text?page` → абзацы, подсветка тем же `findQuote` (спаны = абзацы);
  - `SourcePanel.tsx`: шапка (тип, имя, «страница 12», «версия файла 2», итог сверки словами со значком: ok — «Цитата найдена», fuzzy — «Найдена приблизительно», by_locator — «Место не подтверждено», no_file — «Файла нет в хранилище», no_text — «В файле нет текста», остальные — словами из i18n), переключатель «1 · 2 · 3» для нескольких источников (`ToggleButtonGroup` HeroUI), просмотр по `media_type` (PDF → `PdfPage`, текстовые и офисные → `TextFragment`, сайт — адрес и цитата, переписка — тема и цитата); низ — «Страница источника» (`/object/$id`) и «Открыть файл» (новая вкладка на `…/content`); без источников и с `basis` — «Основание: слово автора / умолчание методики / допущение».

- [ ] **Step 4: Тест панели** (jsdom не рисует canvas — `PdfPage` подменяется `vi.mock`): итог сверки словами, переключатель меняет шапку, `basis: author` без источников — строка основания.
- [ ] **Step 5:** вживую — цитата подсвечена на странице «12» образца в обеих темах.
- [ ] **Step 6: Commit** `web: панель источника — PDF страницей с подсветкой цитаты (pdf.js лениво), текстовый фрагмент, итог сверки словами`.

### Task 7: Страница источника

**Files:** Create `web/src/features/source/ObjectPage.tsx`, `SheetPreview.tsx`, `ObjectPage.test.tsx`, `web/src/routes/object/$id.tsx`.

- [ ] **Step 1: Тест**

```tsx
test("источник-таблица: свойства, превью листа с цитируемым диапазоном, ссылки сюда", async () => {
  await renderWithApp(<ObjectPage objectId={SHEET} />, `/object/${SHEET}`);
  expect(await screen.findByRole("heading", { level: 1, name: /Наблюдения, ноябрь/ })).toBeInTheDocument();
  expect(screen.getByText("~/Документы/Метео/Наблюдения_ноябрь.xlsx")).toBeInTheDocument();
  expect(screen.getByRole("table", { name: "Лист В-2" })).toBeInTheDocument();
  expect(screen.getAllByRole("cell", { name: "87" })[0]).toHaveAttribute("data-cited", "true");
  expect(screen.getByRole("region", { name: "Ссылаются на этот файл" })).toHaveTextContent("лист В-2, B4:C9");
});
test("«Скопировать путь» пишет в буфер и говорит об этом", async () => {
  const write = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText: write } });
  await renderWithApp(<ObjectPage objectId={SHEET} />, `/object/${SHEET}`);
  await userEvent.click(await screen.findByRole("button", { name: "Скопировать путь" }));
  expect(write).toHaveBeenCalledWith("~/Документы/Метео/Наблюдения_ноябрь.xlsx");
  expect(screen.getByRole("status")).toHaveTextContent("Путь скопирован");
});
```

- [ ] **Step 2:** FAIL. **Step 3: Реализация** по эскизу `v9-source` и разд. 5.12: заголовок с типом файла, свойства (вид, путь `logical_paths[0]` и «Скопировать путь» — «Показать в папке» появится, когда служба отдаст путь для этого; версия с датой и размером; листы или страницы; о чём; теги), бриф (тело записи вида `source` об этом объекте через `Body`, если она есть); превью: PDF — `PdfPage` со всеми цитатами страницы; таблица — `SheetPreview` (вкладки листов, `GET …/sheet`, ячейки из `cited_by[].selectors` с `type: range` получают `data-cited` и подсветку `--mark-2`, подпись снизу «B4:C9 цитирует <запись>»); картинка — `<img>` с `alt`; виджеты: «Ссылаются на этот файл» (`section aria-label`; плашка вида, заголовок, место), «Версии» (номер, дата, размер, «N записей сверены»), «Не разобрано» (листы и страницы без цитат при `status: partial`; «Попросить агента» неактивна до части D с подсказкой).
- [ ] **Step 4:** зелёный. **Step 5: Commit** `web: страница источника — свойства и путь, превью PDF и листа с цитируемыми ячейками, ссылки сюда, версии, не разобрано`.

### Task 8: Страница объекта и карточка

**Files:** Create `web/src/features/card/card.ts`, `card.test.ts`, `CardPage.tsx`, `CardTable.tsx`, `card.css`, `CardPage.test.tsx`; Modify `web/src/routes/entity/$ref.tsx`, `web/src/i18n/{ru,en}.json`.

- [ ] **Step 1: Тест сводки**

```ts
import card from "../../mocks/fixtures/card-e3.json";
import { summarize } from "./card";

test("полоса полноты и строка итога из amem.card/1", () => {
  const s = summarize(card as never);
  expect(s.parts).toEqual({ known: 2, conflict: 1, asked: 1, missing: 1, na: 1 });
  expect(s.blockers).toEqual(["Рабочая температура"]);
});
test("группы по профилю в порядке правил", () => {
  expect(summarize(card as never).groups.map((g) => g.name)).toEqual(["Измерение", "Условия", "Опрос"]);
});
```
Текст итога («Известно 2 из 6. Одно расхождение, один открытый вопрос, нет обязательного: рабочая температура.») собирается в компоненте через i18next с множественными формами; его проверяет тест экрана.

- [ ] **Step 2:** FAIL. **Step 3: Реализация** — `summarize(card)`: счёт по `state`, блокеры (`required` и не `known`/`na`), группы в порядке полей. `CardPage` по эскизам `v3-object` и `v4-notes`: путь по `ancestors`, `h1`, класс плашкой, профиль словами, полоса полноты (`role="img"`, `aria-label` = текст итога), строка итога; `CardTable` — сгруппированные списки: имя параметра, подпись (источник и страница / «Ждёт решения: …» / «Где искать: …» из `hint` / «Вы спросили …» / «из: …» для `inherited_from`), справа значение с единицей и статус значком; состояния: known; conflict («2 значения» со значком внимания, нажатие раскрывает кандидатов с цитатами); na («Не применяется»); asked («Вопрос открыт»); missing («Нет данных», обязательное — «Нужно» словом и цветом `--danger`); умолчание серым «по умолчанию 60 с» (без «Принять» до части D). Вкладки «Карточка», «Атомы» (`GET /graph?depth=1` → список записей `about`), «История». Без профиля — сразу «Атомы».
- [ ] **Step 4: Тест экрана** — все пять состояний словами; «Нужно» у обязательного пустого; раскрытие расхождения показывает обе цитаты; строка итога целиком.
- [ ] **Step 5: Commit** `web: страница объекта — путь по part_of, полоса полноты, карточка профиля со всеми состояниями, атомы, история`.

### Task 9: Лента изменений

**Files:** Create `web/src/features/changes/group.ts`, `group.test.ts`, `ChangesPage.tsx`, `ChangesPage.test.tsx`; Modify `web/src/routes/changes.tsx`.

- [ ] **Step 1: Тест группировки**

```ts
import { groupByDay } from "./group";
test("события по дням: Сегодня, Вчера, дата", () => {
  const now = new Date("2026-11-07T12:00:00Z");
  const g = groupByDay([{ at: "2026-11-07T09:00:00Z" }, { at: "2026-11-06T20:00:00Z" }, { at: "2026-11-04T08:00:00Z" }] as never, now, "ru");
  expect(g.map((x) => x.title)).toEqual(["Сегодня", "Вчера", "4 ноября"]);
});
```

- [ ] **Step 2–3:** `groupByDay` (локальная дата, `Intl.DateTimeFormat` с `day` и `month: "long"`), `ChangesPage`: фильтры «Все · Люди · Агенты» (`?who=`) и «7 дней · 30 дней · всё» (`?since=`), строки: время, событие словами (новая ревизия, решение проверки, смена статуса, связь добавлена, связь снята; `folder` — «перенесено в папку», когда служба его добавит), заголовок записи ссылкой, кто; пусто — «Изменений за выбранный срок нет».
- [ ] **Step 4: Commit** `web: лента изменений по дням с фильтрами «кто» и «срок»`.

### Task 10: Командная строка у поля поиска

**Files:** Create `web/src/features/palette/CommandField.tsx`, `CommandField.test.tsx`; Modify `web/src/app/shell/TopBar.tsx`.

- [ ] **Step 1: Тест**

```tsx
test("список: записи по запросу и команды реестра; Enter без выбора — результаты", async () => {
  const { router } = await renderWithApp(<CommandField />);
  const box = screen.getByRole("combobox", { name: "Поиск по базе" });
  await userEvent.type(box, "погрешность");
  expect(await screen.findByRole("option", { name: /Погрешность влажности В-2/ })).toBeInTheDocument();
  await userEvent.clear(box);
  await userEvent.type(box, "проверк");
  expect(await screen.findByRole("option", { name: "Открыть проверку" })).toBeInTheDocument();
  await userEvent.keyboard("{Escape}");
  await userEvent.type(box, "{Enter}");
  expect(router.state.location.pathname).toBe("/search");
});
```
`renderWithApp` возвращает и `router` (дополнить хелпер части A).

- [ ] **Step 2–3:** `ComboBox` из `react-aria-components` (вид и разметку сверить с HeroUI: `node ~/.claude/skills/heroui-react/scripts/get_component_docs.mjs ComboBox Autocomplete`); источник — `registry.dataSources.get("amem.records")` с задержкой 150 мс, до 6 записей, затем команды реестра по совпадению названия; выбор записи — её страница, команды — `run({ navigate })`; Enter без выбора — `/search?q=…`. Поле верхней строки заменяется этим компонентом; `⌘K` и `/` фокусируют его.
- [ ] **Step 4: Commit** `web: командная строка у поля поиска — записи и команды реестра`.

### Task 11: e2e, доступность, бюджеты, дизайн

**Files:** Create `web/e2e/reading.spec.ts`; Modify `web/e2e/a11y.spec.ts`, `web/.size-limit.json`.

- [ ] **Step 1: e2e** — поиск «погрешность» → первая строка → страница записи: заголовок, свойства, тело с формулой (`.katex`), панель источника с подсветкой на PDF (`mark` в слое текста); `?view=source` и `?view=agent`; «Датчик влажности В-2» → объект: полоса полноты, «Нужно», раскрытие расхождения; источник из записи → страница источника, таблица с `data-cited`; «Изменения» → группы дней и фильтр «Люди»; командная строка `⌘K`.
- [ ] **Step 2: axe** на `/atom/<a3>`, `/atom/<a3>?view=source`, `/atom/<n1>`, `/entity/<e3>`, `/object/<sheet>`, `/object/<manual>`, `/changes` в обеих темах — без serious/critical.
- [ ] **Step 3: Бюджеты** — в `.size-limit.json` ленивые куски отдельными строками: pdf.js (≤ 450 КБ gzip, воркер — отдельный файл, грузится только на страницах с PDF), KaTeX (≤ 90 КБ), CodeMirror (≤ 160 КБ); входной кусок остаётся ≤ 220 КБ — новые библиотеки в него не попадают.
- [ ] **Step 4: Дизайн** — `sloplint --scope app` по всем CSS части (склеенным одним файлом, как в части A) и `impeccable detect` по `/atom/…`, `/entity/…`, `/object/…`, `/changes`: 0 FAIL, REFLEX исправлены или сняты с причиной; снимки сверить с эскизами v8, v9, v3/v4.
- [ ] **Step 5:** полный прогон как в CI: `npm run lint && npm run api:check && npm run typecheck && npm test && npm run build && npm run size && npm run e2e`.
- [ ] **Step 6: Commit** `web: e2e и axe чтения, бюджеты ленивых кусков, проход линтеров дизайна`.

### Завершение части B

- [ ] Проверка дерева на приватное (названия, пути, адреса) — чисто.
- [ ] PR в `empty-complete/amem` «Подпроект 5, часть B: чтение — запись как заметка, источник с цитатой на странице, страница источника, карточка объекта, изменения, командная строка» с автослиянием (`gh pr merge --merge --auto`); в описании — дополнения контракта (Task 1) и что служба предупреждена.
- [ ] После слияния: память `amem-pivot` (часть B слита); worktree `~/projects/amem-web-b` убрать.

---

## Самопроверка плана по спецификации

- Разд. 5.4 (запись как в Obsidian, исходник, вид для агента, правила перевода) — Task 3, 4, 5; правка и карандаш — часть D.
- Разд. 5.5 (сущность, карточка, состояния, полоса полноты, вкладки) — Task 8; небо справа — часть C.
- Разд. 5.8 (изменения) — Task 9. Разд. 5.1 (командная строка) — Task 10.
- Разд. 5.12 (страница источника, превью, путь, версии, не разобрано) — Task 7; «Показать в папке» и «Попросить агента» — после пути службы и части D.
- Разд. 4.3 (минимализм: технические поля только в «Как видит агент», одна заполненная кнопка, состояния словами) — Task 5, 8; разд. 9 (доступность, бюджеты, ленивые куски) — Task 11.
- Контракт (разд. 6) — Task 1 дополняет `ObjectView` и лист таблицы; папки и события `folder` вносит служба.
- Безопасность тела: HTML из Markdown не исполняется (`html: false`), DOMPurify возвращает DOM-фрагмент, вставка через `ref.replaceChildren` (Task 4).
- Имена: `recordToDocument`/`documentToRecord` (Task 3) — в `SourceView` (Task 5) и части D; `findQuote`/`normalize` (Task 6) — в `PdfPage`, `TextFragment`, `SheetPreview` (Task 7); `summarize` (Task 8) — в `CardPage`; `renderMarkdown` (Task 4) — в `Body` (Task 5, 7).
