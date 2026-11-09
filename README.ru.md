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
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/ru/sky-dark.png">
    <img alt="Небо: вся память как созвездие атомов и объектов" src="docs/assets/readme/ru/sky-light.png" width="100%">
  </picture>
</p>

> [!IMPORTANT]
> **amem молод.** Ядро, HTTP-служба с веб-UI, CLI, сервер MCP и память агентов для Claude Code и Codex уже
> работают и проверяются в CI на PostgreSQL 18 и 16. Схема и HTTP-контракт ещё могут меняться. Снимки на этой
> странице сняты с настоящей службы на образце базы (`tools/seed_sample.py`, метеостанция с датчиками).

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
        <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/ru/record-dark.png">
        <img alt="Страница записи с цитатой, подсвеченной на странице источника" src="docs/assets/readme/ru/record-light.png">
      </picture>
      <h3>Утверждение рядом с источником</h3>
      Запись читается как заметка: свойства, тело в Markdown и цитата, подсвеченная на настоящей странице
      файла. Процитированные файлы хранятся один раз по хэшу содержимого и не пропадают.
    </td>
    <td width="50%" valign="top">
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/ru/review-dark.png">
        <img alt="Очередь проверки: утверждение, цитата и кнопки решения" src="docs/assets/readme/ru/review-light.png">
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
        <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/ru/card-dark.png">
        <img alt="Карточка сущности: полнота и параметры с известными, недостающими и спорными значениями" src="docs/assets/readme/ru/card-light.png">
      </picture>
      <h3>Карточка объекта</h3>
      Профиль говорит, какие параметры нужны объекту. Карточка показывает, что известно, чего нет и где
      расхождение. Она собирается из атомов на лету, поэтому не устаревает.
    </td>
    <td width="50%" valign="top">
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/ru/agent-dark.png">
        <img alt="Сессия агента по MCP: amem_search, amem_get с цитатой источника, amem_helpful" src="docs/assets/readme/ru/agent-light.png">
      </picture>
      <h3>Память для агентов</h3>
      Claude Code и Codex сначала спрашивают amem. Они читают короткие карточки, берут только нужные
      записи и отмечают, что помогло, — это дешевле по токенам, чем читать сырые файлы.
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

Веб-UI работает на службе или на моках того же HTTP-контракта. Что в нём есть:

- **Небо.** Главная — созвездие записей в цветах семей (источник, работа, объект); новая запись вспыхивает
  на своём месте. 3D-вид грузится по запросу.
- **Чтение.** Запись показывает свойства и текст рядом с источником: цитата подсвечена на настоящей
  странице PDF, диапазон таблицы или фрагмент текста — с версией файла. Карточки сущностей, объекты, лента
  изменений.
- **Запись.** Быстрая запись одной строкой (`N`), полный редактор с Markdown, формулами и источниками,
  папки с перетаскиванием, конструктор видов. У каждого действия есть 6 секунд на отмену.
- **Проверка.** Очередь в две панели с клавишами `J` `K` `Y` `N` `S`: утверждение, источник, замечания
  проверки, пословное сравнение правки и обе версии, если источник изменился. **База** — очередь, статусы
  и бэкапы; **Подборки** — выгрузка и загрузка `amem.bundle/1` и антологий.

Светлая и тёмная темы, русский и английский, раскладка для телефона. Дизайн-система описана в
[`web/DESIGN.md`](web/DESIGN.md).

На службе с образцом базы (метеостанция: датчики, руководство PDF с цитатами, заметки и открытая очередь
проверки), в пустой базе:

```bash
.venv/bin/pip install -e . -e web/python          # служба и пакет веб-UI
(cd web && npm ci && npm run build)               # Node 24+; сборка ложится в пакет amem-web
export AMEM_DSN=postgresql://amem:amem@127.0.0.1:5435/amem AMEM_DOCS=~/amem-sample/docs
.venv/bin/python tools/seed_sample.py             # образец: 22 записи, 2 открытых пункта проверки
.venv/bin/python -m amem.service                  # затем откройте http://127.0.0.1:8767/ui/
```

