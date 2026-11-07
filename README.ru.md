<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/banner-dark.svg">
    <img alt="amem — another memory" src="docs/assets/readme/banner-light.svg" width="100%">
  </picture>
</p>

<h3 align="center">Общая память людей и ИИ-агентов, где у каждого утверждения есть доказательство.</h3>

<p align="center">
  Открытая база знаний из небольших утверждений с источниками. Агенты предлагают, автопроверка
  находит цитату в самом файле, а последнее слово остаётся за человеком.
</p>

<p align="center">
  <a href="https://github.com/empty-complete/amem/actions/workflows/ci.yml"><img alt="Тесты" src="https://img.shields.io/github/actions/workflow/status/empty-complete/amem/ci.yml?branch=main&label=tests&style=flat-square"></a>
  <a href="https://github.com/empty-complete/amem/actions/workflows/web.yml"><img alt="Веб-UI" src="https://img.shields.io/github/actions/workflow/status/empty-complete/amem/web.yml?branch=main&label=web%20ui&style=flat-square"></a>
  <a href="LICENSE.txt"><img alt="Лицензия MIT" src="https://img.shields.io/badge/license-MIT-2a78d6?style=flat-square"></a>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-3776ab?style=flat-square&logo=python&logoColor=white">
  <img alt="PostgreSQL 16+ с pgvector" src="https://img.shields.io/badge/PostgreSQL-16%2B%20%C2%B7%20pgvector-4169e1?style=flat-square&logo=postgresql&logoColor=white">
  <img alt="Состояние: ранняя разработка" src="https://img.shields.io/badge/status-early%20development-eb6834?style=flat-square">
</p>

<p align="center">
  <a href="#быстрый-старт"><b>Быстрый старт</b></a> ·
  <a href="#возможности"><b>Возможности</b></a> ·
  <a href="#как-это-устроено"><b>Как устроено</b></a> ·
  <a href="#дорожная-карта"><b>Дорожная карта</b></a> ·
  <a href="docs/library.ru.md"><b>Документация</b></a> ·
  <a href="docs/MANIFESTO.ru.md"><b>Манифест</b></a> ·
  <a href="README.md"><b>English</b></a>
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/ru/sky-dark.svg">
    <img alt="Небо: вся память как созвездие атомов и объектов (заглушка)" src="docs/assets/readme/ru/sky-light.svg" width="100%">
  </picture>
</p>

> [!IMPORTANT]
> **amem в ранней разработке.** Библиотека ядра уже работает: хранилище с ревизиями, гибридный поиск,
> автопроверка, очередь проверки, карточки сущностей, подборки и бэкапы. Всё это проверяется в CI
> на PostgreSQL 18 и 16. Служба, CLI, сервер MCP и веб-UI сейчас в работе. Пока они не вышли,
> картинки на этой странице — заглушки.

## Зачем amem

Агенты забывают всё между сессиями, а то, что помнят, — текст без доказательств. Заметки и вики хранят,
что написали люди, но не откуда это взялось и кто решил, что это верно.

amem хранит единицу поменьше и понадёжнее — **атом**. Атом — это одно утверждение, точное место в файле,
откуда оно взято, вся история его правок и решение человека.

<table>
  <tr>
    <td width="50%" valign="top">
      <b>У каждого утверждения есть источник</b><br>
      Цитата сверяется с настоящим текстом файла: страница PDF, раздел Markdown, диапазон ячеек
      таблицы.
    </td>
    <td width="50%" valign="top">
      <b>Ничто не перезаписывается</b><br>
      Каждая правка — новая ревизия с причиной, автором и хэшем содержимого. Ошибку не стирают,
      а заменяют.
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <b>Проверка — при каждой записи</b><br>
      Схема, единицы, цитата, здравый смысл и дубли проверяются до того, как запись попадёт в базу.
      Отклонённый пакет не пишет ничего.
    </td>
    <td width="50%" valign="top">
      <b>Решает человек</b><br>
      Агенты предлагают и предварительно проверяют. Принять утверждение в канон решает человек,
      и система показывает, кто именно.
    </td>
  </tr>
