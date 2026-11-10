<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/banner-dark.svg">
    <img alt="amemo — another memory" src="docs/assets/readme/banner-light.svg" width="100%">
  </picture>
</p>

<h3 align="center">Общая память людей и ИИ-агентов, где у каждого утверждения есть доказательство.</h3>

<p align="center">
  Открытая база знаний из небольших утверждений с источниками. Агенты предлагают, автопроверка
  находит цитату в самом файле, а последнее слово остаётся за человеком.
</p>

<p align="center">
  <a href="https://github.com/empty-complete/amemo/actions/workflows/ci.yml"><img alt="Тесты" src="https://img.shields.io/github/actions/workflow/status/empty-complete/amemo/ci.yml?branch=main&label=tests&style=flat-square"></a>
  <a href="https://github.com/empty-complete/amemo/actions/workflows/web.yml"><img alt="Веб-UI" src="https://img.shields.io/github/actions/workflow/status/empty-complete/amemo/web.yml?branch=main&label=web%20ui&style=flat-square"></a>
  <a href="LICENSE.txt"><img alt="Лицензия AGPL-3.0" src="https://img.shields.io/badge/license-AGPL--3.0-2a78d6?style=flat-square"></a>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-3776ab?style=flat-square&logo=python&logoColor=white">
  <img alt="PostgreSQL 16+ с pgvector" src="https://img.shields.io/badge/PostgreSQL-16%2B%20%C2%B7%20pgvector-4169e1?style=flat-square&logo=postgresql&logoColor=white">
  <img alt="Состояние: ранняя разработка" src="https://img.shields.io/badge/status-early%20development-eb6834?style=flat-square">
</p>

<p align="center">
  <a href="#установка-через-агента"><b>Установка</b></a> ·
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
> **amemo молод.** Ядро, HTTP-служба с веб-UI, CLI, сервер MCP и память агентов для Claude Code и Codex уже
> работают и проверяются в CI на PostgreSQL 18 и 16. Схема и HTTP-контракт ещё могут меняться. Снимки на этой
> странице сняты с настоящей службы на образце базы (`tools/seed_sample.py`, метеостанция с датчиками).

## Зачем amemo

Агенты забывают всё между сессиями, а то, что помнят, — текст без доказательств. Заметки и вики хранят,
что написали люди, но не откуда это взялось и кто решил, что это верно.

amemo хранит единицу поменьше и понадёжнее — **атом**. Атом — это одно утверждение, точное место в файле,
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
        <img alt="Сессия агента по MCP: amemo_search, amemo_get с цитатой источника, amemo_helpful" src="docs/assets/readme/ru/agent-light.png">
      </picture>
      <h3>Память для агентов</h3>
      Claude Code и Codex сначала спрашивают amemo. Они читают короткие карточки, берут только нужные
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

## Установка через агента

Вставьте это в Claude Code, Codex или другого агента для кода:

```text
Установи amemo на этот компьютер по инструкции https://raw.githubusercontent.com/empty-complete/amemo/main/docs/install-agent.md
```