На моках, без базы:

```bash
cd web && npm ci && npm run dev:mock              # затем откройте http://127.0.0.1:5173/ui/
```

### Установка одной командой

```bash
pip install amem              # или pipx / uv tool install; до выхода на PyPI — pip install -e . из клона
amem init --dsn postgresql://amem:amem@127.0.0.1:5435/amem   # база и хранилище; DSN запоминается в amem.toml
amem install claude-code      # сервер MCP, хуки и навыки; `amem install codex` — для Codex CLI
amem doctor                   # что работает и что поправить
```

`amem init --dsn` запоминает строку подключения в `~/.config/amem/amem.toml` (права `0600`): агенты, хуки и CLI
находят базу без `AMEM_DSN` в окружении. PostgreSQL с pgvector — из `docker compose up -d --wait db` или свой.
CI проходит эти шаги на каждом push.

## Служба

HTTP-служба отдаёт [контракт v1](docs/api/http-v1.openapi.yaml) по `/api/v1` и веб-UI по `/ui`. Запускается
командой `amem serve` (или `python -m amem.service`):

```bash
export AMEM_DSN=postgresql://amem:amem@127.0.0.1:5435/amem
.venv/bin/amem serve      # http://127.0.0.1:8767; адрес меняют --host и --port
```

- **Локальное доверие.** По умолчанию служба слушает только `127.0.0.1`. Она отвечает только на своё имя в `Host`
  (`127.0.0.1`, `localhost`, `[::1]`, адрес привязки) и только своей странице или `AMEM_UI_ORIGINS` в `Origin`;
  запись принимает только JSON. Веб-UI получает cookie человека, новую при каждом запуске. Если ввести адрес
  в строке браузера, сама страница cookie не получает: её выдаёт первый `fetch` интерфейса к `/api/v1/session`.
  Запросы без cookie (скрипты, агенты) пишут как модель, и их записи идут через проверку.
- **Общая служба.** С `AMEM_TOKENS` (файл `0600` с хэшами токенов) каждый запрос к API требует
  `Authorization: Bearer <токен>`. Токен без `write = true` — только для чтения: запись отвечает `403 read_only`.
  `/health` и статика интерфейса открыты без входа. `--host` не loopback без токенов служба отвергает;
  `--no-auth` разрешает его для закрытой сети и печатает предупреждение.
- **Под своим именем.** С `--host 0.0.0.0` (например, в docker compose) имена, по которым к службе обращаются,
  перечисляет `AMEM_ALLOWED_HOSTS`: `AMEM_ALLOWED_HOSTS=amem` принимает `Host: amem:8767`. Перечисляйте только имена,
  которыми управляете: имя, которое браузер может разрешить в чужой адрес, открывает службу для DNS rebinding.
- **Состояние.** Подборки и загрузки лежат в `AMEM_STATE` (`~/.local/state/amem`) сутки, не больше
  `AMEM_STATE_QUOTA` на владельца (10 ГиБ). Журнал запросов — `AMEM_STATE/queries.jsonl`; `AMEM_QUERY_LOG=off`
  выключает его. Свой журнал служба пишет в stderr.
- **Веб-UI.** Для `/ui` нужен пакет веба: `pip install 'amem[web]'`. Без него `/ui` отвечает 404 с подсказкой,
  а API работает как обычно.

## Docker compose

`docker-compose.yml` поднимает базу и службу; настройки — в `.env` (образец `.env.example`), в самом файле
секретов нет.

```bash
cp .env.example .env                          # задайте AMEM_PG_PASSWORD и AMEM_AGENT
docker compose up -d --wait amem              # PostgreSQL 18 + pgvector и служба на http://127.0.0.1:8767
docker compose exec amem amem doctor
docker compose --profile web up -d --wait amem-web   # то же с веб-UI по /ui (вместо amem)
```

- **Внутри и снаружи.** Служба слушает `0.0.0.0:8767` внутри сети compose, наружу публикуется только
  `127.0.0.1:8767`. `AMEM_ALLOWED_HOSTS=amem` — другие контейнеры зовут её как `http://amem:8767`.
