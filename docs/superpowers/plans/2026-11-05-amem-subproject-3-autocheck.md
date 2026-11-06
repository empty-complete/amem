# amem — подпроект 3 «Автопроверка»: план реализации

> **Для исполнителей-агентов:** задачи выполняются через superpowers:subagent-driven-development — свежий субагент на задачу, ревью после каждой. Шаги — с флажками (`- [ ]`).

05.11.2026. Исполняет `docs/superpowers/specs/2026-11-05-amem-subproject-3-autocheck-design.md` (редакция 1 с правками по ревью).

**Цель:** `check.submit` — запись пакета через уровни 1–4 со статусами, итогами сверки и пунктами очереди (часть 3a); очередь с захватом, решением, аудитом, метриками и пересмотром при новой версии объекта (часть 3b).

**Архитектура:** пакет `amem/check/` (уровни, отчёт, шаблоны, числа, единицы), `amem/review.py` (очередь), `amem/extract.py` (xlsx/docx), миграция `0006_check.sql`. `records.commit` остаётся низкоуровневой записью; `submit` вызывает его внутри своей транзакции, где он становится точкой сохранения.

**Стек:** Python 3.11+, PostgreSQL 18/16, psycopg 3, LinkML → Pydantic, `ucumvert` + `pint` 0.25, `openpyxl`, `rapidfuzz`, PyMuPDF.

**Формат:** каждая задача — падающий тест → реализация → focused test → полный прогон → коммит. Красный тест не пропускается и не отключается. Если реализация упирается в противоречие спецификации, сначала правится спецификация (с причиной), затем план.

**Части и ветки:**
- **3a** — задачи 0–10, ветка `subproject-3-autocheck` от `main` (`4d66ce5`). После задачи 10 — ревью ветки, PR, CI, слияние.
- **3b** — задачи 11–13, ветка `subproject-3b-review-queue` от `main` после слияния 3a.

**Команды** (адреса тестовых баз PostgreSQL 18 и 16 — в `AMEM_TEST_DSNS`, клиент PostgreSQL 18 — в `AMEM_PG_BIN`, как в README):

```bash
cd ~/projects/amem
export AMEM_TEST_DSNS="postgresql://test:test@127.0.0.1:<порт pg18>/test,postgresql://test:test@127.0.0.1:<порт pg16>/test"
export AMEM_PG_BIN=<каталог bin клиента PostgreSQL 18>
env -u PYTHONPATH .venv/bin/pytest -q -p no:cacheprovider
.venv/bin/python tools/gen_schema.py --check
```