</table>

## Возможности

<table>
  <tr>
    <td width="50%" valign="top">
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/ru/record-dark.svg">
        <img alt="Страница записи с цитатой, подсвеченной на странице источника (заглушка)" src="docs/assets/readme/ru/record-light.svg">
      </picture>
      <h3>Утверждение рядом с источником</h3>
      Запись читается как заметка: свойства, тело в Markdown и цитата, подсвеченная на настоящей странице
      файла. Процитированные файлы хранятся один раз по хэшу содержимого и не пропадают.
    </td>
    <td width="50%" valign="top">
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/ru/review-dark.svg">
        <img alt="Очередь проверки: утверждение, цитата и кнопки решения (заглушка)" src="docs/assets/readme/ru/review-light.svg">
      </picture>
      <h3>Проверка одним нажатием</h3>
      Всё сомнительное, рискованное или изменившееся попадает в очередь. В пункте — утверждение, цитата
      и соседи. <kbd>Y</kbd> — подтвердить, <kbd>N</kbd> — отклонить, <kbd>J</kbd>/<kbd>K</kbd> — дальше;
      двум проверяющим один пункт не достанется.
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/ru/card-dark.svg">
        <img alt="Карточка сущности: полнота и параметры по группам (заглушка)" src="docs/assets/readme/ru/card-light.svg">
      </picture>
      <h3>Карточка объекта</h3>
      Профиль говорит, какие параметры нужны объекту. Карточка показывает, что известно, чего нет и где
      расхождение. Она собирается из атомов на лету, поэтому не устаревает.
    </td>
    <td width="50%" valign="top">
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/ru/agent-dark.svg">
        <img alt="Сессия агента: поиск в amem, чтение записей и отметка того, что помогло (заглушка)" src="docs/assets/readme/ru/agent-light.svg">
      </picture>
      <h3>Память для агентов</h3>
      Claude Code и Codex сначала спрашивают amem. Они читают короткие карточки, берут только нужные
      записи и отмечают, что помогло, — это дешевле по токенам, чем читать сырые файлы.
      <i>Появится вместе с сервером MCP.</i>
    </td>
  </tr>
</table>

**Под капотом**

- **Гибридный поиск.** Точные коды, полнотекст и локальные векторы сливаются через RRF. Точный код
  всегда первый, а неоднозначный запрос возвращает всех кандидатов, а не догадку.
- **История, которую можно спросить.** Тела хранятся как канонический JSON (JCS) с хэшем `sha256-c1:`,
  а `what_changed` отвечает на «что изменилось с понедельника» по одной записи или по всей базе.
- **Файлы никуда не денутся.** Источники лежат в хранилище OCFL по хэшу содержимого. Когда приходит
  новая версия файла, каждая запись со ссылкой на старую версию получает пункт проверки.
- **Пакеты домена.** Словари, шаблоны и профили сущностей — подключаемые пакеты с версиями
  и зависимостями. Само ядро — тоже пакет.
- **Подборки.** Ветку знаний можно передать из базы в базу папкой или zip-архивом, с файлами или без.
  Идентификаторы сохраняются, а всё, что расходится с местной копией, идёт на проверку.
- **Бэкап с доказательством.** Бэкап — это `pg_dump` и снимок хранилища объектов. Он проверяется
  настоящим пробным восстановлением во временную базу.
- **Скучное хранилище.** Данные лежат в обычном PostgreSQL 16+ с pgvector. Схема описана на LinkML,
  из неё генерируются модели Pydantic и JSON Schema.

## Быстрый старт

Нужны Python 3.11+, Docker (для PostgreSQL) и Linux или macOS. В Windows — через WSL2.

**1. Запустите PostgreSQL и поставьте библиотеку**

```bash
git clone https://github.com/empty-complete/amem.git
cd amem
docker compose up -d --wait db      # PostgreSQL 18 + pgvector на 127.0.0.1:5435
python3 -m venv .venv
.venv/bin/pip install -e .          # или -e ".[embed]" для локальных многоязычных векторов
```