- **Вход.** Без `AMEM_TOKENS` служба идёт с `--no-auth`: любой, кто достучится до порта, пишет как модель, поэтому
  порт — только на `127.0.0.1`. Для общей службы выдайте токен
  (`docker compose exec amem amem token create person:me --file /var/lib/amem/state/tokens`), задайте
  `AMEM_TOKENS=/var/lib/amem/state/tokens` в `.env` и перезапустите.
- **Тома.** `amem-pg` (база), `amem-objects` (хранилище копий), `amem-state` (подборки, загрузки, журнал запросов,
  токены), `amem-backups` (`docker compose exec amem amem backup create`; в образе есть клиент PostgreSQL 18).
  `AMEM_DOCS_DIR` подключает вашу папку документов только для чтения.
- **Живость.** Образ и compose проверяют `/health`; `docker compose up --wait` ждёт его.
- **Профиль `web`.** `amem-web` — та же служба, собранная с `amem[web]`. Порт и тома у них общие: запускайте
  либо `amem`, либо `amem-web`.
- **Образ.** `docker build -t amem .` (цель `service`) или `--target web`; `--build-arg AMEM_EXTRAS=embed`
  добавляет локальную модель векторов.

## CLI

`pip install -e .` ставит команду `amem` в venv. Она работает с базой напрямую (`AMEM_DSN` или
`amem init --dsn …`, который запоминает строку в `~/.config/amem/amem.toml`), служба ей не нужна.

```
amem init [--dsn DSN]                 база и хранилище объектов
amem serve [--host --port --no-auth]  HTTP API, /mcp и веб-UI
amem mcp [--agent model:ИМЯ]          сервер MCP на stdio для агента
amem search ЗАПРОС [--kind --limit]   поиск, шаг 1
amem timeline REF                     что вокруг записи, шаг 2
amem get REF...                       полные записи, шаг 3
amem card REF                         карточка сущности
amem submit FILE.json                 запись пакета (тело как у POST /submit; «-» — stdin)
amem review list|claim|release|resolve|stats
amem folders tree|create|delete|rename|move
amem export|inspect|import FILE.zip   подборки (import без --apply — пробный)
amem backup create|list|restore|verify
amem token create|list|revoke         токены общей службы
amem base [name [ИМЯ]]                сводка и имя базы
amem doctor [--project DIR]          база, хранилище, модель, документы, агенты, служба
```

- **Вывод.** Текст для человека или `--json` с тем же объектом, что HTTP API отдаёт на ту же операцию.
  Ошибка называет, что сделать: «задайте AMEM_DSN или выполните amem init».
- **Коды выхода.** `0` успех, `1` окружение (нет базы, нет хранилища), `2` неверный вызов, `3` неоднозначный
  текст вместо ссылки (выведены кандидаты), `4` не найдено, `5` проверка отклонила пакет (выведен отчёт),
  `6` конфликт (пункт уже решён, папка занята, коллизия подборки).
- **Кто пишет.** В обычном терминале — человек `AMEM_AGENT` (по умолчанию `person:` и имя пользователя ОС).
  В окружении агента команда идёт от модели: `CLAUDECODE=1` — `model:claude-code`, переменные песочницы Codex —
  `model:codex`, `AMEM_AS_MODEL=имя` — `model:имя`. `--agent` задаёт агента явно, но `person:` в окружении агента
  не принимается.
- **Токены.** `amem token create person:ann` (или `model:…`, `--read-only`) показывает токен один раз и хранит
  в `AMEM_TOKENS` только его хэш. Выдаёт и отзывает токены только человек.
- **Бэкап.** Модели доступен `amem backup create`, но без ротации: `--keep` и `restore` — только человеку.
- **Отладка.** `AMEM_DEBUG=1` добавляет в stderr traceback внутренней ошибки.

## MCP

Сервер MCP даёт агенту 14 инструментов над теми же операциями, что HTTP API:

| Инструмент | Что делает |
|---|---|
| `amem_search(query, kind?, limit?)` | Шаг 1: короткие находки `{ref, label, kind, status, snippet}` и `retrieval_id` |
| `amem_similar(query \| ref, limit?)` | Похожие записи, в той же форме |
| `amem_timeline(ref)` | Шаг 2: последние события записи и её соседи |
| `amem_get(refs)` | Шаг 3: полные записи — тело, источники, статус, открытые пункты |
| `amem_card(ref)` | Карточка сущности `amem.card/1` |
| `amem_submit(proposals, links?, reason?)` | Запись пакета через `check.submit` |
| `amem_helpful(retrieval_id, refs)` | Отметить атомы, которые помогли |
| `amem_move(ref, folder)` | Переложить запись в существующую папку |
| `amem_object_status(path)`, `amem_mark_object(path, status, note?)` | Что из документа уже атомизировано |
| `amem_review_claim`, `amem_review_release`, `amem_review_resolve` | Для смыслового проверяющего |
| `amem_vocab(scheme)` | Коды словаря с подписями |

Поиск идёт в три шага, чтобы агент читал только нужное: `amem_search` даёт короткие карточки, `amem_timeline`
показывает, что вокруг находки, `amem_get` отдаёт выбранные записи целиком. Текст, под который подходят несколько
записей без явного лидера, возвращается как `ambiguous: true` с кандидатами, а не первой попавшейся записью.

**Через stdio.** `amem mcp` — одна сессия на процесс со своим маленьким пулом соединений. Claude Code:

```bash
claude mcp add amem --env AMEM_DSN=postgresql://amem:amem@127.0.0.1:5435/amem -- amem mcp --agent model:claude-code
```

или в `.mcp.json` проекта:

```json
{
  "mcpServers": {
    "amem": {
      "command": "amem",
      "args": ["mcp", "--agent", "model:claude-code"],
      "env": { "AMEM_DSN": "postgresql://amem:amem@127.0.0.1:5435/amem" }
    }
  }
}
```

Codex CLI, в `~/.codex/config.toml` (DSN — в `amem.toml` или в окружении, не в этом файле):

```toml
[mcp_servers.amem]
command = "amem"
args = ["mcp", "--agent", "model:codex"]
env_vars = ["AMEM_DSN", "AMEM_CONFIG"]
```

**Через HTTP.** Запущенная служба отдаёт те же инструменты по `/mcp` (Streamable HTTP):

```bash
claude mcp add --transport http amem http://127.0.0.1:8767/mcp --header "X-Amem-Agent: model:claude-code"
```

```toml
[mcp_servers.amem]
url = "http://127.0.0.1:8767/mcp"
http_headers = { "X-Amem-Agent" = "model:codex" }
```

- **Всегда модель.** Клиент MCP пишет как `model:…`, и его записи идут через проверку. У stdio агент — из
  `--agent model:…` или окружения агента; у `/mcp` — из заголовка `X-Amem-Agent`, иначе агент-модель токена,
  иначе `AMEM_MODEL_AGENT` (`model:local`). `person:` не принимается.
- **Общая служба.** С `AMEM_TOKENS` `/mcp`, как и API, требует `Authorization: Bearer <токен>`; токен только для
  чтения ищет, а инструменты записи отвечают `read_only`. Заголовок, который спорит с агентом-моделью токена,
  отвергается.
- **Полезность.** `amem_helpful` отмечает атомы только из поиска той же сессии (у клиентов без сессий — того же
  агента и входа); чужой `retrieval_id` — `forbidden`.
- **Журнал запросов.** Явные поиски (`amem search`, `amem_search`, `amem_similar`) пишут строку в
  `AMEM_STATE/queries.jsonl`, как `/search` службы; шаги чтения — нет.

## Память агентов

`amem install claude-code` и `amem install codex` подключают amem к агенту — глобально или с `--project DIR`.
`amem uninstall …` убирает ровно установленное; `--dry-run` сначала показывает изменения.