**Правила:**
- код возврата pytest проверяется явно (`; echo "exit=$?"` или `set -o pipefail`), а не по коду `tail`;
- тестовые данные нейтральны: никаких названий компаний, реальных проектов и путей пользователя;
- сообщение коммита начинается с `check:` или `docs:`, называет число новых тестов и заканчивается строкой `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

## Карта файлов

| Файл | Назначение |
|---|---|
| `pyproject.toml` | `ucumvert==0.3.2`, `pint>=0.25,<0.26`, `openpyxl>=3.1`; `requires-python = ">=3.11"` |
| `amem/schema/amem_v1.yaml` | Перечни `CheckCode`, `ReviewReason`, `ReviewItemState`, `VerificationMethod`, `VerificationOutcome`, `HighRiskRule`; `Template.high_risk`; классы `CheckIssue`, `CheckReport`, `ReviewItem`, `Verification` |
| `amem/model_v1.py`, `amem/schema/*.json` | Генерируются `tools/gen_schema.py` |
| `amem/packs/core/pack.yaml`, `templates/decision.yaml` | Ядро 1.1.0, шаблон `decision` с `high_risk: [always]` |
| `amem/packs.py` | Проверка шаблонов при загрузке |
| `amem/sql/0006_check.sql` | `template_active`, `review_item`, `verification`, триггеры, индексы, сброс кэша страницы 0 |
| `amem/db.py` | `load_vocab` переписывает `template_active` |
| `amem/backup.py` | `COUNTED` + `review_item`, `verification` |
| `amem/extract.py` | Текст xlsx/xlsm и docx |
| `amem/sources.py` | `extract_pages` передаёт xlsx/docx в `extract` |
| `amem/check/__init__.py` | `Proposal`, `Submitted`, `CheckError`, `submit` |
| `amem/check/report.py` | `Issue`, `Report` |
| `amem/check/templates.py` | `active`, `rules_for`, `Rules` |
| `amem/check/units.py` | `is_ucum`, `convert` |
| `amem/check/numbers.py` | `atom_numbers`, `text_numbers`, `missing` |
| `amem/check/level1.py` … `level4.py` | Уровни |
| `amem/review.py` | 3a: `insert_item`, `in_audit`, `AUDIT_RATE`; 3b: `claim`, `release`, `resolve`, `enqueue`, `items`, `stats`, `on_new_version` |
| `amem/objects.py` | 3b: `ingest` вызывает `review.on_new_version` |
| `tests/check_support.py` | Построители тел, источников и документов для тестов автопроверки |
| `tests/packs/check/` | Пакет для тестов: виды `rule` (`numeric`) и `idea`; величины `length`, `pressure`, `temperature` с диапазонами |
| `tests/test_check_*.py`, `tests/test_extract.py`, `tests/test_review*.py` | Тесты задач |
| `README.md`, `README.ru.md` | Раздел «Автопроверка» |

Публичные функции принимают соединение `db.connect` (autocommit). Время в базе — `timestamptz`, в ответах — ISO 8601. Ссылки — `atm:`, `ent:`, `obj:`.

---

## Часть 3a

### Task 0: Исходная точка

- [ ] **Step 1.** Ветка `subproject-3-autocheck` уже создана, спецификация закоммичена. Проверить `git status` (чисто, кроме этого плана) и `git log --oneline -3`.
- [ ] **Step 2.** Тестовые базы PostgreSQL 18 и 16 с pgvector доступны по `AMEM_TEST_DSNS`. Это `docker compose --profile test up -d --wait db-test db-test-pg16` или свои контейнеры `pgvector/pgvector:pg18` и `:pg16` с пользователем, паролем и базой `test`.
- [ ] **Step 3.** Полный прогон и `gen_schema.py --check`. Эталон — 916 тестов, все зелёные. Фактическое число записать в `.superpowers/sdd/progress.md` (папку игнорирует git). План закоммитить: `docs: план подпроекта 3`.

---

### Task 1: Зависимости, схема LinkML и шаблон `decision`

**Files:** `pyproject.toml`, `amem/schema/amem_v1.yaml`, сгенерированные `amem/model_v1.py` и JSON Schema, `amem/packs/core/pack.yaml`, `amem/packs/core/templates/decision.yaml`, `tests/test_check_schema.py`, тесты, сверяющие версию ядра или число его шаблонов.

- [ ] **Step 1: зависимости.** В `pyproject.toml`:
  - `requires-python = ">=3.11"`;
  - в `dependencies` — `"ucumvert==0.3.2"`, `"pint>=0.25,<0.26"`, `"openpyxl>=3.1"`.

  Установить: `.venv/bin/pip install -e '.[dev]'`. Проверка: `.venv/bin/python -I -c "from ucumvert import PintUcumRegistry; PintUcumRegistry()"` проходит без ошибки. С pint 0.26 она падает на алиасе `i.U.` — поэтому и нужна верхняя граница.
- [ ] **Step 2: падающие тесты** `tests/test_check_schema.py`:
  - `model_v1.CheckCode` содержит ровно коды таблицы спецификации разд. 2.2 — список в тесте копирует таблицу;
  - перечни очереди:
    - `ReviewReason` = `semantic, warning, high_risk, semantic_doubt, edit, source_changed, audit, calibration`;
    - `ReviewItemState` = `queued, claimed, done, obsolete`;
    - `VerificationMethod` = `llm_judge, human`;
    - `VerificationOutcome` = `confirmed, partial, refuted, uncertain`;
    - `HighRiskRule` = `always, numeric`;
  - `Template.model_validate_json` принимает `high_risk: ["always"]` и отклоняет `["sometimes"]`;
  - `CheckReport` в строгом режиме принимает пример отчёта из разд. 2.3, а `CheckIssue` отклоняет неизвестный `code` и `level: 5`;
  - у ядра `load_pack(CORE_PACK).version == "1.1.0"`, шаблон `decision` есть, `applies_to == "decision"`, `high_risk == [always]`.
- [ ] **Step 3: схема.** В `amem_v1.yaml` добавить:
  - перечни — у каждого значения `label_ru`, `label_en`, `definition_ru`, как у `SourceVerdict`;
  - `Template.high_risk` (`range: HighRiskRule`, `multivalued: true`);
  - классы:

  ```yaml
  CheckIssue:
    attributes:
      level: {range: integer, required: true, minimum_value: 1, maximum_value: 4}
      severity: {range: Severity, required: true}
      code: {range: CheckCode, required: true}
      where: {required: true}
      message: {required: true}
      details: {range: Any}
  CheckReport:
    attributes:
      format: {required: true, pattern: '^amem\.check/1$'}
      levels: {range: Any, required: true}
      issues: {range: CheckIssue, multivalued: true, inlined_as_list: true}
      degraded: {range: Any, multivalued: true}
      templates: {multivalued: true}
      records: {range: Any, multivalued: true}
  ```

  Ещё два класса: `ReviewItem` (поля таблицы `review_item` из разд. 8.1, ревизия — одно поле `revision_id`) и `Verification` (поля `verification`). Запустить `.venv/bin/python tools/gen_schema.py`; `--check` зелёный.
- [ ] **Step 4: ядро.** В `pack.yaml` — `version: 1.1.0`, в описании упомянут `decision`. Новый `templates/decision.yaml`:

  ```yaml
  code: decision
  version: 1.0.0
  target: atom
  applies_to: decision
  description: {ru: "Решение: всегда к человеку — его последствия дороже ошибки проверки."}
  high_risk: [always]
  ```
- [ ] **Step 5.** Focused: `tests/test_check_schema.py tests/test_v1_templates.py tests/test_packs.py tests/test_v1_generated.py`; затем полный прогон. Тесты, сверявшие версию ядра `1.0.0` или число его шаблонов, обновить по смыслу. Commit: `check: схема отчёта и очереди, high_risk у шаблонов, шаблон decision в ядре 1.1.0`.

---

### Task 2: Миграция 0006 и активные шаблоны

**Files:** `amem/sql/0006_check.sql`, `amem/db.py`, `amem/backup.py`, `tests/test_check_sql.py`, `tests/test_sql_schema.py`, `tests/test_db.py` (список миграций).

- [ ] **Step 1: падающие тесты** `tests/test_check_sql.py` (фикстура `pg`, `db.prepare`):
  - **таблицы:** `template_active`, `review_item`, `verification` есть. `template_active` после `prepare` содержит `has_label`, `has_source`, `has_value`, `decision` с версиями из пакета ядра;
  - **вставка:** пункт `review_item` с `record_id` чужой ревизии отвергается триггером (в тексте ошибки — `amem:`); пункт в состоянии не `queued` — тоже;
  - **переходы:** `queued→claimed→queued→claimed→done` проходит. Отвергаются: `done→queued`, `obsolete→claimed`, смена `reason`, `details`, `created_at`. `DELETE` и `TRUNCATE` обеих таблиц отвергаются;
  - **уникальность:** два открытых пункта с одной ревизией и причиной нарушают уникальность; после `done` первого второй вставляется;
  - **`verification`:** отвергаются `llm_judge` без `confidence`, `confidence = 1.5`, `human` от агента `model:`, а также любой `UPDATE`;
  - **сброс кэша:** база мигрирована до 0005 — `monkeypatch.setattr(db, "SQL_DIR", tmp)` с копиями 0001–0005. В неё вставлены объекты `a.docx`, `b.xlsx`, `c.pdf` с версиями и строками `object_text` страницы 0. После `db.migrate` с настоящим `SQL_DIR` страница 0 у docx и xlsx удалена, у pdf — осталась.
- [ ] **Step 2: миграция** `0006_check.sql` (совместима с PostgreSQL 16):

  ```sql
  CREATE TABLE template_active (
      code     text PRIMARY KEY,
      version  text NOT NULL,
      FOREIGN KEY (code, version) REFERENCES template (code, version)
  );

  CREATE TABLE review_item (
      id                  uuid PRIMARY KEY CHECK (id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab]'),
      target              text NOT NULL CHECK (target IN ('atom', 'entity')),
      record_id           uuid NOT NULL,
      atom_revision_id    uuid REFERENCES atom_revision (id),
      entity_revision_id  uuid REFERENCES entity_revision (id),
      reason              text NOT NULL CHECK (reason IN ('semantic', 'warning', 'high_risk', 'semantic_doubt',
                              'edit', 'source_changed', 'audit', 'calibration')),
      state               text NOT NULL CHECK (state IN ('queued', 'claimed', 'done', 'obsolete')),
      changeset_id        uuid REFERENCES changeset (id),
      details             jsonb NOT NULL DEFAULT '{}'::jsonb,
      created_at          timestamptz NOT NULL,
      created_by          text NOT NULL REFERENCES agent (id),
      claimed_by          text REFERENCES agent (id),
      claimed_until       timestamptz,
      closed_at           timestamptz,
      CHECK ((atom_revision_id IS NULL) <> (entity_revision_id IS NULL)),
      CHECK ((target = 'atom') = (atom_revision_id IS NOT NULL)),
      CHECK (state <> 'claimed' OR (claimed_by IS NOT NULL AND claimed_until IS NOT NULL)),
      CHECK (state <> 'queued' OR (claimed_by IS NULL AND claimed_until IS NULL)),
      CHECK ((state IN ('done', 'obsolete')) = (closed_at IS NOT NULL))
  );
  CREATE UNIQUE INDEX review_item_open ON review_item (coalesce(atom_revision_id, entity_revision_id), reason)
      WHERE state IN ('queued', 'claimed');
  CREATE INDEX review_item_state ON review_item (state, reason, created_at);
  CREATE INDEX review_item_record ON review_item (record_id);
  CREATE INDEX changeset_state_created ON changeset (state, created_at);

  CREATE TABLE verification (
      id              uuid PRIMARY KEY CHECK (id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab]'),
      review_item_id  uuid NOT NULL UNIQUE REFERENCES review_item (id),
      method          text NOT NULL CHECK (method IN ('llm_judge', 'human')),
      outcome         text NOT NULL CHECK (outcome IN ('confirmed', 'partial', 'refuted', 'uncertain')),
      confidence      double precision CHECK (confidence >= 0 AND confidence <= 1),
      agent           text NOT NULL REFERENCES agent (id),
      note            text,
      created_at      timestamptz NOT NULL,
      CHECK (method <> 'llm_judge' OR confidence IS NOT NULL),
      CHECK ((method = 'human') = (agent LIKE 'person:%'))
  );
  ```

  Триггер `amem_review_item_check()` — BEFORE INSERT OR UPDATE OR DELETE:
  - **DELETE** — `RAISE EXCEPTION 'amem: пункт очереди нельзя удалить'`;
  - **INSERT** — `state = 'queued'`, `record_id` совпадает с `atom_id` / `entity_id` ревизии;
  - **UPDATE** — `to_jsonb(NEW) - 'state' - 'claimed_by' - 'claimed_until' - 'closed_at'` совпадает с тем же у OLD; `OLD.state` не `done` и не `obsolete`; переход `(OLD.state, NEW.state)` — из разрешённых: `queued→claimed`, `claimed→claimed`, `claimed→queued`, `queued|claimed→done|obsolete`.

  У `verification` — `amem_forbid_change` на UPDATE и DELETE. TRUNCATE запрещён у обеих таблиц тем же `amem_forbid_change`, как в 0002. Последняя строка миграции — сброс кэша:

  ```sql
  DELETE FROM object_text t USING object_version v, object o
   WHERE t.digest = v.digest AND o.id = v.object_id AND t.page = 0
     AND lower(o.original_name) ~ '\.(docx|xlsx|xlsm)$';
  ```
- [ ] **Step 3: `load_vocab`.** После цикла пакетов: `DELETE FROM template_active`, затем `INSERT` пары `(code, version)` каждого шаблона загруженных пакетов. Тест: пакет-пример через `AMEM_PACKS` — `idea` активен; повторный `prepare` без `AMEM_PACKS` — `idea` неактивен, а строка в `template` осталась.
- [ ] **Step 4: перечни и бэкап.**
  - `tests/test_sql_schema.py` сверяет новые CHECK с `ReviewReason`, `ReviewItemState`, `VerificationMethod`, `VerificationOutcome`; `target` заносится в известные служебные списки.
  - `backup.COUNTED` += `"review_item", "verification"`.
  - Список миграций в `tests/test_db.py` пополняется `0006_check.sql`.
- [ ] **Step 5.** Focused, полный прогон (бэкап-тесты тоже: они считают строки). Commit: `check: миграция 0006 — очередь, вердикты, активные шаблоны, сброс кэша docx/xlsx`.

---

### Task 3: Шаблоны — проверка при загрузке и сведение

**Files:** `amem/packs.py`, `amem/check/__init__.py` (пока только докстринг), `amem/check/templates.py`, `tests/test_check_templates.py`, `tests/test_v1_templates.py`, `tests/packs/check/`.

- [ ] **Step 1: тестовый пакет** `tests/packs/check/`. Без сведений о реальном мире: величины физические, подписи нейтральные.
  - `pack.yaml` — `name: check`, `version: 1.0.0`;
  - `vocab/kind.yaml` — `rule` («правило») и `idea`;
  - `vocab/property.yaml`:
    - `length` — `unit: m`, `plausible_min: 0`, `plausible_max: 1000`;
    - `pressure` — `unit: kPa`, от `0` до `100`;
    - `temperature` — `unit: Cel`, от `-80` до `200`;
  - `templates/rule.yaml`:
    - `applies_to: rule`, `extends: [has_label]`, `high_risk: [numeric]`;
    - правило `{path: content.values, required: true, severity: violation}`;
    - `links: {allowed: [refines, see_also, about], required: [{rel: about, to_classes: [document], severity: warning}]}`;
  - `templates/idea.yaml` — `applies_to: idea`, правило `{path: body, required: true, severity: warning}`.
- [ ] **Step 2: падающие тесты загрузки** (`tests/test_check_templates.py`, без базы). `load_packs` с временным пакетом отвергает `PackError`, и в тексте ошибки есть имя файла. Случаи:
  - `extends` на несуществующий шаблон;
  - `extends` на шаблон другого `target`;
  - цикл `a→b→a`;
  - `applies_to` с кодом, которого нет в словарях пакетов;
  - путь `content.vals`;
  - `selector_types: [nope]`;
  - `entity_classes: [nope]`;
  - два шаблона с одним `code` в разных пакетах;
  - два шаблона с одной парой (`target`, `applies_to`).

  Логика путей переезжает из `tests/test_v1_templates.py::_resolve` в `packs._check_path(path, target)`. Тест-файл остаётся, но вызывает функцию пакета.
- [ ] **Step 3: падающие тесты сведения** (`pg`, `prepare` с `AMEM_PACKS=tests/packs/check`):

  ```python
  rules = templates.rules_for(templates.active(pg), "atom", "rule")
  assert rules.templates == ("has_label@1.0.0", "has_source@1.0.0", "has_value@1.0.0", "rule@1.0.0")
  assert rules.high_risk == frozenset({"numeric"})
  assert rules.allowed == frozenset({"refines", "see_also", "about"})
  assert rules.fields["content.values"]["severity"] == "violation"
  ```

  Ещё случаи:
  - правило потомка с тем же `path` заменяет правило интерфейса — временный пакет с правилом `label` и `severity: warning`;
  - из двух несвязанных интерфейсов с одним путём действует тот, чей код больше;
  - у `decision` — `high_risk == {"always"}`;
  - у вида без своего шаблона — только интерфейсы;
  - `extends` раскрывается рекурсивно слева направо; шаблон, встретившийся в цепочке повторно, применяется один раз.
- [ ] **Step 4: реализация** `amem/check/templates.py`:

  ```python
  @dataclass(frozen=True)
  class Rules:
      templates: tuple[str, ...]                 # code@version в порядке применения
      fields: dict[str, dict]                    # path → правило FieldRule (json), сведённое по path
      allowed: frozenset[str] | None             # None — исходящие связи не ограничены
      required_links: tuple[dict, ...]           # RequiredLink (json), сведённые по rel
      high_risk: frozenset[str]

  def active(conn) -> dict[str, dict]:
      """code → тело шаблона (с version) из template_active ⋈ template."""

  def rules_for(active: dict[str, dict], target: str, code: str) -> Rules:
      """Интерфейсы target по возрастанию кода, затем шаблон applies_to = code; extends — слева направо."""
  ```

  Правила сведения: `links.allowed` — у последнего задавшего его шаблона; `required` — по `rel`; `high_risk` — объединение.
- [ ] **Step 5.** Focused, полный прогон. Commit: `check: шаблоны проверяются при загрузке пакетов и сводятся по наследованию`.

---

### Task 4: Отчёт, единицы и уровень 1

**Files:** `amem/check/report.py`, `amem/check/units.py`, `amem/check/level1.py`, `tests/check_support.py`, `tests/test_check_level1.py`, `tests/test_check_units.py`.

- [ ] **Step 1: отчёт.**

  ```python
  @dataclass
  class Issue:
      level: int; severity: str; code: str; where: str; message: str; details: dict = field(default_factory=dict)

  class Report:
      def add(self, level, severity, code, where, message, **details) -> Issue   # code ∉ CheckCode → AssertionError
      def violations(self) -> list[Issue]
      def for_label(self, label) -> list[Issue]       # where == label или начинается с f"{label}:"
      def as_json(self, *, levels: dict, records: list, templates: list, degraded: list) -> dict   # amem.check/1
  ```

  Тест: результат `as_json` после `json.dumps` проходит `model_v1.CheckReport.model_validate_json(..., strict=True)`.
- [ ] **Step 2: единицы** (`tests/test_check_units.py`, без базы).
  - `is_ucum` даёт True для `kPa`, `W/(m2.K)`, `W/(m2.Cel)`, `Cel`, `1`, `%`, `mm`, `kg/m3`, `Pa.s`, `[degF]` и False для `кПа`, `KPA`, `m/s/`, `""`.
  - `convert(0.38, "kPa", "Pa") == 380`, `convert(20, "Cel", "K") == 293.15` (с точностью 1e-9), `convert(1, "m", "kg") is None`, `convert(1, "W/(m2.Cel)", "W/(m2.K)") is None` — смещённая шкала.

  Реализация:
  - `ucumvert.get_ucum_parser()` и `PintUcumRegistry()` — под `functools.cache`;
  - `is_ucum` — только `parser.parse`;
  - `convert` ловит исключения `lark` и `pint` и возвращает `None`.
- [ ] **Step 3: падающие тесты уровня 1** (`tests/test_check_level1.py`, `pg` + `prepare` с тестовым пакетом). Построители в `tests/check_support.py`:

  ```python
  def atom(label, kind="fact", **fields) -> dict: ...
  def entity(label, cls="document", **fields) -> dict: ...
  def source_md(path, quote=None, **kw) -> dict: ...
  def source_pdf(path, page, quote, **kw) -> dict: ...
  def value(prop, amount, unit, **kw) -> dict: ...
  ```

  Каждый случай даёт один код с точным `where`:
  - **схема и коды:** нет `label` → `schema`; `kind: "nope"` → `unknown_code`; селектор `{"type": "pagee"}` внутри `refined_by` → `unknown_code`;
  - **ссылки:** `about: ["ent:missing_key"]` → `ref_unknown`; `@b` на запись пачки находится;
  - **шаблоны:**
    - `rule` без `content.values` → `template` (violation) с `details.template == "rule@1.0.0"`;
    - `idea` без `body` → `template` (warning);
    - проверяются `selector_types` через `refined_by`, `entity_classes` (`about` на `@имя` сущности другого класса), `min_count`;
  - **величины:** `unit: "кПа"` → `ucum` (violation от `has_value`); `amount` без `unit` → `unit_required`; `lower_bound > upper_bound` и `amount` вне границ → `bounds_order`;
  - **связи:**
    - `rule → depends_on` → `link_not_allowed`;
    - `rule` без `about` на документ → `link_required` (warning); с `about` на `@doc` класса `document` замечания нет;
    - связь с концами не из `pairs` → `link_pair`;
  - **статус:** правка записи `deprecated` → `retired_record`.
- [ ] **Step 4: реализация** `level1.check(conn, proposals, links, report) -> Batch`:

  ```python
  @dataclass
  class Prepared:
      label: str                     # @имя или items[i]
      target: str
      payload: dict                  # входное тело; уровень 2 заменит его разобранным
      record_id: uuid.UUID | None
      code: str | None               # kind / entity_class
      status: str | None             # статус существующей записи при чтении (не под блокировкой)
      rules: Rules | None
      ok: bool                       # тело разобралось — дальше идти можно

  @dataclass
  class Batch:
      items: list[Prepared]
      links: list[dict]
      refs: dict[str, tuple[str, str | None]]      # @имя → (target, код)
      templates: tuple[str, ...]                   # все применённые code@version
  ```

  - **разбор** — `model_v1.AtomPayload.model_validate_json(json.dumps(payload), strict=True)`; каждая ошибка Pydantic — отдельный `schema` с `where = f"{label}: {loc}"`;
  - **правила полей** — через `canon.values_at`;
  - **ссылки на существующие записи** — `atm:` или `ent:` с UUID или ключом → `SELECT id, kind|entity_class, status FROM atom|entity WHERE id = … | key = …`.
- [ ] **Step 5.** Focused, полный прогон. Commit: `check: отчёт, UCUM и уровень 1 — схема, коды, шаблоны, жёсткие правила, концы связей`.

---

### Task 5: Текст xlsx и docx

**Files:** `amem/extract.py`, `amem/sources.py`, `tests/test_extract.py`, `tests/samples.py`.

- [ ] **Step 1: построители образцов** в `tests/samples.py`.
  - `make_xlsx(path, sheets: dict[str, list[list]], formats: dict | None = None)` — через `openpyxl.Workbook`; `formats` задаёт `number_format` ячеек, например `{("Лист", "B2"): "0.00"}`.
  - `make_docx(path, blocks: list)` — zip с минимальными `[Content_Types].xml`, `_rels/.rels` и `word/document.xml`. Виды блоков:
    - строка — абзац;
    - `("table", rows)` — таблица;
    - `("page",)` — `w:br w:type="page"`;
    - `("rendered",)` — `w:lastRenderedPageBreak` в начале следующего абзаца;
    - `("del", text)` — `w:del/w:r/w:delText`;
    - `("ins", text)` — вставка;
    - `("doctype",)` — `<!DOCTYPE …>` в начале XML.

  Старый `скан.docx` (не zip) остаётся и по-прежнему без текста.
- [ ] **Step 2: падающие тесты** `tests/test_extract.py`.
  - **xlsx:**
    - два листа → две страницы; первая строка страницы — имя листа; ячейки через табуляцию;
    - числа: значение `0.187` в формате `0.00` → `0.19`; без формата → `0.187`; `0.18700000000000003` без формата → `0.187`; `12.0` → `12`; `0.05` в формате `0%` → `5%`;
    - дата → `2026-01-31`; `True` → `TRUE`; перевод строки в ячейке → пробел;
    - пустые строки пропущены; формула без сохранённого значения → пустая ячейка; скрытый лист входит;
    - битый файл → `None`.
  - **docx:**
    - абзацы и таблица идут в порядке тела; `w:tab` → `\t`; `del` не входит, `ins` входит;
    - `page` и `rendered` начинают новую страницу; `page`, сразу за ним `rendered` — одна новая страница, а не две; без разрывов — одна страница;
    - пустой документ → `None`; `doctype` → `None`; `document.xml` больше предела (константу подменить) → `None`.
  - **`sources.extract_pages`:** `.xlsx`, `.xlsm`, `.docx` уходят в `extract`; `.doc` и `.pptx` → `None`.
  - **`objects.text`:** для docx отдаёт страницы и кэширует их по `digest`.
- [ ] **Step 3: реализация** `amem/extract.py`:

  ```python
  MAX_XML_BYTES = 256 * 2**20
  MAX_TEXT_CHARS = 50_000_000
  W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

  def xlsx_pages(file: Path) -> list[str] | None: ...
  def docx_pages(file: Path) -> list[str] | None: ...
  def _cell_text(value, number_format: str) -> str: ...      # разд. 9.1 спецификации
  ```

  - **docx, чтение:** `zf.open("word/document.xml")` читается блоками до `MAX_XML_BYTES + 1` — больше предела → `None`; `<!DOCTYPE` в первых 4 КиБ → `None`; разбор — `ElementTree.fromstring`.
  - **docx, обход:** рекурсивный, пропускает `w:del`, `w:delText`, `w:instrText`. Новая страница — только если на текущей уже есть текст.
  - **Ошибки** `zipfile.BadZipFile`, `KeyError`, `ElementTree.ParseError` и `InvalidFileException` из `openpyxl` → `None`.
  - **В `sources.extract_pages`:** `.xlsx` и `.xlsm` → `extract.xlsx_pages`, `.docx` → `extract.docx_pages`.
  - **Докстринг `sources.py`:** `no_text` больше не упоминает `.docx`. Комментарий о проверке локаторов («… 19 из 20 локаторов базы») переписать нейтрально: «проверено на двух сводах правил: верные страницы почти для всех локаторов».
- [ ] **Step 4.** Focused, полный прогон. `test_objects.py` и `test_sources.py` проверяют `скан.docx`: он не zip и остаётся `None`. Commit: `check: текст xlsx и docx — лист и страница Word как страницы, число как в ячейке`.

---

### Task 6: Числа

**Files:** `amem/check/numbers.py`, `tests/test_check_numbers.py` (без базы).

- [ ] **Step 1: падающие тесты.**
  - **`atom_numbers(payload)`** — тройки `(путь, Decimal, из_условия)`:
    - пути: `content.values[0].amount`, `content.values[0].lower_bound`, `content.values[0].qualifiers[1].upper_bound` (из условия), `qualifiers[0].amount` (из условия), `content.table.rows[2][1]`;
    - `True` в ячейке — не число; строка `"0,5"` в ячейке — не число; формулы пропущены.
  - **`text_numbers(text)`** содержит:
    - разделители: `0,17` и `0.17` → `0.17`; `1 200`, `1 200`, `1 200` → `1200`;
    - знак: `−5`, `-5`, `–5` в начале строки, после пробела или после `(` → `-5`, но не `5`; «5–10» и «5 – 10» → `5`, `10` и `-10`; «– 10» → `10` и `-10`;
    - неоднозначные записи: `1,200` → и `1.2`, и `1200`; `10 200` → и `10200`, и `10`, и `200`;
    - `1,5e-3` → `0.0015`; `12%` → `12`.
  - **`missing(numbers, fragments)`:**
    - пустой список, если каждое число есть хотя бы в одном фрагменте; иначе — ненайденные тройки;
    - float `0.3` в атоме находит `0,30` в тексте.
- [ ] **Step 2: реализация.**
  - Нормализация текста: NFC; ` `, ` `, ` ` → пробел.
  - Два прохода регулярными выражениями: с группами разрядов (`\d{1,3}(?: \d{3})+`) и без групп (`\d+`). Дробная часть — `[.,]\d+`, экспонента — `[eE][-+−]?\d+`.
  - Знак — по разд. 4.5 спецификации:
    - вплотную к цифре и после не-цифры — только отрицательное;
    - после цифры (с пробелами или без) или с пробелом перед цифрой — оба значения.
  - Дробная часть ровно из трёх цифр даёт ещё и значение «тысячи».
  - Сравнение — множества `Decimal`, у чисел JSON — `Decimal(str(x))`.
- [ ] **Step 3.** Focused, полный прогон. Commit: `check: числа атома и текста — запятая, разряды, минус и тире диапазона`.

---

### Task 7: Уровень 2 — источники

**Files:** `amem/check/level2.py`, `tests/test_check_level2.py`, `tests/check_support.py`.

- [ ] **Step 1: падающие тесты** (`pg`, `docs`, `ObjectStore(tmp_path / "objects")`). Документы: `SP_PAGES` (PDF), заметка `.md`, xlsx с листом «Нагрузки», docx на две страницы.
  - **Разбор:**
    - путь на несуществующий файл → `source_unresolved` с `where = "@a: sources[0]"`;
    - два плохих источника → два замечания;
    - `object` с несуществующей версией → `version_missing`; с чужим `digest` → `digest_mismatch`.
  - **PDF:** без `page` → `pdf_page_required`; без цитаты или с цитатой «0,30 кПа» короче `MIN_QUOTE` → `pdf_quote_required`.
  - **Цитата:**
    - на указанной странице → `ok`, замечаний нет;
    - на соседней → `moved`, страница исправлена, info `page_moved`;
    - с опечаткой → `quote_fuzzy`, `details.anchor` — текст документа;
    - чужая → `quote_not_found`.
  - **Без цитаты:**
    - `.md` с селектором `heading` → `by_locator` или `ok`, без замечаний;
    - docx в одну страницу без цитаты и локатора → `unresolved` и `place_unresolved`, а не `ok`.
  - **xlsx:** селектор `sheet: "Нагрузки"` без цитаты → `by_locator`, страница листа; цитата из строки листа → `ok`.
  - **Числа:**
    - `w0 = 0,30 кПа` на странице 2; атом с `amount 0.3` и цитатой со страницы 2 → замечаний нет;
    - тот же атом с источником на странице 3 и цитатой со страницы 3 → `number_not_found` (violation);
    - то же с `role: derived` → warning;
    - число только в `qualifiers` и не найдено → warning;
    - селектор `page: "2–3"`, цитата со страницы 3, число на странице 2 → найдено.
  - **Без текста:**
    - сайт (`objects.web`) → `external` и warning `external_source`;
    - файл без текста (`скан.docx`) → `no_text`, warning, а у атома с числом ещё info `numbers_unchecked`.
  - **Сбои:** `sources.extract_pages` подменён и бросает `RuntimeError` → `error` и warning `source_error`; `FileNotFoundError` копии → наружу уходит `StoreError`.
  - **Редакция:** есть сущность класса `edition` с источником этого PDF, у атома нет `edition` → в теле появилась `edition: ent:<id>` и info `edition_filled`. Две такие сущности → не подставлено.
  - **Сущность:**
    - цитата не найдена → warning `quote_not_found`;
    - PDF без страницы — замечания нет;
    - итоги `fuzzy` и `not_found` записываются.
- [ ] **Step 2: реализация.**

  ```python
  @dataclass
  class SourceCheck:
      position: int
      verdict: str | None
      page: int | None
      anchor: str | None
      fragments: list[str]       # страницы для сверки чисел

  @dataclass
  class Place:
      page: int | None           # ожидаемая страница
      pages: list[int]           # страницы диапазона селектора page
      locator: str
      quote: str
      sheet: str | None

  def place(selectors: list[dict], quote: str | None) -> Place
  def check(conn, store, docs, batch, report, *, agent) -> dict[str, list[SourceCheck]]   # label → итоги
  ```

  - Источники разбираются по одному: `objects.resolve_sources(conn, store, docs, {"sources": [s]}, agent=…)`.
  - Итоги и важность — по разд. 4.3 спецификации, селекторы — по разд. 4.2: лист ищется по первой строке страниц, сравнение — NFC и `casefold`.
  - PDF — `media_type == "application/pdf"` или имя на `.pdf`.
  - Одностраничное `ok` без цитаты принимается только у `.md` и `.txt`.
  - Тест: каждое значение `verdict`, которое может вернуть уровень 2, входит в `model_v1.SourceVerdict`.
- [ ] **Step 3.** Focused, полный прогон. Commit: `check: уровень 2 — разбор источников, цитата и место, числа во фрагменте, подстановка редакции`.

---

### Task 8: Уровень 3 — здравый смысл

**Files:** `amem/check/level3.py`, `tests/test_check_level3.py`.

- [ ] **Step 1: падающие тесты** (`pg`, тестовый пакет с величинами; атомы-соперники записаны через `records.commit` с `about` на одну сущность).
  - **Диапазон и единицы:** `pressure 150 kPa` → `out_of_range`; `pressure 0.05 MPa` (это 50 kPa) — замечания нет; `pressure 3 m` → `unit_mismatch`; `temperature -100 Cel` → `out_of_range`.
  - **Словарь величин:** `velocity` (нет в словаре) при загруженном словаре `property` → `unknown_property`; без пакета величин (только ядро) — замечания нет.
  - **Согласие** — соперник `pressure 0.3 kPa` о той же сущности:
    - новый `0.38 kPa` → `conflict`, `details.atoms == ["atm:…"]`;
    - новый `300 Pa` — замечания нет: после перевода это то же значение;
    - замечания нет и при:
      - других уточнениях (`qualifiers` с другим `value_text`);
      - непересекающихся сроках;
      - другой сущности;
      - соперник со статусом `rejected`;
    - соперник внутри пачки → `conflict`;
    - атом без `about` на согласие не проверяется.
- [ ] **Step 2: реализация** `level3.check(conn, batch, report) -> dict[str, list[str]]` — label → риски, здесь только `conflict`.

  Соперники:

  ```sql
  SELECT c.atom_id, c.payload FROM atom_about ab
    JOIN atom_current c ON c.id = ab.revision_id JOIN atom a ON a.id = c.atom_id
   WHERE ab.entity_id = ANY(%s) AND a.status = ANY(%s)
  ```

  Уточнения сравниваются как множества строк `json.dumps(…, sort_keys=True, ensure_ascii=False)`.
- [ ] **Step 3.** Focused, полный прогон. Commit: `check: уровень 3 — диапазон величины, перевод единиц, противоречия`.

---

### Task 9: Уровень 4 — дубли

**Files:** `amem/check/level4.py`, `tests/test_check_level4.py`.

- [ ] **Step 1: падающие тесты** (`pg`). Вектора — от `FakeProvider` из `conftest.py`. Модель активируется так: `embed.register_model`, затем `sync_embeddings`, затем `activate_model`.
  - **Атомы, текст:**
    - существующий атом «Ветровое давление для района II равно 0,30 кПа», новый «Ветровое давление района II равно 0,30 кПа» того же вида → `duplicate` (текст ≥ 90) с кандидатом;
    - замечания нет, если вид другой или у существующего статус `rejected`;
    - правка самой записи себя не находит;
    - похожий ниже порога → `related` (info), кандидатов не больше 5.
  - **Атомы, вектор:** подменённый провайдер отдаёт для нового текста вектор существующей записи → `duplicate`, `details.candidates[0].channel == "vector"`.
  - **Ослабление** — работает только текст, причины:
    - `AMEM_BACKEND=none` → `degraded == [{"level": 4, "channel": "vector", "reason": "backend_disabled"}]`;
    - модели нет → `no_active_model`;
    - неявный провайдер бросает `EmbeddingError` → `provider_error`;
    - явный провайдер с `EmbeddingError` → исключение наружу.
  - **Сущности:** «Пример и партнёры» при существующей сущности с алиасом «Пример и партнёры» → `duplicate`, `details.suggest == "same_as"`.
  - **Внутри пачки:** два почти одинаковых атома → `duplicate` у второго.
  - **Журнал:** таблица `retrieval` не пополнилась.
- [ ] **Step 2: реализация** `level4.check(conn, batch, report, *, provider=None) -> list[dict]` — возвращает `degraded`.
  - **Константы:** `DUP_TEXT = 90`, `DUP_VECTOR = 0.92`, `REL_TEXT = 60`, `REL_VECTOR = 0.80`, `CANDIDATES = 20`, `RELATED = 5`.
  - **Текстовые кандидаты** — собственный запрос:

  ```sql
  WITH q AS (SELECT to_tsquery('simple', string_agg(quote_literal(l), ' | ')) AS query
               FROM unnest(tsvector_to_array(to_tsvector('russian', %(label)s))) l)
  SELECT d.record_id, c.payload->'label'->>'ru'
    FROM q, search_document d
    JOIN atom a ON a.id = d.record_id
    JOIN atom_current c ON c.atom_id = a.id
   WHERE q.query IS NOT NULL AND d.target = 'atom' AND a.kind = %(kind)s
     AND a.status = ANY(%(statuses)s) AND a.id IS DISTINCT FROM %(self)s
     AND d.search_vector @@ q.query
   ORDER BY ts_rank_cd(d.search_vector, q.query) DESC LIMIT 20
  ```

  `IS DISTINCT FROM`, а не `<>`: у новой записи `self` — `NULL`, и `<>` отбросил бы всех кандидатов. Подпись без лексем (одни стоп-слова) — текстовых кандидатов нет. Запрос для сущностей — тот же, по `entity`, `entity_class` и `aliases`.
  - **Вектор:**
    - модель — `search._active_model`, провайдер — `embed.get_provider(provider)`;
    - неявный провайдер кэшируется на процесс (`functools.cache` вокруг `embed.get_provider()` при `provider is None`);
    - документ — `search.search_text(payload, target).document`;
    - кандидаты — `search._vector(conn, vec, model_id, target=…, kind=…, exclude=…)`, расстояние переводится в схожесть.
- [ ] **Step 3.** Focused, полный прогон. Commit: `check: уровень 4 — дубли текстом и вектором, подсказки связей, явное ослабление`.

---

### Task 10: `submit` — статусы, запись, ответ

**Files:** `amem/check/__init__.py`, `amem/review.py` (часть 3a: `insert_item`, `in_audit`, `AUDIT_RATE`), `tests/test_check_submit.py`.

- [ ] **Step 1: падающие тесты** (`pg`, `docs`, `store`).
  - **Отклонение:** пакет из двух атомов, у одного нет источника:
    - `state == "rejected"`, атомов в базе нет, `changeset.state = 'rejected'`;
    - `check_report` проходит `CheckReport`, `levels["3"] == "skipped"`, `levels["5"] == "skipped"`;
    - `queued == []`, `complete is True` — обработка закончена, в очереди ничего.
  - **Чистый атом с PDF-источником:**
    - статус `draft`, пункт `semantic` в `queued`, `levels["5"] == "queued"`, `complete is False`;
    - в `source` записаны `verdict`, `page`, `anchor`, `checked_at = changeset.created_at`;
    - в отчёте `records[0] == {"label": …, "target": "atom", "planned_status": "draft", "risk": []}` и нет поля `review`.
  - **К человеку:**
    - источник-переписка → `needs_review`, пункт `warning`, `levels["5"] == "not_applicable"`;
    - `decision` без замечаний → `needs_review`, пункт `high_risk`, `risk == ["template:decision:always"]`;
    - `rule` с числом → риск `template:rule:numeric`.
  - **Сущности:**
    - без замечаний → `auto_verified`, пунктов нет, `complete is True`, `levels["5"] == "not_applicable"`;
    - с `review.AUDIT_RATE = 1.0` (monkeypatch) → пункт `audit`, `complete is False`;
    - с риском (шаблон-интерфейс сущностей с `always` во временном пакете) → `needs_review`.
  - **Правки:**
    - `verified` атома → ревизия `pending`, текущая прежняя, статус `verified`, пункт `edit`;
    - `draft` атома → новая текущая ревизия; пункт `semantic` старой ревизии закрыт `obsolete`, у новой — новый `semantic`;
    - `deprecated` атома → отклонено с `retired_record`.
  - **Тело без изменений:** отклонённый человеком атом (`rejected`) прислан тем же телом → `created False`, статус остаётся `rejected`, пунктов нет, итоги сверки обновлены.
  - **Поздний отказ:** два пакета с одинаковым `key` — второй отклонён с `record_error`, `levels["3"] == "done"`, половины пакета в базе нет.
  - **Гонка статуса:** monkeypatch уровня 4 вызывает `records.set_status(..., "deprecated")` → пакет отклонён с `retired_record`.
  - **Устаревшая версия:** атом ссылается на `obj:…` версии 1, а у объекта уже есть версия 2 → пункт `source_changed`.
  - **Окружение:** `StoreError` из разбора источника → исключение; ни пакета, ни записей.
  - **Тупики:** два потока (`threading`, у каждого своё `db.connect`) отправляют пакеты от двух новых агентов с правкой одной записи — оба завершаются без `DeadlockDetected`; повтор 20 раз.
- [ ] **Step 2: реализация.**

  ```python
  @dataclass
  class Proposal:
      target: Literal["atom", "entity"]
      payload: dict
      record_id: uuid.UUID | str | None = None

  @dataclass
  class Submitted:
      state: str; changeset_id: uuid.UUID; report: dict; records: list[dict]
      queued: list[dict]; levels: dict[str, str]; complete: bool

  def submit(conn, store, docs, proposals, links=(), *, agent, activity=None, reason=None, provider=None) -> Submitted
  ```

  Транзакция записи — по шагам разд. 7.5 спецификации:
  1. `INSERT INTO agent … ON CONFLICT DO NOTHING`.
  2. `SELECT pg_advisory_xact_lock_shared(objects.OBJECTS_LOCK)`.
  3. `SELECT status FROM {t} WHERE id = %s FOR NO KEY UPDATE` — по возрастанию id.
  4. `records.commit`. У существующих записей `Item.status` — `None`; у новых — плановый статус; у правки `verified` — `review_state="pending"`.
  5. Для созданных ревизий существующих записей — `records.set_status_locked(conn, t, id, status, agent=agent, reason="autocheck", at=at)`; `at` — `changeset.created_at`.
  6. `UPDATE source SET verdict = %s, page = %s, anchor = %s, checked_at = %s WHERE {t}_revision_id = %s AND position = %s`. Затем `source_changed` там, где `object_version < (SELECT max(n) FROM object_version WHERE object_id = …)`.
  7. Устаревание: `UPDATE review_item SET state = 'obsolete', closed_at = %s WHERE record_id = %s AND state IN ('queued', 'claimed') AND …` — правила разд. 7.3. Затем пункты: `review.insert_item(conn, target, record_id, revision_id, reason, *, changeset_id, details, agent, at)` с `ON CONFLICT DO NOTHING`. Затем аудит: `review.in_audit(revision_id, review.AUDIT_RATE)`, где `in_audit` — `int.from_bytes(sha256(b"amem-audit" + revision_id.bytes).digest()[:8], "big") / 2**64 < rate`.

  `RecordError` из `commit` → откат, затем `records.reject` вне транзакции с отчётом, в котором есть `record_error`.
- [ ] **Step 3.** Focused, полный прогон. Commit: `check: submit — статусы по замечаниям и риску, итоги сверки, пункты очереди, «в очереди» ≠ «сделано»`.

---

### Завершение части 3a

- [ ] README и README.ru: раздел «Автопроверка» (часть 3a):
  - `submit`, уровни, статусы;
  - «в очереди ≠ сделано»;
  - `role: derived` для пересчитанных чисел;
  - xlsx и docx.

  Состояние проекта — подпроект 3a. Commit: `docs: автопроверка в README`.
- [ ] Мутационные пробы правил 3a — скрипт во временной папке, не в репозитории. Мутанты:
  - правило знака у тире;
  - `created`-условие смены статуса;
  - разделяемая блокировка объектов;
  - проверка устаревшей версии;
  - `ON CONFLICT` в `insert_item`;
  - одностраничное `ok` только для `.md`/`.txt`.

  Каждый мутант должен ронять хотя бы один тест. Выжившего — либо закрыть тестом, либо записать как эквивалентного.
- [ ] Ревью всей ветки субагентом; Critical и Important исправлены.
- [ ] Полный прогон на pg18 и pg16, `gen_schema.py --check`, проверка на приватное (скрипт в scratchpad). Пуш, PR с описанием и строкой `🤖 Generated with [Claude Code](https://claude.com/claude-code)`, CI зелёный, слияние.

---

## Часть 3b

### Task 11: Очередь — захват, решение, ручная постановка

**Files:** `amem/review.py`, `tests/test_review.py`.

- [ ] **Step 1: падающие тесты** (`pg`; пункты создаются через `check.submit`).
  - **Захват:**
    - `claim(agent="model:verifier")` возвращает самый старый `semantic` с телом ревизии, источниками и автором пакета;
    - `model:verifier` не получает `warning`; автор пакета не получает свой `semantic`; `person:` получает всё;
    - два соединения захватывают параллельно (`threading`) — пункты разные;
    - истёкшая аренда (`now` в будущем) → пункт достаётся другому;
    - `release` чужого → `ReviewError`; своего → `queued`.
  - **Решение по `semantic`:**
    - `resolve(semantic, "confirmed", confidence=0.9, agent="model:verifier")` → `auto_verified`, `verification.method == "llm_judge"`;
    - `confidence=0.5` → `needs_review` и пункт `semantic_doubt`; `"partial"` → то же;
    - без `confidence` от модели → `ReviewError`;
    - человек: `confirmed` → `verified`, `uncertain` → `ReviewError`.
  - **Права и прочие причины:**
    - `warning` от `model:` → `ReviewError`; `refuted` человеком → `rejected`;
    - `edit`: `confirmed` → ревизия текущая, статус `verified`; `refuted` → ревизия `declined`;
    - человек подтверждает свою же правку — разрешено.
  - **Несколько пунктов у ревизии:** человек подтвердил `source_changed` → `verified`, а открытый `semantic` той же ревизии закрыт `obsolete`. Модель решает `semantic` после `set_status(..., "verified")` мимо очереди → вердикт записан, статус остался `verified`.
  - **Две ждущие правки:** принята новая → пункт `edit` старой при захвате закрывается `obsolete`.
  - **Устаревание:** запись получила новую ревизию через `records.commit` мимо `submit` → пункт при `claim` закрыт `obsolete` и не выдан; `resolve` по нему → `ReviewError`, пункт `obsolete`.
  - **Аудит:** `AUDIT_RATE = 1.0`, после `semantic confirmed` → пункт `audit`.
  - **Ручная постановка:** `enqueue(ref, "calibration", agent="person:ann")` ставит пункт, повтор возвращает тот же id; от `model:` → `ReviewError`.
  - **Список:** `items(state="queued", reason="semantic")` фильтрует.
  - **Тупики:** `resolve` и `submit` по одной записи в двух потоках — без `DeadlockDetected`, 20 повторов.
- [ ] **Step 2: реализация.**
  - **Константы и ошибки:** `ReviewError(ValueError)`; `HUMAN_REASONS`; `MODEL_OUTCOMES = {"confirmed", "partial", "refuted", "uncertain"}`, `HUMAN_OUTCOMES = {"confirmed", "refuted"}`; `SEMANTIC_MIN_CONFIDENCE = 0.8`; `LEASE = timedelta(minutes=15)`.
  - **Захват:**

    ```sql
    SELECT … FROM review_item ri LEFT JOIN changeset cs ON cs.id = ri.changeset_id
     WHERE (ri.state = 'queued' OR (ri.state = 'claimed' AND ri.claimed_until < %(now)s))
       AND ri.reason = ANY(%(reasons)s) AND NOT (ri.reason = 'semantic' AND cs.agent = %(agent)s)
     ORDER BY ri.created_at, ri.id LIMIT %(limit)s FOR UPDATE OF ri SKIP LOCKED
    ```

  - **Решение** — по разд. 8.5:
    1. Пункт читается без блокировки.
    2. Агент.
    3. Запись — `FOR NO KEY UPDATE`.
    4. Пункт — `FOR UPDATE`, затем перепроверка.
    5. Последствия: при ожидаемом статусе — `records.set_status_locked`; у `edit` — `records.decide` (точка сохранения); итоговое решение человека закрывает остальные открытые пункты ревизии.
- [ ] **Step 3.** Focused, полный прогон. Commit: `check: очередь — захват с арендой, права, решение с вердиктом, аудит, ручная постановка`.

---

### Task 12: Метрики

**Files:** `amem/review.py`, `tests/test_review_stats.py`.

- [ ] **Step 1: падающие тесты.**
  - Подготовленные данные:
    - 3 пункта `semantic`, из них 1 захвачен и 1 с истёкшей арендой;
    - 2 пункта, решённые с известными интервалами;
    - 1 пункт `obsolete`;
    - 1 отклонённый пакет с `quote_not_found`;
    - 1 решение аудита `refuted`.
  - `stats(now=…)` на них даёт точные числа во всех разделах разд. 8.7 спецификации.
  - Пустая база — нули и `None`, без ошибок.
  - Результат сериализуется `json.dumps`.
- [ ] **Step 2: реализация** `stats(conn, *, days=7, now=None) -> dict`. Медиана — `percentile_cont(0.5) WITHIN GROUP (ORDER BY …)`.
- [ ] **Step 3.** Focused, полный прогон. Commit: `check: метрики очереди и проверки`.

---

### Task 13: Новая версия объекта и завершение

**Files:** `amem/review.py`, `amem/objects.py`, `tests/test_review_sources.py`, README.

- [ ] **Step 1: падающие тесты.**
  - Атом и сущность ссылаются на `заметка.md` v1; файл изменён, `objects.ingest` создал v2 → у обеих текущих ревизий пункт `source_changed` с `details == {"object": "obj:…", "from": [1], "to": 2}`.
  - Ждущая правка со ссылкой на v1 тоже получает пункт.
  - У `rejected` атома пункта нет.
  - Повторный `ingest` того же содержимого пунктов не прибавляет. Третья версия при открытом пункте его не дублирует.
  - Новая ревизия атома со ссылкой на v2 через `submit` → пункт `obsolete`.
  - Гонка: поток A разбирает путь (v1) и ждёт перед транзакцией записи, поток B выполняет `ingest` v2, затем A записывает пакет → у ревизии ровно один пункт `source_changed`.
- [ ] **Step 2: реализация.** `on_new_version(conn, object_id, n, *, agent, at)` вызывается из `objects.ingest` в его транзакции, после вставки версии `n > 1`.
- [ ] **Step 3.** README: очередь, захват, решение, метрики. Спецификация: в таблице разд. 13 — столбец «Тест» с именами тестов. Мутационные пробы правил 3b:
  - исключение автора в `claim`;
  - ожидаемый статус в `resolve`;
  - закрытие пунктов итоговым решением;
  - `ON CONFLICT` в `on_new_version`;
  - порог `SEMANTIC_MIN_CONFIDENCE`;
  - переход `claimed→done` в триггере.
- [ ] **Step 4.** Ревью ветки, полный прогон на pg18 и pg16, проверка на приватное, PR, CI, слияние. Commit: `check: пересмотр при новой версии объекта; docs: очередь проверки в README`.

---

## Критерии готовности

- Все тесты зелёные на PostgreSQL 18 и 16; `gen_schema.py --check` зелёный; CI зелёный у обоих PR.
- Каждое требование таблицы приёмки спецификации связано с тестом.
- Ревью каждой задачи и итоговое ревью веток пройдены; Critical и Important исправлены.
- Публичный репозиторий не получил ничего приватного.

## Что остаётся следующим подпроектам

- Исполнитель уровня 5 (навык смыслового проверяющего, запуск по расписанию), сервер MCP/HTTP, CLI (`amem check`, `amem review`), повторная сверка источников (`recheck_sources`) — подпроект 4.
- Страница «Проверка» — подпроект 5.
- Доля аудита по ошибкам и метрика калибровки — после пилота.