**2. Запишите факт с источником**

```python
from pathlib import Path

from amem import check, db, recipes
from amem.check import Proposal
from amem.ocfl_store import ObjectStore

conn = db.connect("postgresql://amem:amem@127.0.0.1:5435/amem")
db.prepare(conn)                                  # миграции и словарь ядра

docs = Path("my-docs")                            # папка с файлами-источниками
store = ObjectStore(Path("amem-objects"))         # копии процитированных файлов по хэшу
(docs / "pgvector").mkdir(parents=True, exist_ok=True)
(docs / "pgvector" / "README.md").write_text(
    "## HNSW\n\nvector - up to 2,000 dimensions, halfvec - up to 4,000 dimensions\n")

fact = {
    "kind": "fact",
    "label": {"en": "pgvector indexes vector with HNSW up to 2,000 dimensions",
              "ru": "pgvector: индекс HNSW по vector — до 2000 измерений"},
    "summary_plain": {"en": "Longer embeddings need halfvec, up to 4,000.",
                      "ru": "Длинные векторы индексируются через halfvec, до 4000."},
    "sources": [{"path": "pgvector/README.md",
                 "selectors": [{"type": "heading", "value": "HNSW"}],
                 "quote": "vector - up to 2,000 dimensions"}],
}
result = check.submit(conn, store, docs, [Proposal("atom", fact)], agent="model:my-agent")
print(result.state, result.records[0]["status"])  # approved draft
```

Уровни 1–4 пройдены, файл скопирован в хранилище. Атом остаётся `draft`, пока его не подтвердит смысловая
проверка (уровень 5) или человек.

**3. Попробуйте процитировать то, чего в файле нет**

```python
wrong = {**fact, "sources": [{**fact["sources"][0], "quote": "vector - up to 16,000 dimensions"}]}
result = check.submit(conn, store, docs, [Proposal("atom", wrong)], agent="model:my-agent")
print(result.state, result.report["issues"][0]["code"])  # rejected quote_fuzzy
```

Пакет отклонён целиком, в базу ничего не записано. Отчёт показывает ближайший настоящий текст в файле:
`vector - up to 2,000 dimensions`.

**4. Найдите**

```python
hits = recipes.exact_fact(conn, "halfvec", agent="model:my-agent")
print(hits["items"][0]["label"]["ru"])  # pgvector: индекс HNSW по vector — до 2000 измерений
```

Остальное — очередь проверки, карточки, подборки, папки и бэкапы — в [справочнике библиотеки](docs/library.ru.md).

### Веб-UI на образцах данных

Веб-UI собран по HTTP-контракту и до выхода службы работает на моках.

```bash
cd web
npm ci
npm run dev:mock      # Node 24+; затем откройте http://127.0.0.1:5173/ui/
```

### Дальше: установка одной командой

> [!NOTE]
> **Пока недоступно.** Это задуманный интерфейс службы, CLI и памяти агентов
> ([подпроект 4](docs/superpowers/specs/2026-11-07-amem-subproject-4-service-design.md)).

```bash
pipx install amem
amem init                     # база и хранилище объектов
amem install claude-code      # сервер MCP, хуки и навыки; `amem install codex` — для Codex CLI
amem serve                    # HTTP API, /mcp и веб-UI на http://127.0.0.1:8767/ui
```

## Как это устроено

```mermaid
flowchart LR
    agents["Агенты<br/>MCP · CLI · хуки"] -- предлагают --> check
    people["Люди<br/>веб-UI · CLI"] -- пишут --> check
    check["check.submit<br/>1 схема и шаблоны<br/>2 цитата найдена в файле<br/>3 здравый смысл<br/>4 дубли"]
    check -- одна транзакция --> base[("PostgreSQL + pgvector<br/>атомы · сущности · связи · ревизии")]
    check -. файлы-источники по хэшу .-> files[("хранилище OCFL")]
    base --> queue{{"очередь проверки"}}
    queue -- подтвердить или отклонить --> people
    base --> search["рецепты поиска<br/>exact_fact · similar<br/>what_changed · around_entity"]
    search -- короткие карточки, затем записи --> agents
```