| | Claude Code | Codex CLI |
|---|---|---|
| Сервер MCP | `claude mcp add --scope user` (или `~/.claude.json`); проект — `.mcp.json` | `[mcp_servers.amem]` в `~/.codex/config.toml`; проект — `.codex/config.toml` |
| Хуки | `SessionStart`, `UserPromptSubmit`, `PreCompact` в `settings.json` | `SessionStart`, `UserPromptSubmit` в `hooks.json` |
| Навыки | `~/.claude/skills/amem-*`; проект — `.claude/skills/` | `~/.agents/skills/`; проект — `.agents/skills/`, и блок в `AGENTS.md` |

- **Хуки.** `amem hook SessionStart` добавляет 3–5 проверенных атомов о проекте (по имени корня git) и
  напоминание; `UserPromptSubmit` — уверенные находки по запросу («сначала amem»); `PreCompact` просит сводку
  перечислить выводы, которые стоит записать. Хук читает базу напрямую, укладывается в 1,5 с и при любом сбое
  отвечает пусто с кодом 0. Текст из памяти приходит в рамке как данные со статусом проверки, а не как указания.
- **Навыки.** `amem-remember` (записать 1–3 атома в конце задачи), `amem-answer` (ответ по памяти со ссылками на
  источники), `amem-verify` (смысловой проверяющий, уровень 5).
- **Кто пишет.** Установщик задаёт `AMEM_AS_MODEL` серверу MCP и хукам: агент пишет как `model:claude-code` или
  `model:codex`, а не от вашего имени.
- **Правит только своё.** Ключи `amem` и элементы хуков с `amem hook` в JSON, блок `# amem:begin … # amem:end`
  в TOML, блок `<!-- amem:begin … -->` в Markdown. Перед первой правкой файл копируется в `<файл>.amem-backup`.
- **Codex.** Codex передаёт серверу MCP только переменные из `env_vars`; установщик перечисляет `AMEM_DSN`,
  `AMEM_CONFIG`, `AMEM_STATE`, `PGPASSFILE` и `PGSERVICE` и никогда не пишет строку подключения в `config.toml`.
  Базу задавайте в `amem.toml` через `amem init --dsn …` (или в этих переменных). Файлы проекта Codex читает
  только у доверенного проекта.
- **Файлы проекта.** С `--project` в файлы идёт голая команда `amem`, без пути этой машины, — их можно
  коммитить; `amem` должен быть в `PATH` агента. Глобальная установка пишет полный путь.
- **Windows.** Команды хуков — строки оболочки POSIX (`AMEM_AS_MODEL=… amem hook …`): они работают в Linux, macOS
  и WSL2, но не в родных оболочках Windows. Используйте WSL2.
- **Проверка.** `amem doctor` показывает, что установлено (глобально и для проекта текущей папки) и существует ли
  ещё его команда; затем `claude mcp list` или `codex mcp list` подтверждают, что агент видит сервер.

**Расписание `amem-verify`.** Смысловой проверяющий — это агент, которого запускают по вашему расписанию,
например каждую ночь через cron:

```cron
# м ч д мес дн
30 3 * * *  cd ~/notes && claude -p "Use the amem-verify skill: review up to 20 open semantic items." >> ~/.local/state/amem/verify.log 2>&1
```

или таймером systemd пользователя:

```ini
# ~/.config/systemd/user/amem-verify.service
[Service]
Type=oneshot
WorkingDirectory=%h/notes
ExecStart=/usr/bin/env claude -p "Use the amem-verify skill: review up to 20 open semantic items."

# ~/.config/systemd/user/amem-verify.timer
[Timer]
OnCalendar=*-*-* 03:30
Persistent=true
[Install]
WantedBy=timers.target
```

`systemctl --user enable --now amem-verify.timer`. Агенту нужен сервер MCP amem (`amem install …`).

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
   во фрагменте. Работает для PDF, Markdown, xlsx и docx. Страница-скан PDF (картинка без текстового слоя)
   распознаётся Tesseract через PyMuPDF, если установлены языковые данные: в Debian/Ubuntu —
   `sudo apt install tesseract-ocr tesseract-ocr-rus`, в macOS — `brew install tesseract tesseract-lang`;
   языки по умолчанию `rus+eng`, свои — `AMEM_OCR_LANGUAGES`. Цитата, сверенная с распознанным текстом,
   получает замечание `info` `quote_ocr` и более мягкий порог нечёткости; без Tesseract о такой странице
   сказано, что у неё нет текстового слоя.
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