Агент начинает с пустой машины. Он смотрит, что уже стоит, ставит PostgreSQL с pgvector (в Docker, если он
есть, иначе напрямую; в Windows — внутри WSL2), сам amemo, подключает его к вашим агентам и заканчивает
`amemo doctor`. Перед `sudo`, перезагрузкой и большой загрузкой он спрашивает. Инструкция целиком —
[`docs/install-agent.md`](docs/install-agent.md) (на английском, агент ответит на вашем языке); её команды CI
проходит на Linux и macOS. Вручную — [установка одной командой](#установка-одной-командой).

## Быстрый старт

Нужны Python 3.11+, Docker (для PostgreSQL) и Linux или macOS. В Windows — через WSL2.

**1. Запустите PostgreSQL и поставьте библиотеку**

```bash
git clone https://github.com/empty-complete/amemo.git
cd amemo
docker compose up -d --wait db      # PostgreSQL 18 + pgvector на 127.0.0.1:5435
python3 -m venv .venv
.venv/bin/pip install -e .          # или -e ".[embed]" для локальных многоязычных векторов
```

**2. Запишите факт с источником**

```python
from pathlib import Path

from amemo import check, db, recipes
from amemo.check import Proposal
from amemo.ocfl_store import ObjectStore

conn = db.connect("postgresql://amemo:amemo@127.0.0.1:5435/amemo")
db.prepare(conn)                                  # миграции и словарь ядра

docs = Path("my-docs")                            # папка с файлами-источниками
store = ObjectStore(Path("amemo-objects"))         # копии процитированных файлов по хэшу
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
(cd web && npm ci && npm run build)               # Node 24+; сборка ложится в пакет amemo-web
export AMEMO_DSN=postgresql://amemo:amemo@127.0.0.1:5435/amemo AMEMO_DOCS=~/amemo-sample/docs
.venv/bin/python tools/seed_sample.py             # образец: 22 записи, 2 открытых пункта проверки
.venv/bin/python -m amemo.service                  # затем откройте http://127.0.0.1:8767/ui/
```

На моках, без базы:

```bash
cd web && npm ci && npm run dev:mock              # затем откройте http://127.0.0.1:5173/ui/
```

### Установка одной командой

```bash
pipx install 'amemo[web]'      # или pip install / uv tool install; [web] добавляет веб-UI по /ui
amemo init --dsn postgresql://amemo:amemo@127.0.0.1:5435/amemo   # база и хранилище; DSN запоминается в amemo.toml
amemo install claude-code      # сервер MCP, хуки и навыки; `amemo install codex` — для Codex CLI
amemo doctor                   # что работает и что поправить
```

`amemo init --dsn` запоминает строку подключения в `~/.config/amemo/amemo.toml` (права `0600`): агенты, хуки и CLI
находят базу без `AMEMO_DSN` в окружении. PostgreSQL с pgvector — из `docker compose up -d --wait db`, прямой
установкой ([`docs/install-agent.md`](docs/install-agent.md), шаг 3) или свой. CI проходит эти шаги на каждом push.

## Служба

HTTP-служба отдаёт [контракт v1](docs/api/http-v1.openapi.yaml) по `/api/v1` и веб-UI по `/ui`. Запускается
командой `amemo serve` (или `python -m amemo.service`):

```bash
export AMEMO_DSN=postgresql://amemo:amemo@127.0.0.1:5435/amemo
.venv/bin/amemo serve      # http://127.0.0.1:8767; адрес меняют --host и --port
```

- **Локальное доверие.** По умолчанию служба слушает только `127.0.0.1`. Она отвечает только на своё имя в `Host`
  (`127.0.0.1`, `localhost`, `[::1]`, адрес привязки) и только своей странице или `AMEMO_UI_ORIGINS` в `Origin`;
  запись принимает только JSON. Веб-UI получает cookie человека, новую при каждом запуске. Если ввести адрес
  в строке браузера, сама страница cookie не получает: её выдаёт первый `fetch` интерфейса к `/api/v1/session`.
  Запросы без cookie (скрипты, агенты) пишут как модель, и их записи идут через проверку.
- **Общая служба.** С `AMEMO_TOKENS` (файл `0600` с хэшами токенов) каждый запрос к API требует
  `Authorization: Bearer <токен>`. Токен без `write = true` — только для чтения: запись отвечает `403 read_only`.
  `/health` и статика интерфейса открыты без входа. `--host` не loopback без токенов служба отвергает;
  `--no-auth` разрешает его для закрытой сети и печатает предупреждение.
- **Под своим именем.** С `--host 0.0.0.0` (например, в docker compose) имена, по которым к службе обращаются,
  перечисляет `AMEMO_ALLOWED_HOSTS`: `AMEMO_ALLOWED_HOSTS=amemo` принимает `Host: amemo:8767`. Перечисляйте только имена,
  которыми управляете: имя, которое браузер может разрешить в чужой адрес, открывает службу для DNS rebinding.
- **Состояние.** Подборки и загрузки лежат в `AMEMO_STATE` (`~/.local/state/amemo`) сутки, не больше
  `AMEMO_STATE_QUOTA` на владельца (10 ГиБ). Журнал запросов — `AMEMO_STATE/queries.jsonl`; `AMEMO_QUERY_LOG=off`
  выключает его. Свой журнал служба пишет в stderr.
- **Веб-UI.** Для `/ui` нужен пакет веба: `pip install 'amemo[web]'`. Без него `/ui` отвечает 404 с подсказкой,
  а API работает как обычно.

## Запись из веба

Человек пишет в веб-UI: форма для каждого вида, свои виды, загрузка файлов и задачи агентам.

- **Формы по шаблонам.** `GET /templates` даёт форму каждому виду атома и классу сущности, со своим шаблоном или
  без. Поля берутся из правил шаблона, поэтому форма просит то, что потом проверит `check.submit`. Необязательный
  блок `ui` в шаблоне пакета задаёт тело, виджеты и подписи полей; на проверку он не влияет:

  ```yaml
  code: reading
  version: 1.0.0
  target: atom
  applies_to: reading
  fields:
    - {path: about, required: true, entity_classes: [artifact]}
    - {path: content.values, required: true}
  ui:
    body: none                       # wanted | required | none
    widgets: [sources, values_table] # sources, links, around, values_table, similar, children
    fields:
      - {path: "content.values[property=humidity]", label: {ru: Влажность, en: Air humidity}}
  ```

- **Мои виды.** Человек заводит свой вид из веба (`PUT /packs/mine/templates/{code}`). Он живёт в базе как пакет
  `mine` и проходит те же проверки, что пакет из файлов, — как и его записи. Каждая правка — новая версия шаблона;
  код, занятый пакетом из файлов, не принимается (`409 template_exists`). Удалить вид можно, только пока у него
  нет записей (`409 template_in_use`). Правит и удаляет виды только человек, модель получает `403 forbidden`.
  `POST /bundles/export` с `with_packs` увозит свои виды с подборкой; импорт добавляет недостающие, а тот же код
  с другим содержимым — коллизия `bundle_pack_conflict`.
- **Загрузка и поиск файлов.** `POST /objects` (multipart: `file`, необязательный `path`) кладёт файл в папку
  документов `AMEMO_DOCS`, по умолчанию как `Загрузки/<имя файла>`, и разбирает его. Тот же файл по этому пути —
  `200`, другой файл там — `409 object_path_taken`, и он не тронут; без `AMEMO_DOCS` — `503 docs_unavailable`.
  `GET /objects?q=` находит объекты по части имени или пути.
- **Задачи агентам.** В вебе человек просит агента разобрать файл (`POST /tasks`); повтор возвращает ту же
  задачу. Агент берёт её через MCP: `amemo_tasks` — свободные задачи и свои, `amemo_task_claim` — взять с арендой
  на 30 минут, `amemo_task_release` — вернуть, `amemo_task_done` — закрыть с итогом (ссылками на записанное),
  `amemo_task_cancel` — отменить поставленную им. Истёкшая аренда освобождает задачу для другого агента.
  `GET /tasks` и `amemo tasks list` показывают открытые и взятые задачи, от новых к старым (закрытые —
  `--state done`); `amemo tasks cancel ID` отменяет (тот, кто поставил, или человек).

## Docker compose

`docker-compose.yml` поднимает базу и службу; настройки — в `.env` (образец `.env.example`), в самом файле
секретов нет.

```bash
cp .env.example .env                          # задайте AMEMO_PG_PASSWORD и AMEMO_AGENT
docker compose up -d --wait amemo              # PostgreSQL 18 + pgvector и служба на http://127.0.0.1:8767
docker compose exec amemo amemo doctor
docker compose --profile web up -d --wait amemo-web   # то же с веб-UI по /ui (вместо amemo)
```

- **Внутри и снаружи.** Служба слушает `0.0.0.0:8767` внутри сети compose, наружу публикуется только
  `127.0.0.1:8767`. `AMEMO_ALLOWED_HOSTS=amemo` — другие контейнеры зовут её как `http://amemo:8767`.
- **Вход.** Без `AMEMO_TOKENS` служба идёт с `--no-auth`: любой, кто достучится до порта, пишет как модель, поэтому
  порт — только на `127.0.0.1`. Для общей службы выдайте токен
  (`docker compose exec amemo amemo token create person:me --file /var/lib/amemo/state/tokens`), задайте
  `AMEMO_TOKENS=/var/lib/amemo/state/tokens` в `.env` и перезапустите.
- **Тома.** `amemo-pg` (база), `amemo-objects` (хранилище копий), `amemo-state` (подборки, загрузки, журнал запросов,
  токены), `amemo-backups` (`docker compose exec amemo amemo backup create`; в образе есть клиент PostgreSQL 18).
  `AMEMO_DOCS_DIR` подключает вашу папку документов только для чтения.
- **Живость.** Образ и compose проверяют `/health`; `docker compose up --wait` ждёт его.
- **Профиль `web`.** `amemo-web` — та же служба, собранная с `amemo[web]`. Порт и тома у них общие: запускайте
  либо `amemo`, либо `amemo-web`.
- **Образ.** `docker build -t amemo .` (цель `service`) или `--target web`; `--build-arg AMEMO_EXTRAS=embed`
  добавляет локальную модель векторов. `AMEMO_OCR_LANGS="rus eng"` в `.env` — образ с распознаванием сканов
  ([OCR](#распознавание-сканов-ocr)).

## CLI

`pip install -e .` ставит команду `amemo` в venv. Она работает с базой напрямую (`AMEMO_DSN` или
`amemo init --dsn …`, который запоминает строку в `~/.config/amemo/amemo.toml`), служба ей не нужна.

```
amemo init [--dsn DSN] [--ocr ЯЗЫКИ]   база и хранилище объектов; --ocr rus,eng — распознавание сканов
amemo serve [--host --port --no-auth]  HTTP API, /mcp и веб-UI
amemo mcp [--agent model:ИМЯ]          сервер MCP на stdio для агента
amemo search ЗАПРОС [--kind --limit]   поиск, шаг 1
amemo timeline REF                     что вокруг записи, шаг 2
amemo get REF...                       полные записи, шаг 3
amemo card REF                         карточка сущности
amemo submit FILE.json                 запись пакета (тело как у POST /submit; «-» — stdin)
amemo review list|claim|release|resolve|stats
amemo folders tree|create|delete|rename|move
amemo export|inspect|import FILE.zip   подборки (import без --apply — пробный)
amemo backup create|list|restore|verify
amemo tasks list|cancel              задачи агентам
amemo token create|list|revoke         токены общей службы
amemo base [name [ИМЯ]]                сводка и имя базы
amemo ocr install|list|remove          языки распознавания сканов (OCR)
amemo doctor [--project DIR]          база, хранилище, модель, документы, OCR, агенты, служба
```

- **Вывод.** Текст для человека или `--json` с тем же объектом, что HTTP API отдаёт на ту же операцию.
  Ошибка называет, что сделать: «задайте AMEMO_DSN или выполните amemo init».
- **Коды выхода.** `0` успех, `1` окружение (нет базы, нет хранилища), `2` неверный вызов, `3` неоднозначный
  текст вместо ссылки (выведены кандидаты), `4` не найдено, `5` проверка отклонила пакет (выведен отчёт),
  `6` конфликт (пункт уже решён, папка занята, коллизия подборки).
- **Кто пишет.** В обычном терминале — человек `AMEMO_AGENT` (по умолчанию `person:` и имя пользователя ОС).
  В окружении агента команда идёт от модели: `CLAUDECODE=1` — `model:claude-code`, переменные песочницы Codex —
  `model:codex`, `AMEMO_AS_MODEL=имя` — `model:имя`. `--agent` задаёт агента явно, но `person:` в окружении агента
  не принимается.
- **Токены.** `amemo token create person:ann` (или `model:…`, `--read-only`) показывает токен один раз и хранит
  в `AMEMO_TOKENS` только его хэш. Выдаёт и отзывает токены только человек.
- **Бэкап.** Модели доступен `amemo backup create`, но без ротации: `--keep` и `restore` — только человеку.
- **Отладка.** `AMEMO_DEBUG=1` добавляет в stderr traceback внутренней ошибки.

## Распознавание сканов (OCR)

Страница-скан PDF — картинка без текстового слоя: процитировать с неё можно, только распознав её. OCR в amemo —
расширение на выбор: можно поставить языки Tesseract, можно не ставить. Без OCR всё работает, а о сканах сказано,
что текста у них нет.

```bash
amemo ocr install rus eng            # скачать языки и включить OCR (или: amemo init --ocr rus,eng)
amemo ocr install deu --quality best # точнее, но файлы в несколько раз больше
amemo ocr list                       # режим, языки, папка данных
amemo ocr remove deu
```

- **Что ставится.** Распознаёт встроенная в PyMuPDF библиотека Tesseract: бинарник `tesseract` не нужен, только
  языковые файлы `.traineddata`. `amemo ocr install` скачивает их по HTTPS из репозиториев
  [tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast) (по умолчанию, `--quality fast`) или
  [tessdata_best](https://github.com/tesseract-ocr/tessdata_best) (`--quality best`) в `ocr_data`
  (`~/.local/share/amemo/tessdata`) и пишет `ocr = "tesseract"` и `ocr_languages` в `amemo.toml`. Повтор ничего
  не качает; `--force` — скачать заново.
- **Языки.** Коды tessdata: `rus`, `eng`, `deu`, `fra`, `chi_sim`, … — любые из репозитория. По умолчанию
  распознаются `rus` и `eng`.
- **Настройки.** `ocr` (`AMEMO_OCR`): `none` — не распознавать, `tesseract` — распознавать; не задано — Tesseract,
  если языковые данные найдены. `ocr_data` (`AMEMO_OCR_DATA`) — папка языковых данных; `ocr_languages`
  (`AMEMO_OCR_LANGUAGES`) — список языков (в окружении — через `+`, запятую или пробел). Системный Tesseract
  (`apt install tesseract-ocr-rus`, `brew install tesseract-lang`, `TESSDATA_PREFIX`) тоже подходит: он берётся,
  если в `ocr_data` нужных языков нет.
- **Кто ставит.** Только человек: модель на `amemo ocr install` и `remove` получает код 2 — это меняет установку.
- **Docker.** `AMEMO_OCR_LANGS="rus eng"` в `.env` (или `--build-arg OCR_LANGS="rus eng"`) — языки скачиваются
  при сборке образа; пусто — образ без OCR.
- **Проверка.** `amemo doctor` показывает строку OCR: режим, языки и папку; предупреждает, если `ocr = "tesseract"`,
  а данных нет.
- **Облако.** Облачное распознавание — позже: значение `ocr = "cloud"` зарезервировано и пока даёт ошибку
  «ещё не поддерживается».

## MCP

Сервер MCP даёт агенту 19 инструментов над теми же операциями, что HTTP API:

| Инструмент | Что делает |
|---|---|
| `amemo_search(query, kind?, limit?)` | Шаг 1: короткие находки `{ref, label, kind, status, snippet}` и `retrieval_id` |
| `amemo_similar(query \| ref, limit?)` | Похожие записи, в той же форме |
| `amemo_timeline(ref)` | Шаг 2: последние события записи и её соседи |
| `amemo_get(refs)` | Шаг 3: полные записи — тело, источники, статус, открытые пункты |
| `amemo_card(ref)` | Карточка сущности `amem.card/1` |
| `amemo_submit(proposals, links?, reason?)` | Запись пакета через `check.submit` |
| `amemo_helpful(retrieval_id, refs)` | Отметить атомы, которые помогли |
| `amemo_move(ref, folder)` | Переложить запись в существующую папку |
| `amemo_object_status(path)`, `amemo_mark_object(path, status, note?)` | Что из документа уже атомизировано |
| `amemo_review_claim`, `amemo_review_release`, `amemo_review_resolve` | Для смыслового проверяющего |
| `amemo_tasks(object?, limit?)` | Задачи агентам: свободные и взятые вами |
| `amemo_task_claim(task?, kind?)`, `amemo_task_release(task)`, `amemo_task_done(task, result?)`, `amemo_task_cancel(task)` | Взять задачу с арендой, вернуть, закрыть с итогом, отменить свою |
| `amemo_vocab(scheme)` | Коды словаря с подписями |

Поиск идёт в три шага, чтобы агент читал только нужное: `amemo_search` даёт короткие карточки, `amemo_timeline`
показывает, что вокруг находки, `amemo_get` отдаёт выбранные записи целиком. Текст, под который подходят несколько
записей без явного лидера, возвращается как `ambiguous: true` с кандидатами, а не первой попавшейся записью.

**Через stdio.** `amemo mcp` — одна сессия на процесс со своим маленьким пулом соединений. Claude Code:

```bash
claude mcp add amemo --env AMEMO_DSN=postgresql://amemo:amemo@127.0.0.1:5435/amemo -- amemo mcp --agent model:claude-code
```

или в `.mcp.json` проекта:

```json
{
  "mcpServers": {
    "amemo": {
      "command": "amemo",
      "args": ["mcp", "--agent", "model:claude-code"],
      "env": { "AMEMO_DSN": "postgresql://amemo:amemo@127.0.0.1:5435/amemo" }
    }
  }
}
```

Codex CLI, в `~/.codex/config.toml` (DSN — в `amemo.toml` или в окружении, не в этом файле):

```toml
[mcp_servers.amemo]
command = "amemo"
args = ["mcp", "--agent", "model:codex"]
env_vars = ["AMEMO_DSN", "AMEMO_CONFIG"]
```

**Через HTTP.** Запущенная служба отдаёт те же инструменты по `/mcp` (Streamable HTTP):

```bash
claude mcp add --transport http amemo http://127.0.0.1:8767/mcp --header "X-Amemo-Agent: model:claude-code"
```

```toml
[mcp_servers.amemo]
url = "http://127.0.0.1:8767/mcp"
http_headers = { "X-Amemo-Agent" = "model:codex" }
```

- **Всегда модель.** Клиент MCP пишет как `model:…`, и его записи идут через проверку. У stdio агент — из
  `--agent model:…` или окружения агента; у `/mcp` — из заголовка `X-Amemo-Agent`, иначе агент-модель токена,
  иначе `AMEMO_MODEL_AGENT` (`model:local`). `person:` не принимается.
- **Общая служба.** С `AMEMO_TOKENS` `/mcp`, как и API, требует `Authorization: Bearer <токен>`; токен только для
  чтения ищет, а инструменты записи отвечают `read_only`. Заголовок, который спорит с агентом-моделью токена,
  отвергается.
- **Полезность.** `amemo_helpful` отмечает атомы только из поиска той же сессии (у клиентов без сессий — того же
  агента и входа); чужой `retrieval_id` — `forbidden`.
- **Журнал запросов.** Явные поиски (`amemo search`, `amemo_search`, `amemo_similar`) пишут строку в
  `AMEMO_STATE/queries.jsonl`, как `/search` службы; шаги чтения — нет.

## Память агентов

`amemo install claude-code` и `amemo install codex` подключают amemo к агенту — глобально или с `--project DIR`.
`amemo uninstall …` убирает ровно установленное; `--dry-run` сначала показывает изменения.

| | Claude Code | Codex CLI |
|---|---|---|
| Сервер MCP | `claude mcp add --scope user` (или `~/.claude.json`); проект — `.mcp.json` | `[mcp_servers.amemo]` в `~/.codex/config.toml`; проект — `.codex/config.toml` |
| Хуки | `SessionStart`, `UserPromptSubmit`, `PreCompact` в `settings.json` | `SessionStart`, `UserPromptSubmit` в `hooks.json` |
| Навыки | `~/.claude/skills/amemo-*`; проект — `.claude/skills/` | `~/.agents/skills/`; проект — `.agents/skills/`, и блок в `AGENTS.md` |

- **Хуки.** `amemo hook SessionStart` добавляет 3–5 проверенных атомов о проекте (по имени корня git) и
  напоминание; `UserPromptSubmit` — уверенные находки по запросу («сначала amemo»); `PreCompact` просит сводку
  перечислить выводы, которые стоит записать. Хук читает базу напрямую, укладывается в 1,5 с и при любом сбое
  отвечает пусто с кодом 0. Текст из памяти приходит в рамке как данные со статусом проверки, а не как указания.
- **Навыки.** `amemo-remember` (записать 1–3 атома в конце задачи), `amemo-answer` (ответ по памяти со ссылками на
  источники), `amemo-verify` (смысловой проверяющий, уровень 5).
- **Кто пишет.** Установщик задаёт `AMEMO_AS_MODEL` серверу MCP и хукам: агент пишет как `model:claude-code` или
  `model:codex`, а не от вашего имени.
- **Правит только своё.** Ключи `amemo` и элементы хуков с `amemo hook` в JSON, блок `# amemo:begin … # amemo:end`
  в TOML, блок `<!-- amemo:begin … -->` в Markdown. Перед первой правкой файл копируется в `<файл>.amemo-backup`.
- **Codex.** Codex передаёт серверу MCP только переменные из `env_vars`; установщик перечисляет `AMEMO_DSN`,
  `AMEMO_CONFIG`, `AMEMO_STATE`, `PGPASSFILE` и `PGSERVICE` и никогда не пишет строку подключения в `config.toml`.
  Базу задавайте в `amemo.toml` через `amemo init --dsn …` (или в этих переменных). Файлы проекта Codex читает
  только у доверенного проекта.
- **Файлы проекта.** С `--project` в файлы идёт голая команда `amemo`, без пути этой машины, — их можно
  коммитить; `amemo` должен быть в `PATH` агента. Глобальная установка пишет полный путь.
- **Windows.** Команды хуков — строки оболочки POSIX (`AMEMO_AS_MODEL=… amemo hook …`): они работают в Linux, macOS
  и WSL2, но не в родных оболочках Windows. Используйте WSL2.
- **Проверка.** `amemo doctor` показывает, что установлено (глобально и для проекта текущей папки) и существует ли
  ещё его команда; затем `claude mcp list` или `codex mcp list` подтверждают, что агент видит сервер.

**Расписание `amemo-verify`.** Смысловой проверяющий — это агент, которого запускают по вашему расписанию,
например каждую ночь через cron:

```cron
# м ч д мес дн
30 3 * * *  cd ~/notes && claude -p "Use the amemo-verify skill: review up to 20 open semantic items." >> ~/.local/state/amemo/verify.log 2>&1
```

или таймером systemd пользователя:

```ini
# ~/.config/systemd/user/amemo-verify.service
[Service]
Type=oneshot
WorkingDirectory=%h/notes
ExecStart=/usr/bin/env claude -p "Use the amemo-verify skill: review up to 20 open semantic items."

# ~/.config/systemd/user/amemo-verify.timer
[Timer]
OnCalendar=*-*-* 03:30
Persistent=true
[Install]
WantedBy=timers.target
```

`systemctl --user enable --now amemo-verify.timer`. Агенту нужен сервер MCP amemo (`amemo install …`).

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
   распознаётся Tesseract через PyMuPDF, если OCR поставлен (`amemo ocr install rus eng` или системный
   Tesseract, см. [распознавание сканов](#распознавание-сканов-ocr)). Цитата, сверенная с распознанным текстом,
   получает замечание `info` `quote_ocr` и более мягкий порог нечёткости; без OCR о такой странице
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
- [x] **Служба HTTP:** `amemo serve` по [контракту v1](docs/api/http-v1.openapi.yaml)
- [x] **CLI и сервер MCP:** поиск в три шага, отметки полезности, вырезание `<private>`
- [x] **Память агентов:** хуки Claude Code, Codex CLI, `amemo install`, навыки ядра
- [x] **Запись из веба:** формы по шаблонам, свои виды, загрузка файлов, задачи агентам
- [x] **Веб-UI:** все экраны — на службе и на моках; сквозные проверки против службы
- [ ] **asearch:** поиск по файлам как плагин amemo

## Документация

| | |
|---|---|
| [Справочник библиотеки](docs/library.ru.md) | Модель данных, поиск, автопроверка, очередь, карточки, подборки, папки, бэкапы |
| [HTTP API v1](docs/api/) | Контракт OpenAPI между службой и веб-UI |
| [Манифест](docs/MANIFESTO.ru.md) | Зачем существует amemo и на чём он стоит |
| [Спецификации и планы](docs/superpowers/) | Как решали и строили каждый подпроект |

**Полезно знать**

- У текста два слота, `ru` и `en`; записи нужен хотя бы один, так что базу можно вести только по-английски, как
  английский образец. Подписи и фрагменты приходят на запрошенном языке — языке интерфейса (`Accept-Language`),
  `--lang` у CLI, `lang` у инструментов MCP, иначе `AMEMO_LANG` — а если его слот пуст, из другого. Полнотекстовый
  поиск ведёт `ru` русской конфигурацией, `en` — английской; необязательная локальная модель векторов
  многоязычная.
- Векторы локальные и необязательные: `pip install -e ".[embed]"` добавляет fastembed, а модель
  скачивается только с явного разрешения. `AMEMO_BACKEND=none` выключает смысловой канал, лексический
  поиск продолжает работать.
- Бэкапу нужен клиент PostgreSQL 18 (`pg_dump`, `pg_restore`, `psql`) в `PATH` или в папке `AMEMO_PG_BIN`.

## Разработка

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# тестовые базы: PostgreSQL 18 (порт 5433) и 16 (порт 5434)
docker compose --profile test up -d --wait db-test db-test-pg16

# запуск тестов (тестам бэкапа нужен клиент PostgreSQL 18)
.venv/bin/pytest -q
```

Другие порты или серверы задаются так: `AMEMO_TEST_DSNS="postgresql://…/test,postgresql://…/test"`.
Нет тестовой базы или клиента — это падение теста, а не пропуск. Если окружение выставляет `PYTHONPATH`
от других инструментов (например, ROS), он ломает автозагрузку плагинов pytest — тогда запускайте
`env -u PYTHONPATH .venv/bin/pytest -q`.

После правки `amemo/schema/amemo_v1.yaml` перегенерируйте модели:

```bash
.venv/bin/python tools/gen_schema.py          # пишет amemo/model_v1.py и JSON Schema
.venv/bin/python tools/gen_schema.py --check  # проверка в CI: сгенерированное актуально
```
Перед push — проверка на приватное: `git config core.hooksPath tools/hooks`; список образцов хук читает из `~/.config/amemo/private-patterns.txt` (вне репозитория).

Сообщения коммитов — по [Conventional Commits](https://www.conventionalcommits.org/) и на английском:
`type(scope): subject`, не длиннее 100 знаков, например `fix(service): reject NUL in parameters`. Тот же
`core.hooksPath` включает хук `commit-msg`, который проверяет это при коммите;
`python3 tools/check_commits.py --revs origin/main..HEAD` проверяет диапазон вручную.


Веб-UI лежит в [`web/`](web/) (React 19, HeroUI v3, TanStack). Там же — `npm run lint`, `npm test`
и `npm run e2e`.

## Участие

amemo делается открыто. Вопросы и обсуждения приветствуются. Перед большой правкой откройте, пожалуйста,
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

GNU Affero General Public License v3.0 (AGPL-3.0-only), см. [LICENSE.txt](LICENSE.txt).
© 2026 empty-complete.

amemo можно свободно использовать, изучать, менять и распространять. Кто распространяет изменённую версию или
запускает её как сервис для других людей по сети, обязан открыть полный исходный код на тех же условиях.

Пакеты домена в `amemo/packs` (словари и шаблоны) — это данные, они остаются под лицензией MIT и годятся для
повторного использования где угодно.

Коммерческая лицензия без условий AGPL (например, для закрытого облачного сервиса) — по договорённости с автором:
откройте issue на GitHub. Версии, выпущенные до перехода на AGPL, остаются доступны под MIT.

<p align="center"><sub>amemo — инструмент для того, чтобы хорошо помнить.</sub></p>