Любая запись идёт через `check.submit`. Он проверяет весь пакет и пишет его одной транзакцией:

1. **Схема и шаблоны:** поля, типы, правила связей, единицы UCUM.
2. **Привязка к источнику:** цитата найдена в файле, страница совпадает, числа утверждения есть
   во фрагменте. Работает для PDF, Markdown, xlsx и docx.
3. **Здравый смысл:** диапазоны значений, единицы, противоречия с атомами, которые уже есть в базе.
4. **Дубли:** по тексту и по вектору.

Ошибка уровня 1 или 2 отклоняет пакет с отчётом. Иначе каждая запись получает статус:

| Статус | Что значит |
|---|---|
| `draft` | Прошёл уровни 1–4 без замечаний; ждёт смысловой проверки (уровень 5) |
| `needs_review` | Есть предупреждение или высокий риск; ждёт человека |
| `auto_verified` | Пройдены все пять уровней, риск низкий |
| `verified` | Человек подтвердил по источнику. Запись самого человека проверена сразу |
| `rejected` | Человек отклонил |
| `deprecated`, `superseded` | Выведен из оборота; хранится для истории |

**Как выглядит атом** (`amem.atom/1`):

```yaml
kind: fact
key: pgvector.hnsw_max_dimensions
label:
  en: pgvector indexes vector with HNSW up to 2,000 dimensions
  ru: "pgvector: индекс HNSW по vector — до 2000 измерений"
summary_plain:
  en: Longer embeddings need halfvec, up to 4,000.
  ru: Длинные векторы индексируются через halfvec, до 4000.
content:
  values:
    - {property: max_indexed_dimensions, amount: 2000, unit: "1"}
sources:
  - path: pgvector/README.md
    selectors: [{type: heading, value: HNSW}]
    quote: vector - up to 2,000 dimensions
    role: primary
```

Статус агент не ставит — его ставят проверка и люди.

**Основные понятия**

| Понятие | Что это |
|---|---|
| **Атом** | Небольшое типизированное утверждение: факт, термин, методика, решение, вопрос, урок, требование или параметр |
| **Сущность** | То, о чём говорят атомы: проект, документ, редакция, организация, человек, место, программа, тема |
| **Объект** | Файл-источник, веб-страница или сообщение. Файлы хранятся один раз по хэшу содержимого |
| **Связь** | Типизированное отношение между записями с правилами для концов. Связи выводят из оборота, а не удаляют |
| **Ревизия** | Одна правка записи: каноническое тело, хэш содержимого, автор и причина |
| **Пакет** | Словарь области с шаблонами и профилями сущностей. Ядро — тоже пакет |
| **Подборка** | Переносимый набор записей (`amem.bundle/1`), с файлами или без |

**Рецепты поиска.** Четыре именованных рецепта возвращают обычный JSON, с которым агенты работают напрямую:

| Рецепт | Отвечает на вопрос |
|---|---|
| `exact_fact` | *Что такое X в точности?* Коды, марки, полнотекст и векторы, слитые через RRF |
| `similar` | *Что ещё похоже на это?* Смысловые соседи текста или записи |
| `what_changed` | *Что изменилось с понедельника?* Ревизии, решения, статусы, переносы и связи |
| `around_entity` | *Что мы знаем вокруг X?* Кратчайшие пути по связям с оценкой по самому слабому звену |

Агенты отмечают атомы, которые им помогли. Отметки со временем затухают и дают небольшой ограниченный
подъём в выдаче. Статус они не меняют и проверку не обходят.

## Дорожная карта