**Рецепты поиска.** Пять именованных рецептов возвращают обычный JSON, с которым агенты работают напрямую:

| Рецепт | Отвечает на вопрос |
|---|---|
| `exact_fact` | *Что такое X в точности?* Коды, марки, полнотекст и векторы, слитые через RRF |
| `similar` | *Что ещё похоже на это?* Смысловые соседи текста или записи |
| `what_changed` | *Что изменилось с понедельника?* Ревизии, решения, статусы, переносы и связи |
| `around_entity` | *Что мы знаем вокруг X?* Кратчайшие пути по связям с оценкой по самому слабому звену; останавливается на `limit` (по умолчанию 300, раньше без предела), `total` — узлов без предела |
| `overview` | *Как выглядит вся база?* Хабы по числу связей (`degree`), их соседи и рёбра между ними; фильтр по `project` |

Агенты отмечают атомы, которые им помогли. Отметки со временем затухают и дают небольшой ограниченный
подъём в выдаче. Статус они не меняют и проверку не обходят.

## Дорожная карта

- [x] **Ядро и хранилище:** схема LinkML, ревизии, объекты по хэшу, пакеты домена
- [x] **Поисковый движок:** четыре рецепта, ранжирование RRF, отметки полезности, бэкапы
- [x] **Автопроверка** (уровни 1–4) и **очередь проверки** с арендой пунктов, аудитом и метриками
- [x] **Онтология:** профили сущностей, карточки на лету, переносимые подборки
- [x] **Библиотека для службы:** папки, списки записей, ссылки по ключу, карточка объекта
- [x] **Служба HTTP:** `amem serve` по [контракту v1](docs/api/http-v1.openapi.yaml)
- [x] **CLI и сервер MCP:** поиск в три шага, отметки полезности, вырезание `<private>`
- [x] **Память агентов:** хуки Claude Code, Codex CLI, `amem install`, навыки ядра
- [x] **Веб-UI:** все экраны — на службе и на моках; сквозные проверки против службы
- [ ] **asearch:** поиск по файлам как плагин amem

## Документация

| | |
|---|---|
| [Справочник библиотеки](docs/library.ru.md) | Модель данных, поиск, автопроверка, очередь, карточки, подборки, папки, бэкапы |
| [HTTP API v1](docs/api/) | Контракт OpenAPI между службой и веб-UI |
| [Манифест](docs/MANIFESTO.ru.md) | Зачем существует amem и на чём он стоит |
| [Спецификации и планы](docs/superpowers/) | Как решали и строили каждый подпроект |

**Полезно знать**

- Схема v1 требует поле `ru` у каждой подписи; остальные языки — по желанию. База на английском пишет
  туда английский текст, как английский образец. Полнотекст настроен на русский язык, а необязательная
  локальная модель векторов многоязычная.
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
Перед push — проверка на приватное: `git config core.hooksPath tools/hooks`; список образцов хук читает из `~/.config/amem/private-patterns.txt` (вне репозитория).

Сообщения коммитов — по [Conventional Commits](https://www.conventionalcommits.org/) и на английском:
`type(scope): subject`, не длиннее 100 знаков, например `fix(service): reject NUL in parameters`. Тот же
`core.hooksPath` включает хук `commit-msg`, который проверяет это при коммите;
`python3 tools/check_commits.py --revs origin/main..HEAD` проверяет диапазон вручную.


Веб-UI лежит в [`web/`](web/) (React 19, HeroUI v3, TanStack). Там же — `npm run lint`, `npm test`
и `npm run e2e`.

## Участие

amem делается открыто. Вопросы и обсуждения приветствуются. Перед большой правкой откройте, пожалуйста,
issue, чтобы договориться о подходе. Каждый pull request проходит workflow `ci` (тесты на PostgreSQL 18 и 16)
и workflow `commits` (Conventional Commits на английском), а правки в `web/` — ещё и workflow `web`.

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