- [x] **Ядро и хранилище:** схема LinkML, ревизии, объекты по хэшу, пакеты домена
- [x] **Поисковый движок:** четыре рецепта, ранжирование RRF, отметки полезности, бэкапы
- [x] **Автопроверка** (уровни 1–4) и **очередь проверки** с арендой пунктов, аудитом и метриками
- [x] **Онтология:** профили сущностей, карточки на лету, переносимые подборки
- [x] **Библиотека для службы:** папки, списки записей, ссылки по ключу, карточка объекта
- [ ] **Служба HTTP:** `amem serve` по [контракту v1](docs/api/http-v1.openapi.yaml) *(в работе)*
- [ ] **CLI и сервер MCP:** поиск в три шага, отметки полезности, вырезание `<private>`
- [ ] **Память агентов:** хуки Claude Code, Codex CLI, `amem install`, навыки ядра
- [ ] **Веб-UI:** основа, чтение и небо готовы на моках; дальше — запись
- [ ] **asearch:** поиск по файлам как плагин amem

## Документация

| | |
|---|---|
| [Справочник библиотеки](docs/library.ru.md) | Модель данных, поиск, автопроверка, очередь, карточки, подборки, папки, бэкапы |
| [HTTP API v1](docs/api/) | Контракт OpenAPI между службой и веб-UI |
| [Манифест](docs/MANIFESTO.ru.md) | Зачем существует amem и на чём он стоит |
| [Спецификации и планы](docs/superpowers/) | Как решали и строили каждый подпроект |

**Полезно знать**

- Схема v1 требует подпись на русском (`ru`); остальные языки — по желанию. Полнотекст настроен
  на русский язык, а необязательная локальная модель векторов многоязычная.
- Векторы локальные и необязательные: `pip install -e ".[embed]"` добавляет fastembed, а модель
  скачивается только с явного разрешения. `AMEM_BACKEND=none` выключает смысловой канал, лексический
  поиск продолжает работать.
- Бэкапу нужен клиент PostgreSQL 18 (`pg_dump`, `pg_restore`, `psql`) в `PATH` или в папке `AMEM_PG_BIN`.

## Разработка

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# тестовые базы: PostgreSQL 18 (порт 5433) и 16 (порт 5434)
docker compose --profile test up -d --wait db-test db-test-pg16

# запуск тестов (тестам бэкапа нужен клиент PostgreSQL 18)
.venv/bin/pytest -q
```

Другие порты или серверы задаются так: `AMEM_TEST_DSNS="postgresql://…/test,postgresql://…/test"`.
Нет тестовой базы или клиента — это падение теста, а не пропуск. Если окружение выставляет `PYTHONPATH`
от других инструментов (например, ROS), он ломает автозагрузку плагинов pytest — тогда запускайте
`env -u PYTHONPATH .venv/bin/pytest -q`.

После правки `amem/schema/amem_v1.yaml` перегенерируйте модели:

```bash
.venv/bin/python tools/gen_schema.py          # пишет amem/model_v1.py и JSON Schema
.venv/bin/python tools/gen_schema.py --check  # проверка в CI: сгенерированное актуально
```

Веб-UI лежит в [`web/`](web/) (React 19, HeroUI v3, TanStack). Там же — `npm run lint`, `npm test`
и `npm run e2e`.

## Участие

amem делается открыто. Вопросы и обсуждения приветствуются. Перед большой правкой откройте, пожалуйста,
issue, чтобы договориться о подходе. Каждый pull request проходит workflow `ci` (тесты на PostgreSQL 18 и 16),
а правки в `web/` — ещё и workflow `web`.

## На чём построен

[PostgreSQL](https://www.postgresql.org/) ·
[pgvector](https://github.com/pgvector/pgvector) ·
[LinkML](https://linkml.io/) ·
[OCFL](https://ocfl.io/) ·
[PyMuPDF](https://pymupdf.readthedocs.io/) ·
[fastembed](https://github.com/qdrant/fastembed) ·
[React](https://react.dev/) ·
[HeroUI](https://www.heroui.com/) ·
[force-graph](https://github.com/vasturiano/force-graph)

## Лицензия

MIT, см. [LICENSE.txt](LICENSE.txt). © 2026 Филипп Белобородов (Philipp Beloborodov).

<p align="center"><sub>amem — инструмент для того, чтобы хорошо помнить.</sub></p>
