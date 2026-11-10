# amemo — подпроект 3c «Онтология, профили, подборки»: план реализации

> **Для исполнителей-агентов:** задачи выполняются через superpowers:subagent-driven-development — свежий субагент на задачу, ревью после каждой. Шаги — с флажками (`- [ ]`).

05.11.2026. Исполняет `docs/superpowers/specs/2026-11-05-amemo-subproject-3c-ontology-profiles-bundles-design.md` (редакция 1).

**Цель:** ядро 1.2.0 и пакеты с зависимостями; основание (`basis`) и уверенность (`confidence`) у атома; профили сущностей в шаблонах и карточка `amem.card/1`; подборки `amem.bundle/1` с экспортом и импортом без перезаписи; политика записей человека.

**Архитектура:** три части — три ветки и три PR. Часть A меняет схему, пакеты и уровень 1 автопроверки; часть B добавляет проекцию `atom_property` и модуль `amemo/profile.py`; часть C — `records.commit(keep_ids=True)`, `objects.adopt` и модуль `amemo/bundle.py`. Одна миграция `0007_ontology.sql` создаётся в части A целиком.

**Стек:** Python 3.11+, PostgreSQL 18/16, psycopg 3, LinkML → Pydantic (`tools/gen_schema.py`), PyYAML, `packaging` (диапазоны версий), `zipfile`.

**Предпосылка:** части 3a и 3b автопроверки слиты в `main` (`check.submit`, `amemo/check/level1.py`, `amemo/review.py`). Если `level1.py` устроен не так, как записано в спецификации подпроекта 3, адаптировать шаги задачи 5 по месту, а не отключать тесты.

**Формат:** каждая задача — падающий тест → реализация → focused test → полный прогон → коммит. Красный тест не пропускается. Противоречие спецификации — сначала правится спецификация с причиной, затем план.

**Команды** (как в README; порты тестовых баз — свои):

```bash
cd ~/projects/amemo
export AMEMO_TEST_DSNS="postgresql://test:test@127.0.0.1:<pg18>/test,postgresql://test:test@127.0.0.1:<pg16>/test"
export AMEMO_PG_BIN=<bin клиента PostgreSQL 18>
env -u PYTHONPATH .venv/bin/pytest -q -p no:cacheprovider; echo "exit=$?"
.venv/bin/python tools/gen_schema.py --check
```

**Правила:**
- тестовые данные нейтральны — никаких компаний, объектов, людей, путей пользователя;
- сообщения коммитов начинаются с `ontology:`, `profile:`, `bundle:` или `docs:`, называют число новых тестов и заканчиваются строкой `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`;
- код возврата pytest проверяется явно.

---

## Карта файлов

| Файл | Назначение |
|---|---|
| `pyproject.toml` | зависимость `packaging>=23` |
| `amemo/schema/amemo_v1.yaml` | `Basis`, `AtomPayload.basis/confidence`, `FieldRule.skip_if_set`, `ParameterRule`, `Template.parameters`, `Provenance.origin_revision_hash/origin_agent`, новые коды `CheckCode`, `ReviewReason.imported`, `HighRiskRule.low_confidence` |
| `amemo/model_v1.py`, `amemo/schema/amemo_v1.schema.json` | генерируются |
| `amemo/packs.py` | `requires`, топологический порядок, `broader`, проверка `parameters` |
| `amemo/packs/core/**` | ядро 1.2.0: `note`, `artifact`, `bbox`, `has_source` 1.1.0, шаблон `note` |
| `amemo/sql/0007_ontology.sql` | `pack.requires`, `atom_property`, `import_history`, перечни `review_item.reason` |
| `amemo/db.py` | `load_vocab` пишет `requires` |
| `amemo/check/templates.py` | `Rules.parameters`, сведение по `property` |
| `amemo/check/level1.py` | `skip_if_set`; правила `basis`, `confidence`; риск `low_confidence` |
| `amemo/check/__init__.py` | политика `person:`; `LOW_CONFIDENCE = 0.8` |
| `amemo/records.py` | `atom_property` в `_write_revision`; `rebuild_projections`; `keep_ids` |
| `amemo/profile.py` | `rules_for_entity`, `card` |
| `amemo/objects.py` | `adopt` |
| `amemo/bundle.py` | `Selection`, `export`, `inspect`, `import_`, `BundleError` |
| `amemo/backup.py` | `COUNTED` + `atom_property`, `import_history` |
| `tests/packs/ontology/` | тестовый пакет: величины, `parameter_origin`, профили `device` и `device_sensor`, пакет-зависимость `tests/packs/quantities` |
| `tests/test_ontology_*.py`, `tests/test_profile.py`, `tests/test_bundle*.py` | тесты задач |
| `README.md`, `README.ru.md` | разделы «Пакеты», «Профили и карточка», «Подборки» |

Публичные функции принимают соединение `db.connect` (autocommit). Ссылки — `atm:`, `ent:`, `obj:`.

---

## Часть A — схема, пакеты, уровень 1 (ветка `subproject-3c-ontology`)

### Task 0: Исходная точка

- [ ] **Step 1.** `git checkout main && git pull`, затем `git checkout -b subproject-3c-ontology`. `git log --oneline -3` показывает слитые 3a и 3b.
- [ ] **Step 2.** Тестовые базы доступны (`docker compose --profile test up -d --wait db-test db-test-pg16` или свои). Полный прогон зелёный, `gen_schema.py --check` чист. Число тестов записать в `.superpowers/sdd/progress.md`.
- [ ] **Step 3.** Скопировать спецификацию и этот план из ветки `ontology-spec` (если они ещё не в `main`): `git checkout ontology-spec -- docs/superpowers/specs/2026-11-05-amemo-subproject-3c-ontology-profiles-bundles-design.md docs/superpowers/plans/2026-11-05-amemo-subproject-3c-ontology-profiles-bundles.md`. Commit: `docs: спецификация и план подпроекта 3c`.

---

### Task 1: Схема LinkML

**Files:** `amemo/schema/amemo_v1.yaml`, сгенерированные `amemo/model_v1.py` и `amemo/schema/amemo_v1.schema.json`, `tests/test_ontology_schema.py`.

- [ ] **Step 1: падающие тесты** `tests/test_ontology_schema.py`:

```python
"""Схема подпроекта 3c: основание и уверенность атома, правило skip_if_set, профиль шаблона, происхождение."""
import pytest

from amemo import model_v1
from v1_support import example, pydantic_errors, json_errors

ATOM = "atom_parameter.yaml"          # существующий нейтральный пример атома-параметра из tests/v1_examples


def _atom(**extra):
    return {**example(ATOM), **extra}


def test_basis_enum():
    assert [m.value for m in model_v1.Basis] == ["default", "assumed", "author"]


@pytest.mark.parametrize("basis", ["default", "assumed", "author"])
def test_atom_accepts_basis(basis):
    assert pydantic_errors("AtomPayload", _atom(basis=basis)) == []
    assert json_errors("AtomPayload", _atom(basis=basis)) == []


def test_atom_rejects_unknown_basis():
    assert pydantic_errors("AtomPayload", _atom(basis="guess"))


@pytest.mark.parametrize("value, ok", [(0.0, True), (0.8, True), (1.0, True), (1.5, False), (-0.1, False), ("0.8", False)])
def test_atom_confidence_bounds(value, ok):
    assert (pydantic_errors("AtomPayload", _atom(confidence=value)) == []) is ok


def test_field_rule_skip_if_set():
    rule = model_v1.FieldRule.model_validate({"path": "sources", "required": True, "skip_if_set": "basis"}, strict=True)
    assert rule.skip_if_set == "basis"


def test_template_parameters():
    body = {"code": "device", "version": "1.0.0", "target": "entity", "applies_to": "device",
            "parameters": [{"property": "mass", "required": True, "group": "body",
                            "default": {"amount": 1.0, "unit": "kg"},
                            "ask": {"ru": "изготовитель"}, "hint": {"ru": "паспорт"}, "when": {"ru": "всегда"}}]}
    t = model_v1.Template.model_validate(body, strict=True)
    assert t.parameters[0].property == "mass" and t.parameters[0].required is True
    bad = {**body, "parameters": [{"required": True}]}
    with pytest.raises(ValueError):
        model_v1.Template.model_validate(bad, strict=True)


def test_provenance_fields():
    p = model_v1.Provenance.model_validate({
        "origin_base": "01932f5e-7a3b-7c4d-8e9f-0123456789ab",
        "origin_revision_hash": "sha256-c1:" + "0" * 64, "origin_agent": "person:alice"}, strict=True)
    assert p.origin_agent == "person:alice"
    with pytest.raises(ValueError):
        model_v1.Provenance.model_validate({"origin_revision_hash": "sha256:" + "0" * 64}, strict=True)


def test_new_enum_values():
    assert "imported" in {m.value for m in model_v1.ReviewReason}
    assert "low_confidence" in {m.value for m in model_v1.HighRiskRule}
    for code in ["basis_author_model", "basis_without_rule", "confidence_person",
                 "bundle_pack_missing", "bundle_key_collision"]:
        assert code in {m.value for m in model_v1.CheckCode}
```

Если примера `atom_parameter.yaml` в `tests/v1_examples` нет — взять любой существующий пример атома из этой папки и подставить его имя в `ATOM`.

- [ ] **Step 2.** Run: `env -u PYTHONPATH .venv/bin/pytest tests/test_ontology_schema.py -q`. Expected: FAIL — `Basis` отсутствует.
- [ ] **Step 3: схема.** В `amemo_v1.yaml`:

```yaml
  Basis:
    description: Основание значения, когда оно не взято из документа об объекте.
    permissible_values:
      default:
        annotations: {label_ru: "умолчание", label_en: "default", definition_ru: "Умолчание методики — принято по правилу области «в запас», не из документа об объекте."}
      assumed:
        annotations: {label_ru: "допущение", label_en: "assumed", definition_ru: "Принято без решения по объекту, чтобы продолжить работу; требует подтверждения."}
      author:
        annotations: {label_ru: "утверждение автора", label_en: "author", definition_ru: "Человек утверждает это сам; документа нет. Доступно только агенту person:."}
```

В `AtomPayload.attributes` после `provenance`:

```yaml
      basis:
        description: Основание значения без документа; при заданном basis источник не обязателен (has_source 1.1.0).
        range: Basis
      confidence:
        description: Уверенность агента-модели в утверждении (распознавание, извлечение). Человек поле не заполняет.
        range: float
        minimum_value: 0
        maximum_value: 1
```

В `FieldRule.attributes`:

```yaml
      skip_if_set:
        description: Путь до поля того же тела; если оно непусто, правило не применяется.
        pattern: '^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)*$'
```

Новый класс и поле шаблона:

```yaml
  ParameterRule:
    description: >-
      Правило профиля сущности: какая величина нужна объекту этого класса. required — блокер; default — умолчание
      области (в карточке показывается, значением не считается); origin — код словаря parameter_origin.
    attributes:
      property: {required: true, pattern: '^[a-z][a-z0-9_]*$'}
      required: {range: boolean}
      group: {pattern: '^[a-z][a-z0-9_]*$'}
      origin: {pattern: '^[a-z][a-z0-9_]*$'}
      default: {range: ParameterDefault, inlined: true}
      ask: {range: LangString, inlined: true}
      hint: {range: LangString, inlined: true}
      when: {range: LangString, inlined: true}

  ParameterDefault:
    attributes:
      amount: {range: float}
      unit: {}
      value_text: {}
```

В `Template.attributes`: `parameters: {range: ParameterRule, multivalued: true, inlined_as_list: true}` с описанием «только у target entity». В `Provenance.attributes`:

```yaml
      origin_revision_hash:
        description: content_hash ревизии в базе-источнике — по нему повторный импорт узнаёт то же содержание.
        pattern: '^sha256-c[1-9][0-9]*:[0-9a-f]{64}$'
      origin_agent:
        pattern: '^(person|model):[a-z0-9_.-]+$'
```

Перечни: в `ReviewReason` — `imported` (label_ru «из другой базы», definition_ru «Пришло подборкой из другой базы»); в `HighRiskRule` — `low_confidence` («низкая уверенность», «Записи с confidence ниже порога уходят к человеку»); в `CheckCode` — `basis_author_model` («автор — модель», «basis author у записи модели»), `basis_without_rule` («основание без правила», «basis default или assumed без derived_from»), `confidence_person` («уверенность у человека», «confidence заполнил человек»), `bundle_pack_missing` («нет пакета подборки», «Пакет подборки не загружен или digest иной»), `bundle_key_collision` («ключ занят», «key записи подборки принадлежит другой записи»).

- [ ] **Step 4.** `.venv/bin/python tools/gen_schema.py`, затем `--check`. Focused: `tests/test_ontology_schema.py tests/test_v1_generated.py tests/test_v1_templates.py`. Полный прогон. Commit: `ontology: схема — basis и confidence атома, skip_if_set, ParameterRule и parameters шаблона, происхождение импорта, новые коды; N новых тестов`.

---

### Task 2: Зависимости пакетов, `broader`, миграция 0007

**Files:** `pyproject.toml`, `amemo/packs.py`, `amemo/sql/0007_ontology.sql`, `amemo/db.py`, `amemo/backup.py`, `tests/packs/quantities/`, `tests/test_ontology_packs.py`, `tests/test_sql_schema.py`.

- [ ] **Step 1: зависимость.** В `pyproject.toml` `dependencies` добавить `"packaging>=23"`. `.venv/bin/pip install -e '.[dev]'`.
- [ ] **Step 2: тестовый пакет-зависимость** `tests/packs/quantities/`:

```yaml
# pack.yaml
name: quantities
version: 1.0.0
title: Величины для тестов
description: Физические величины с единицами и диапазонами — общий пакет, который требуют другие тестовые пакеты.
license: MIT
```

```yaml
# vocab/property.yaml
scheme: property
concepts:
  - {code: mass, label: {ru: масса, en: mass}, definition: {ru: "Масса тела."}, unit: kg, plausible_min: 0, plausible_max: 100000}
  - {code: length, label: {ru: длина, en: length}, definition: {ru: "Длина или размер."}, unit: m, plausible_min: 0, plausible_max: 1000}
  - {code: temperature, label: {ru: температура, en: temperature}, definition: {ru: "Температура."}, unit: Cel, plausible_min: -80, plausible_max: 200}
  - {code: width, label: {ru: ширина, en: width}, definition: {ru: "Ширина."}, unit: m, broader: length, plausible_min: 0, plausible_max: 1000}
```

- [ ] **Step 3: падающие тесты** `tests/test_ontology_packs.py` (без базы, кроме последнего):

```python
"""Зависимости пакетов: requires, порядок загрузки, циклы, broader."""
from pathlib import Path

import pytest
import yaml

from amemo import db, packs

QUANTITIES = Path(__file__).with_name("packs") / "quantities"


def _pack(root: Path, name: str, version="1.0.0", requires=None, vocab=None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    manifest = {"name": name, "version": version}
    if requires:
        manifest["requires"] = requires
    (root / "pack.yaml").write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8")
    for scheme, concepts in (vocab or {}).items():
        (root / "vocab").mkdir(exist_ok=True)
        (root / "vocab" / f"{scheme}.yaml").write_text(
            yaml.safe_dump({"scheme": scheme, "concepts": concepts}, allow_unicode=True), encoding="utf-8")
    return root


def _kind(code, broader=None):
    c = {"code": code, "label": {"ru": code, "en": code}, "definition": {"ru": f"Вид {code}."}}
    if broader:
        c["broader"] = broader
    return c


def test_requires_satisfied_and_ordered(tmp_path):
    a = _pack(tmp_path / "a", "a", requires={"quantities": ">=1.0.0,<2"})
    loaded = packs.load_packs([packs.CORE_PACK, a, QUANTITIES])
    assert [p.name for p in loaded] == ["core", "quantities", "a"]
    assert loaded[2].requires == {"quantities": ">=1.0.0,<2"}


def test_requires_missing_names_pack(tmp_path):
    a = _pack(tmp_path / "a", "a", requires={"quantities": ">=1.0.0"})
    with pytest.raises(packs.PackError, match="пакет a требует quantities >=1.0.0"):
        packs.load_packs([packs.CORE_PACK, a])


def test_requires_version_out_of_range(tmp_path):
    a = _pack(tmp_path / "a", "a", requires={"quantities": ">=2.0.0"})
    with pytest.raises(packs.PackError, match="загружен 1.0.0"):
        packs.load_packs([packs.CORE_PACK, a, QUANTITIES])


def test_requires_cycle(tmp_path):
    a = _pack(tmp_path / "a", "a", requires={"b": ">=1.0.0"})
    b = _pack(tmp_path / "b", "b", requires={"a": ">=1.0.0"})
    with pytest.raises(packs.PackError, match="цикл.*a → b → a|цикл.*b → a → b"):
        packs.load_packs([packs.CORE_PACK, a, b])


def test_requires_core_explicit_is_checked(tmp_path):
    a = _pack(tmp_path / "a", "a", requires={"core": ">=9.0.0"})
    with pytest.raises(packs.PackError, match="требует core >=9.0.0"):
        packs.load_packs([packs.CORE_PACK, a])


def test_bad_requires_shape(tmp_path):
    a = _pack(tmp_path / "a", "a", requires=["quantities"])
    with pytest.raises(packs.PackError, match="requires: ожидается отображение"):
        packs.load_packs([packs.CORE_PACK, a])


def test_broader_must_exist(tmp_path):
    a = _pack(tmp_path / "a", "a", vocab={"kind": [_kind("idea", broader="thought")]})
    with pytest.raises(packs.PackError, match="broader thought — нет в словаре kind"):
        packs.load_packs([packs.CORE_PACK, a])


def test_broader_across_packs_ok(tmp_path):
    a = _pack(tmp_path / "a", "a", requires={"quantities": ">=1.0.0"},
              vocab={"property": [{"code": "span", "label": {"ru": "пролёт", "en": "span"},
                                   "definition": {"ru": "Пролёт."}, "unit": "m", "broader": "length"}]})
    assert packs.load_packs([packs.CORE_PACK, a, QUANTITIES])


def test_pack_table_keeps_requires(pg, monkeypatch, tmp_path):
    a = _pack(tmp_path / "a", "a", requires={"quantities": ">=1.0.0,<2"})
    monkeypatch.setenv("AMEMO_PACKS", f"{QUANTITIES}{__import__('os').pathsep}{a}")
    db.prepare(pg)
    row = pg.execute("SELECT requires FROM pack WHERE name = 'a'").fetchone()
    assert row[0] == {"quantities": ">=1.0.0,<2"}
    assert pg.execute("SELECT requires FROM pack WHERE name = 'core'").fetchone()[0] == {}
```

- [ ] **Step 4.** Run: `env -u PYTHONPATH .venv/bin/pytest tests/test_ontology_packs.py -q`. Expected: FAIL — `Pack` без `requires`, нет проверки.
- [ ] **Step 5: миграция** `amemo/sql/0007_ontology.sql` (целиком — части B и C её только используют):

```sql
-- Схема v1, часть 3c: зависимости пакетов, проекция величин атома, история импорта. Совместимо с PostgreSQL 16.

ALTER TABLE pack ADD COLUMN requires jsonb NOT NULL DEFAULT '{}'::jsonb;

-- Величины текущей ревизии атома: content.values[].property. Заполняется записью ревизии (amemo/records.py)
-- вместе с atom_about; перестраивается records.rebuild_projections.
CREATE TABLE atom_property (
    revision_id  uuid NOT NULL REFERENCES atom_revision (id),
    property     text NOT NULL,
    PRIMARY KEY (revision_id, property)
);
CREATE INDEX atom_property_property ON atom_property (property, revision_id);

-- Ревизии чужой базы, пришедшие подборкой с историей: локальной историей не становятся, хранятся для просмотра.
CREATE TABLE import_history (
    id            uuid PRIMARY KEY CHECK (id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab]'),
    changeset_id  uuid NOT NULL REFERENCES changeset (id),
    target        text NOT NULL CHECK (target IN ('atom', 'entity')),
    record_id     uuid NOT NULL,
    origin_base   uuid NOT NULL,
    n             integer NOT NULL CHECK (n >= 1),
    content_hash  text NOT NULL,
    payload       jsonb NOT NULL,
    recorded_at   timestamptz NOT NULL,
    agent         text,
    UNIQUE (origin_base, record_id, n)
);
CREATE INDEX import_history_record ON import_history (record_id, n);

-- Новая причина пункта очереди.
ALTER TABLE review_item DROP CONSTRAINT review_item_reason_check;
ALTER TABLE review_item ADD CONSTRAINT review_item_reason_check CHECK (reason IN ('semantic', 'warning', 'high_risk',
    'semantic_doubt', 'edit', 'source_changed', 'audit', 'calibration', 'imported'));
```

Имя ограничения `review_item_reason_check` сверить с `\d review_item` в тестовой базе; если PostgreSQL назвал его иначе — использовать фактическое имя. `tests/test_sql_schema.py` сверяет перечни CHECK со схемой — после миграции он должен остаться зелёным (перечень `ReviewReason` уже расширен в задаче 1).

- [ ] **Step 6: загрузчик.** В `amemo/packs.py`:

```python
from packaging.specifiers import SpecifierSet, InvalidSpecifier
from packaging.version import Version, InvalidVersion
```

В `Pack` — поле `requires: dict[str, str]`. В `load_pack` после чтения `name`, `version`:

```python
    requires = manifest.get("requires") or {}
    if not isinstance(requires, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in requires.items()):
        raise PackError(f"{path / 'pack.yaml'}: requires: ожидается отображение имя → диапазон версий")
    for dep, spec in requires.items():
        try:
            SpecifierSet(spec)
        except InvalidSpecifier as e:
            raise PackError(f"{path / 'pack.yaml'}: requires: {dep}: {e}") from e
```

и `requires=requires` в конструкторе `Pack`. Новая функция:

```python
def _ordered(packs: list[Pack]) -> list[Pack]:
    """Ядро первым, дальше — топологический порядок по requires; версии проверены; цикл — ошибка с цепочкой."""
    by_name = {p.name: p for p in packs}
    for p in packs:
        for dep, spec in p.requires.items():
            if dep not in by_name:
                raise PackError(f"пакет {p.name} требует {dep} {spec}, он не загружается")
            try:
                have = Version(by_name[dep].version)
            except InvalidVersion as e:
                raise PackError(f"пакет {dep}: версия {by_name[dep].version!r} — не semver") from e
            if have not in SpecifierSet(spec):
                raise PackError(f"пакет {p.name} требует {dep} {spec}, загружен {by_name[dep].version}")
    order: list[Pack] = []
    done: set[str] = set()

    def visit(name: str, chain: tuple[str, ...]) -> None:
        if name in done:
            return
        if name in chain:
            loop = chain[chain.index(name):] + (name,)
            raise PackError(f"цикл в requires: {' → '.join(loop)}")
        for dep in sorted(by_name[name].requires):
            visit(dep, chain + (name,))
        done.add(name)
        order.append(by_name[name])

    visit("core", ())
    for name in sorted(by_name):
        visit(name, ())
    return order
```

В `load_packs` после проверки дубликатов имён: `packs = _ordered(packs)`, и дальше работать с упорядоченным списком. Проверка `broader` — в `load_packs` после сбора `owners` (коды всех пакетов известны):

```python
    codes: dict[str, set[str]] = {}
    for p in packs:
        for c in p.concepts:
            codes.setdefault(c.scheme, set()).add(c.code)
    for p in packs:
        for c in p.concepts:
            if c.broader and c.broader not in codes.get(c.scheme, set()):
                raise PackError(f"пакет {p.name}: {c.scheme}.{c.code}: broader {c.broader} — нет в словаре {c.scheme} загружаемых пакетов")
```

Тесты `test_requires_core_explicit_is_checked` проходят через ту же `_ordered` (`core` есть в `by_name`).

- [ ] **Step 7: `load_vocab`.** В `amemo/db.py` вставка в `pack`: `INSERT INTO pack (name, version, digest, requires, loaded_at) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (name, version) DO UPDATE SET requires = EXCLUDED.requires` с `Jsonb(p.requires)`. В `amemo/backup.py` `COUNTED` добавить `"atom_property", "import_history"`.
- [ ] **Step 8.** Focused: `tests/test_ontology_packs.py tests/test_packs.py tests/test_sql_schema.py tests/test_backup.py`. Полный прогон. Commit: `ontology: requires у пакетов — диапазоны semver, топологический порядок, циклы; broader проверяется; миграция 0007 (pack.requires, atom_property, import_history, причина imported); N новых тестов`.

---

### Task 3: Ядро 1.2.0

**Files:** `amemo/packs/core/pack.yaml`, `vocab/kind.yaml`, `vocab/entity_class.yaml`, `vocab/selector_type.yaml`, `templates/has_source.yaml`, `templates/note.yaml`, `tests/test_ontology_core.py`, тесты со счётом словаря ядра (`tests/test_packs.py::test_core_vocabulary_sizes` и подобные).

- [ ] **Step 1: падающие тесты** `tests/test_ontology_core.py`:

```python
from amemo import packs

CORE = packs.load_pack(packs.CORE_PACK)


def _codes(scheme):
    return {c.code for c in CORE.concepts if c.scheme == scheme}


def test_core_version():
    assert CORE.version == "1.2.0"


def test_core_new_codes():
    assert "note" in _codes("kind")
    assert "artifact" in _codes("entity_class")
    assert "bbox" in _codes("selector_type")


def test_has_source_skips_when_basis_set():
    t = next(t for t in CORE.templates if t.code == "has_source")
    assert t.version == "1.1.0"
    assert {r.path: r.skip_if_set for r in t.fields} == {"sources": "basis", "sources[].selectors": "basis"}


def test_note_template():
    t = next(t for t in CORE.templates if t.code == "note")
    assert t.applies_to == "note" and t.extends == ["has_label"]
    body = next(r for r in t.fields if r.path == "body")
    assert body.required is True and body.severity.value == "warning"
    assert t.links is None
```

- [ ] **Step 2.** Run: `env -u PYTHONPATH .venv/bin/pytest tests/test_ontology_core.py -q`. Expected: FAIL — версия 1.1.0.
- [ ] **Step 3: ядро.** `pack.yaml`: `version: 1.2.0`, в описание добавить «вид note, класс artifact, селектор bbox, шаблон note». В `vocab/kind.yaml`:

```yaml
- code: note
  label: {ru: заметка, en: note}
  definition: {ru: "Заметка человека — наблюдение, мысль, напоминание. Источник — сам автор (basis author)."}
```

В `vocab/entity_class.yaml`:

```yaml
- code: artifact
  label: {ru: изделие, en: artifact}
  definition: {ru: "Вещь, сделанная людьми: изделие, устройство, конструкция, узел, образец. Доменные классы уточняют его через broader."}
```

В `vocab/selector_type.yaml`:

```yaml
- code: bbox
  label: {ru: прямоугольник, en: bounding box}
  definition: {ru: "Прямоугольник на странице: x0,y0,x1,y1 в пунктах PDF от левого верхнего угла. Уточняет page или sheet через refined_by."}
```

`templates/has_source.yaml`:

```yaml
code: has_source
version: 1.1.0
target: atom
description: {ru: "Интерфейс для всех видов атомов: у атома есть источник и место в нём — если не задано основание basis (умолчание, допущение, утверждение автора). Что у PDF обязательны страница и цитата, проверяет уровень 2."}
fields:
  - path: sources
    required: true
    severity: violation
    skip_if_set: basis
    message: {ru: "У атома нет источника и не задано основание basis."}
  - path: sources[].selectors
    required: true
    severity: warning
    skip_if_set: basis
    message: {ru: "Не указано место в источнике — страница, пункт, лист."}
```

`templates/note.yaml`:

```yaml
code: note
version: 1.0.0
target: atom
applies_to: note
description: {ru: "Заметка: пояснение желательно; связи любые."}
extends: [has_label]
fields:
  - {path: body, required: true, severity: warning, message: {ru: "У заметки нет текста."}}
```

- [ ] **Step 4.** Обновить тесты, сверяющие счёт ядра (`test_core_vocabulary_sizes`: kind 9, entity_class 9, selector_type 13; число шаблонов ядра 5; версия `1.2.0` — найти `grep -rn "1.1.0" tests/`). Focused: `tests/test_ontology_core.py tests/test_packs.py tests/test_v1_templates.py tests/test_check_schema.py`. Полный прогон. Commit: `ontology: ядро 1.2.0 — note, artifact, bbox, has_source 1.1.0 со skip_if_set, шаблон note; N новых тестов`.

---

### Task 4: Профиль в шаблоне — проверка при загрузке и сведение

**Files:** `amemo/packs.py`, `amemo/check/templates.py`, `tests/packs/ontology/`, `tests/test_ontology_profile_rules.py`.

- [ ] **Step 1: тестовый пакет** `tests/packs/ontology/`:

```yaml
# pack.yaml
name: ontology
version: 1.0.0
title: Пакет для тестов профилей
description: Классы device и sensor с профилями, словарь parameter_origin, вид measurement.
license: MIT
requires: {quantities: ">=1.0.0,<2"}
```

```yaml
# vocab/entity_class.yaml
scheme: entity_class
concepts:
  - {code: device, label: {ru: устройство, en: device}, definition: {ru: "Устройство для теста."}, broader: artifact}
  - {code: sensor, label: {ru: датчик, en: sensor}, definition: {ru: "Датчик — частный случай устройства."}, broader: device}
```

```yaml
# vocab/parameter_origin.yaml
scheme: parameter_origin
concepts:
  - {code: datasheet, label: {ru: паспорт, en: datasheet}, definition: {ru: "Из паспорта изделия."}}
  - {code: measured, label: {ru: измерено, en: measured}, definition: {ru: "Измеряется на месте."}}
  - {code: method, label: {ru: по методике, en: method}, definition: {ru: "Умолчание методики, подтверждает инженер."}}
```

```yaml
# templates/device.yaml
code: device
version: 1.0.0
target: entity
applies_to: device
description: {ru: "Профиль устройства: масса обязательна, рабочая температура по умолчанию."}
parameters:
  - {property: mass, required: true, group: body, origin: datasheet, ask: {ru: "изготовитель"}, hint: {ru: "паспорт, табличка"}}
  - {property: temperature, required: false, group: environment, origin: method, default: {amount: 20, unit: Cel}, when: {ru: "если не задано заданием"}}
```

```yaml
# templates/sensor.yaml
code: sensor
version: 1.0.0
target: entity
applies_to: sensor
description: {ru: "Датчик: как устройство, но температура обязательна и измеряется; плюс длина кабеля."}
extends: [device]
parameters:
  - {property: temperature, required: true, group: environment, origin: measured}
  - {property: length, required: false, group: body, hint: {ru: "длина кабеля"}}
```

- [ ] **Step 2: падающие тесты** `tests/test_ontology_profile_rules.py`:

```python
"""Профили: проверка раздела parameters при загрузке пакетов и сведение по extends."""
import os
from pathlib import Path

import pytest
import yaml

from amemo import db, packs
from amemo.check import templates

PACKS = Path(__file__).with_name("packs")
ONTOLOGY, QUANTITIES = PACKS / "ontology", PACKS / "quantities"


def _with_template(tmp_path, body, requires=True):
    root = tmp_path / "p"
    (root / "templates").mkdir(parents=True)
    manifest = {"name": "p", "version": "1.0.0"}
    if requires:
        manifest["requires"] = {"quantities": ">=1.0.0"}
    (root / "pack.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    (root / "templates" / "t.yaml").write_text(yaml.safe_dump(body, allow_unicode=True), encoding="utf-8")
    return root


def _entity_template(**extra):
    return {"code": "t", "version": "1.0.0", "target": "entity", **extra}


def test_ontology_pack_loads():
    loaded = packs.load_packs([packs.CORE_PACK, QUANTITIES, ONTOLOGY])
    assert [p.name for p in loaded] == ["core", "quantities", "ontology"]


@pytest.mark.parametrize("parameters, message", [
    ([{"property": "nope"}], "property nope — нет в словаре property"),
    ([{"property": "mass", "origin": "rumor"}], "origin rumor — нет в словаре parameter_origin"),
    ([{"property": "mass", "default": {"amount": 1, "unit": "kilos"}}], "default.unit kilos — не код UCUM"),
    ([{"property": "mass", "default": {"amount": 1, "unit": "m"}}], "default.unit m не переводится в kg"),
    ([{"property": "mass"}, {"property": "mass"}], "property mass повторяется"),
])
def test_bad_parameters_name_file(tmp_path, parameters, message):
    root = _with_template(tmp_path, _entity_template(parameters=parameters))
    with pytest.raises(packs.PackError, match=message) as e:
        packs.load_packs([packs.CORE_PACK, QUANTITIES, root])
    assert "t.yaml" in str(e.value)


def test_parameters_only_for_entities(tmp_path):
    body = {"code": "t", "version": "1.0.0", "target": "atom", "parameters": [{"property": "mass"}]}
    root = _with_template(tmp_path, body)
    with pytest.raises(packs.PackError, match="parameters — только у шаблонов target entity"):
        packs.load_packs([packs.CORE_PACK, QUANTITIES, root])


def test_parameters_merge_by_property(pg, monkeypatch):
    monkeypatch.setenv("AMEMO_PACKS", os.pathsep.join([str(QUANTITIES), str(ONTOLOGY)]))
    db.prepare(pg)
    active = templates.active(pg)
    rules = templates.rules_for(active, "entity", "sensor")
    assert [r["property"] for r in rules.parameters] == ["mass", "temperature", "length"]
    temperature = rules.parameters[1]
    assert temperature["required"] is True and temperature["origin"] == "measured"
    assert "default" not in temperature                      # правило потомка заменяет правило предка целиком
    assert rules.parameter_origins["temperature"] == "sensor@1.0.0"
    assert rules.parameter_origins["mass"] == "device@1.0.0"
    assert templates.rules_for(active, "entity", "document").parameters == ()
```

- [ ] **Step 3.** Run: `env -u PYTHONPATH .venv/bin/pytest tests/test_ontology_profile_rules.py -q`. Expected: FAIL.
- [ ] **Step 4: проверка при загрузке.** В `amemo/packs.py` `_check_template` после проверки `fields`:

```python
    params = t.parameters or []
    if params and target != "entity":
        raise PackError(f"{file}: parameters — только у шаблонов target entity")
    seen_props: set[str] = set()
    for rule in params:
        if rule.property in seen_props:
            raise PackError(f"{file}: parameters: property {rule.property} повторяется")
        seen_props.add(rule.property)
        if rule.property not in codes.get("property", set()):
            raise PackError(f"{file}: parameters: property {rule.property} — нет в словаре property загружаемых пакетов")
        if rule.origin and rule.origin not in codes.get("parameter_origin", set()):
            raise PackError(f"{file}: parameters: {rule.property}: origin {rule.origin} — нет в словаре parameter_origin")
        default = rule.default
        if default is not None and default.unit is not None:
            from .check import units                     # локальный импорт: units тянет pint
            if not units.is_ucum(default.unit):
                raise PackError(f"{file}: parameters: {rule.property}: default.unit {default.unit} — не код UCUM")
            prop_unit = properties.get(rule.property)
            if prop_unit and units.convert(1.0, default.unit, prop_unit) is None:
                raise PackError(f"{file}: parameters: {rule.property}: default.unit {default.unit} не переводится в {prop_unit}")
```

`properties` — словарь `code → unit` понятий схемы `property`; собрать его в `_check_templates` рядом с `codes` (`{c.code: c.unit for p in packs for c in p.concepts if c.scheme == "property"}`) и передать в `_check_template` новым параметром.

- [ ] **Step 5: сведение.** В `amemo/check/templates.py` `Rules` получает `parameters: tuple[dict, ...] = ()` и `parameter_origins: dict[str, str] = field(default_factory=dict)`. В `rules_for` в цикле по `order`:

```python
        for rule in t.get("parameters") or []:
            params[rule["property"]] = dict(rule)          # dict сохраняет порядок первого появления
            parameter_origins[rule["property"]] = applied
```

где `params: dict[str, dict] = {}` объявлен до цикла; в возвращаемом `Rules`: `parameters=tuple(params.values()), parameter_origins=parameter_origins`. Порядок: `dict` хранит позицию первого появления ключа — у наследника это место правила предка, как требует спецификация (предки, затем свои).

- [ ] **Step 6.** Focused, полный прогон. Commit: `ontology: раздел parameters шаблона сущности — проверка при загрузке (величина, origin, UCUM, повтор, target), сведение по property; тестовые пакеты quantities и ontology; N новых тестов`.

---

### Task 5: Уровень 1 — `skip_if_set`, `basis`, `confidence`; политика человека

**Files:** `amemo/check/level1.py`, `amemo/check/__init__.py`, `tests/test_ontology_level1.py`.

Опора — спецификация подпроекта 3, разд. 3: правила полей проверяются функцией, которая перебирает `rules.fields` и для каждого пути вычисляет значение по телу. Ниже — что добавить; имена вспомогательных функций берутся из `level1.py` как есть.

- [ ] **Step 1: падающие тесты** `tests/test_ontology_level1.py` (фикстуры `pg`, `docs`, `store` как в `tests/test_check_level1.py`; построители из `tests/check_support.py`; пакеты `quantities` + `ontology` через `AMEMO_PACKS`):

```python
"""Уровень 1 и политика статусов: skip_if_set, basis, confidence, записи человека."""
import os
from pathlib import Path

import pytest

from amemo import check, db
from amemo.check import Proposal
from check_support import atom, source_md, value

PACKS = Path(__file__).with_name("packs")
MODEL, PERSON = "model:claude", "person:alice"


@pytest.fixture
def ready(pg, monkeypatch):
    monkeypatch.setenv("AMEMO_PACKS", os.pathsep.join([str(PACKS / "quantities"), str(PACKS / "ontology")]))
    db.prepare(pg)
    return pg


def _submit(conn, store, docs, payload, agent):
    return check.submit(conn, store, docs, [Proposal("atom", payload)], agent=agent)


def _codes(result):
    return {i.code for i in result.report.issues}


def test_model_without_source_rejected(ready, store, docs):
    r = _submit(ready, store, docs, atom("Масса 3 кг", kind="parameter", content={"values": [value("mass", 3, "kg")]}), MODEL)
    assert r.state == "rejected" and "template" in _codes(r)


def test_basis_default_skips_source_but_warns_without_rule(ready, store, docs):
    r = _submit(ready, store, docs, atom("Температура 20 °C", kind="parameter", basis="default",
                                         content={"values": [value("temperature", 20, "Cel")]}), MODEL)
    assert r.state == "approved" and "basis_without_rule" in _codes(r)
    assert r.records[0].status == "needs_review"


def test_basis_default_with_rule_is_clean(ready, store, docs):
    rule = _submit(ready, store, docs, atom("Температура по умолчанию 20 °C", kind="method", body={"ru": "В запас."},
                                            sources=[source_md("заметка.md", "20 °C")]), PERSON)
    rule_ref = f"atm:{rule.records[0].record_id}"
    r = _submit(ready, store, docs, atom("Температура 20 °C", kind="parameter", basis="default", derived_from=[rule_ref],
                                         content={"values": [value("temperature", 20, "Cel")]}), MODEL)
    assert r.state == "approved" and "basis_without_rule" not in _codes(r)
    assert r.records[0].status == "draft"


def test_basis_author_only_for_person(ready, store, docs):
    body = atom("Заметка", kind="note", body={"ru": "Проверить крепёж."}, basis="author")
    assert _submit(ready, store, docs, body, MODEL).state == "rejected"
    assert "basis_author_model" in _codes(_submit(ready, store, docs, body, MODEL))
    ok = _submit(ready, store, docs, body, PERSON)
    assert ok.state == "approved" and ok.records[0].status == "verified"
    assert ok.queued == [] and ok.complete is True


def test_person_without_basis_and_source_rejected(ready, store, docs):
    r = _submit(ready, store, docs, atom("Заметка", kind="note", body={"ru": "Текст."}), PERSON)
    assert r.state == "rejected"


def test_confidence_person_rejected(ready, store, docs):
    r = _submit(ready, store, docs, atom("Заметка", kind="note", body={"ru": "Текст."}, basis="author", confidence=0.9), PERSON)
    assert r.state == "rejected" and "confidence_person" in _codes(r)


def test_low_confidence_needs_review_only_with_rule(ready, store, docs, tmp_path, monkeypatch):
    # без правила в шаблоне низкая уверенность ничего не меняет
    r = _submit(ready, store, docs, atom("Масса 3 кг", kind="parameter", confidence=0.5,
                                         sources=[source_md("заметка.md", "3 кг")],
                                         content={"values": [value("mass", 3, "kg")]}), MODEL)
    assert r.records[0].status == "draft"
    # с правилом high_risk: [low_confidence] — к человеку
    from check_support import pack
    extra = pack(tmp_path / "risk", "risk", {"measurement": {
        "code": "measurement", "version": "1.0.0", "target": "atom", "applies_to": "measurement",
        "extends": ["has_label"], "high_risk": ["low_confidence"]}}, kinds=["measurement"])
    monkeypatch.setenv("AMEMO_PACKS", os.pathsep.join([str(PACKS / "quantities"), str(PACKS / "ontology"), str(extra)]))
    db.prepare(ready)
    low = _submit(ready, store, docs, atom("Масса 3 кг", kind="measurement", confidence=0.5,
                                           sources=[source_md("заметка.md", "3 кг")],
                                           content={"values": [value("mass", 3, "kg")]}), MODEL)
    assert low.records[0].status == "needs_review"
    assert any(q.reason == "high_risk" for q in low.queued)
    assert "template:measurement:low_confidence" in low.report.records[0]["risk"]
    high = _submit(ready, store, docs, atom("Масса 4 кг", kind="measurement", confidence=0.95,
                                            sources=[source_md("заметка.md", "4 кг")],
                                            content={"values": [value("mass", 4, "kg")]}), MODEL)
    assert high.records[0].status == "draft"


def test_person_edit_of_model_atom_is_verified_and_model_edit_of_person_is_pending(ready, store, docs):
    first = _submit(ready, store, docs, atom("Масса 3 кг", kind="parameter", sources=[source_md("заметка.md", "3 кг")],
                                             content={"values": [value("mass", 3, "kg")]}), MODEL)
    rid = first.records[0].record_id
    edited = atom("Масса 3,0 кг", kind="parameter", sources=[source_md("заметка.md", "3 кг")],
                  content={"values": [value("mass", 3, "kg")]}, summary_plain={"ru": "Паспортная масса."})
    by_person = check.submit(ready, store, docs, [Proposal("atom", edited, record_id=rid)], agent=PERSON)
    assert by_person.records[0].status == "verified" and by_person.records[0].review_state == "none"
    again = {**edited, "summary_plain": {"ru": "Масса с упаковкой."}}
    by_model = check.submit(ready, store, docs, [Proposal("atom", again, record_id=rid)], agent=MODEL)
    assert by_model.records[0].review_state == "pending"
```

Файл `заметка.md` с текстом «3 кг», «4 кг», «20 °C» — добавить в `tests/samples.make_docs`, если его там нет (одна строка на фразу).

- [ ] **Step 2.** Run: `env -u PYTHONPATH .venv/bin/pytest tests/test_ontology_level1.py -q`. Expected: FAIL.
- [ ] **Step 3: `skip_if_set`.** В `level1.py` в месте, где правило поля применяется к телу, перед вычислением правила:

```python
def _is_set(body: dict, path: str) -> bool:
    node = body
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return node not in (None, "", [], {})
```

и `if rule.get("skip_if_set") and _is_set(body, rule["skip_if_set"]): continue`.

- [ ] **Step 4: жёсткие правила** (там же, где спецификация 3 помещает «жёсткие правила», разд. 3.3), для атомов:

```python
    basis = body.get("basis")
    if basis == "author" and agent.startswith("model:"):
        report.violation(1, "basis_author_model", f"{label}: basis", "basis author может ставить только человек")
    if basis in ("default", "assumed") and not body.get("derived_from"):
        report.warning(1, "basis_without_rule", f"{label}: basis",
                       "умолчание или допущение без derived_from на правило методики")
    if body.get("confidence") is not None and agent.startswith("person:"):
        report.violation(1, "confidence_person", f"{label}: confidence", "confidence заполняет только модель")
```

Имена методов отчёта (`violation`/`warning` или единый `add(level, severity, code, where, message)`) — как в `amemo/check/report.py`.

- [ ] **Step 5: риск `low_confidence`.** В `amemo/check/__init__.py`: `LOW_CONFIDENCE = 0.8`. Где считается риск записи (строки `template:<code>:always` / `:numeric`), добавить: если `"low_confidence" in rules.high_risk` и `body.get("confidence") is not None and body["confidence"] < LOW_CONFIDENCE` — риск `f"template:{origin_code}:low_confidence"`, где `origin_code` — код шаблона, принёсшего правило (как для `always`).
- [ ] **Step 6: политика человека.** В `submit`, где по замечаниям и риску выбирается плановый статус (разд. 7.1 спецификации 3): если `agent.startswith("person:")` — статус `verified`, `review_state = "none"`, риск не учитывается, пункты очереди не ставятся, `levels["5"] = "not_applicable"`. Для существующей записи: `Item.review_state = "none"` даже если текущая ревизия `verified`. Правка моделью записи, у которой текущая ревизия записана агентом `person:` или статус `verified`, — `pending` (как раньше по статусу; добавить проверку агента текущей ревизии: `SELECT c.agent FROM atom_revision r JOIN changeset c ON c.id = r.changeset_id WHERE r.id = <current revision>`).
- [ ] **Step 7.** Focused: `tests/test_ontology_level1.py tests/test_check_level1.py tests/test_check_submit.py`. Полный прогон. Commit: `ontology: уровень 1 — skip_if_set, правила basis и confidence, риск low_confidence; записи человека получают verified без очереди; N новых тестов`.

---

### Завершение части A

- [ ] README и README.ru: в «Устройство» — абзац о `basis`, `confidence` и зависимостях пакетов; в «Пакеты домена» — `requires`.
- [ ] Ревью всей ветки субагентом; Critical и Important исправлены.
- [ ] Полный прогон на pg18 и pg16, `gen_schema.py --check`, проверка на приватное (скрипт в scratchpad). Пуш, PR, CI зелёный, слияние.

---

## Часть B — проекция величин и карточка (ветка `subproject-3c-profiles` от `main` после A)

### Task 6: Проекция `atom_property` и `rebuild_projections`

**Files:** `amemo/records.py`, `tests/test_profile_projection.py`.

- [ ] **Step 1: падающие тесты** `tests/test_profile_projection.py`:

```python
"""Проекция atom_property: заполняется при записи, перестраивается, совпадает с телами."""
from amemo import db, records
from amemo.records import Item
from check_support import atom, entity, value

AGENT = "model:claude"


def _rows(pg):
    return set(pg.execute("SELECT r.atom_id, p.property FROM atom_property p "
                          "JOIN atom_current r ON r.revision_id = p.revision_id").fetchall())


def _expected(pg):
    rows = pg.execute("SELECT atom_id, payload FROM atom_current").fetchall()
    return {(atom_id, v["property"]) for atom_id, payload in rows
            for v in (payload.get("content") or {}).get("values") or []}


def test_projection_follows_current_revision(pg):
    db.prepare(pg)
    body = atom("Масса и длина", kind="parameter", sources=[],
                content={"values": [value("mass", 3, "kg"), value("length", 2, "m")]})
    body["basis"] = "author"
    done = records.commit(pg, [Item("atom", body)], agent="person:alice")
    rid = done.revisions[0].record_id
    assert _rows(pg) == {(rid, "mass"), (rid, "length")} == _expected(pg)
    body2 = {**body, "content": {"values": [value("mass", 4, "kg")]}}
    records.commit(pg, [Item("atom", body2, record_id=rid)], agent="person:alice")
    assert _rows(pg) == {(rid, "mass")} == _expected(pg)


def test_rebuild_projections_is_idempotent(pg):
    db.prepare(pg)
    body = atom("Масса", kind="parameter", sources=[], content={"values": [value("mass", 3, "kg")]})
    body["basis"] = "author"
    records.commit(pg, [Item("atom", body)], agent="person:alice")
    pg.execute("DELETE FROM atom_property")
    records.rebuild_projections(pg)
    assert _rows(pg) == _expected(pg)
    records.rebuild_projections(pg)
    assert _rows(pg) == _expected(pg)
```

Атомы в этом тесте записываются `records.commit` напрямую (без автопроверки), поэтому `sources: []` допустим.

- [ ] **Step 2.** Run. Expected: FAIL — таблица пуста / функции нет.
- [ ] **Step 3: запись.** В `records._write_revision` после вставок `atom_about` / `atom_derived`:

```python
        for prop in sorted({v["property"] for v in (body.get("content") or {}).get("values") or []}):
            conn.execute("INSERT INTO atom_property (revision_id, property) VALUES (%s, %s)", (revision_id, prop))
```

Новая функция:

```python
def rebuild_projections(conn: psycopg.Connection) -> None:
    """Перестроить atom_about, atom_derived и atom_property по всем ревизиям атомов. Идемпотентно."""
    _require_autocommit(conn)
    with conn.transaction():
        conn.execute("DELETE FROM atom_about")
        conn.execute("DELETE FROM atom_derived")
        conn.execute("DELETE FROM atom_property")
        for revision_id, body in conn.execute("SELECT id, payload FROM atom_revision").fetchall():
            for entity_id in _ids(body, "about[]"):
                conn.execute("INSERT INTO atom_about (revision_id, entity_id) VALUES (%s, %s)", (revision_id, entity_id))
            for atom_id in _ids(body, "derived_from[]"):
                conn.execute("INSERT INTO atom_derived (revision_id, atom_id) VALUES (%s, %s)", (revision_id, atom_id))
            for prop in sorted({v["property"] for v in (body.get("content") or {}).get("values") or []}):
                conn.execute("INSERT INTO atom_property (revision_id, property) VALUES (%s, %s)", (revision_id, prop))
```

Проверить, что `atom_about` и `atom_derived` не защищены триггером от `DELETE`; если защищены — перестраивать только `atom_property` и переименовать описание.

- [ ] **Step 4.** Focused, полный прогон (тесты бэкапа считают `atom_property`). Commit: `profile: проекция atom_property при записи ревизии и rebuild_projections; N новых тестов`.

---

### Task 7: Карточка `profile.card`

**Files:** `amemo/profile.py`, `amemo/schema/amemo_v1.yaml` (классы `Card`, `CardField` — только для документации JSON Schema), `tests/test_profile_card.py`.

- [ ] **Step 1: падающие тесты** `tests/test_profile_card.py` (пакеты `quantities` + `ontology`; записи — через `records.commit`, статусы — через `Item.status`):

```python
"""Карточка сущности: состояния полей, признаки значения, предки по part_of, extra."""
import os
from pathlib import Path

import pytest

from amemo import db, profile, records
from amemo.records import Item
from check_support import atom, entity, value

PACKS = Path(__file__).with_name("packs")
MODEL, PERSON = "model:claude", "person:alice"


@pytest.fixture
def ready(pg, monkeypatch):
    monkeypatch.setenv("AMEMO_PACKS", os.pathsep.join([str(PACKS / "quantities"), str(PACKS / "ontology")]))
    db.prepare(pg)
    return pg


def _entity(conn, label, cls, **fields):
    done = records.commit(conn, [Item("entity", entity(label, cls=cls, **fields))], agent=PERSON)
    return f"ent:{done.revisions[0].record_id}"


def _param(conn, about, prop, amount, unit, *, agent=MODEL, status="draft", **extra):
    body = atom(f"{prop} {amount}", kind="parameter", about=[about], sources=[],
                content={"values": [value(prop, amount, unit, **extra.pop("value_extra", {}))]}, **extra)
    body.setdefault("basis", "author" if agent.startswith("person") else None)
    body = {k: v for k, v in body.items() if v is not None}
    done = records.commit(conn, [Item("atom", body, status=status)], agent=agent)
    return f"atm:{done.revisions[0].record_id}"


def _field(card, prop):
    return next(f for f in card["fields"] if f["property"] == prop)


def test_missing_and_known(ready):
    dev = _entity(ready, "Насос", "device")
    card = profile.card(ready, dev)
    assert card["format"] == "amem.card/1" and card["profile"] == "device@1.0.0"
    assert [f["property"] for f in card["fields"]] == ["mass", "temperature"]
    assert _field(card, "mass")["state"] == "missing" and _field(card, "mass")["required"] is True
    assert _field(card, "temperature")["default"] == {"amount": 20, "unit": "Cel"}
    assert card["summary"]["blockers_open"] == 1
    a = _param(ready, dev, "mass", 12, "kg")
    f = _field(profile.card(ready, dev), "mass")
    assert f["state"] == "known" and f["value"] == {"amount": 12, "unit": "kg"}
    assert f["by"] == "model" and f["status"] == "draft" and f["atoms"] == [a]
    assert profile.card(ready, dev)["summary"]["blockers_open"] == 0


def test_default_basis_is_a_value_only_when_recorded(ready):
    dev = _entity(ready, "Насос", "device")
    assert _field(profile.card(ready, dev), "temperature")["state"] == "missing"
    _param(ready, dev, "temperature", 20, "Cel", basis="default")
    f = _field(profile.card(ready, dev), "temperature")
    assert f["state"] == "known" and f["basis"] == "default"


def test_na_unknown_asked(ready):
    dev = _entity(ready, "Насос", "device")
    _param(ready, dev, "temperature", None, None, value_extra={"value_state": "none"})
    assert _field(profile.card(ready, dev), "temperature")["state"] == "na"
    sensor = _entity(ready, "Датчик", "sensor")
    _param(ready, sensor, "length", None, None, value_extra={"value_state": "unknown"})
    assert _field(profile.card(ready, sensor), "length")["state"] == "missing"
    q = atom("Какова масса?", kind="question", about=[sensor], sources=[], basis="author",
             content={"values": [{"property": "mass", "value_state": "unknown"}]})
    records.commit(ready, [Item("atom", q)], agent=PERSON)
    assert _field(profile.card(ready, sensor), "mass")["state"] == "asked"


def test_conflict_and_preferred(ready):
    dev = _entity(ready, "Насос", "device")
    a = _param(ready, dev, "mass", 12, "kg")
    b = _param(ready, dev, "mass", 12000, "g")          # то же после перевода единиц — не конфликт
    assert _field(profile.card(ready, dev), "mass")["state"] == "known"
    c = _param(ready, dev, "mass", 15, "kg")
    f = _field(profile.card(ready, dev), "mass")
    assert f["state"] == "conflict" and {x["atom"] for x in f["candidates"]} == {a, b, c}
    _param(ready, dev, "mass", 15, "kg", rank="preferred", agent=PERSON, status="verified")
    f = _field(profile.card(ready, dev), "mass")
    assert f["state"] == "known" and f["value"]["amount"] == 15 and f["by"] == "person" and len(f["candidates"]) == 3


def test_retired_atoms_ignored(ready):
    dev = _entity(ready, "Насос", "device")
    a = _param(ready, dev, "mass", 12, "kg")
    records.set_status(ready, "atom", a.split(":")[1], "rejected", agent=PERSON, reason="ошибка")
    assert _field(profile.card(ready, dev), "mass")["state"] == "missing"


def test_ancestors_by_part_of(ready):
    rack = _entity(ready, "Стойка", "device")
    sensor = _entity(ready, "Датчик", "sensor")
    records.commit(ready, [], [{"rel": "part_of", "src": sensor, "dst": rack}], agent=PERSON)
    _param(ready, rack, "mass", 40, "kg")
    card = profile.card(ready, sensor)
    assert [a["entity"]["ref"] for a in card["ancestors"]] == [rack]
    assert _field(card["ancestors"][0], "mass")["state"] == "known"
    assert profile.card(ready, sensor, ancestors=False)["ancestors"] == []
    records.commit(ready, [], [{"rel": "part_of", "src": rack, "dst": sensor}], agent=PERSON)   # цикл
    assert len(profile.card(ready, sensor)["ancestors"]) == 1


def test_entity_without_profile_lists_extra(ready):
    doc = _entity(ready, "Паспорт", "document")
    _param(ready, doc, "mass", 1, "kg")
    card = profile.card(ready, doc)
    assert card["profile"] is None and card["fields"] == []
    assert [e["property"] for e in card["extra"]] == ["mass"]
```

- [ ] **Step 2.** Run. Expected: FAIL — нет модуля `profile`.
- [ ] **Step 3: реализация** `amemo/profile.py`:

```python
"""Профиль сущности и карточка amem.card/1 (спецификация 3c, разд. 3).

Карточка не хранится: для каждой величины профиля класса сущности берутся действующие атомы parameter о ней
(текущая ревизия, статус не rejected / deprecated / superseded), и по ним выводится состояние поля.
Умолчание профиля показывается, но значением не считается. Предки — по действующим связям part_of вверх.
"""
from __future__ import annotations

import uuid

import psycopg

from . import lookup
from .check import templates, units

RETIRED = ("rejected", "deprecated", "superseded")
FORMAT = "amem.card/1"


def rules_for_entity(conn, entity_class: str) -> templates.Rules:
    return templates.rules_for(templates.active(conn), "entity", entity_class)


def _uuid(ref: str) -> uuid.UUID:
    return uuid.UUID(ref.split(":", 1)[1])


def _parameter_atoms(conn, entity_id: uuid.UUID, kinds: tuple[str, ...]) -> list[dict]:
    """Действующие атомы данных видов о сущности с их величинами, автором и статусом."""
    rows = conn.execute(
        "SELECT r.atom_id, r.revision_id, r.payload, a.status, c.agent "
        "FROM atom_current r JOIN atom a ON a.id = r.atom_id "
        "JOIN atom_about ab ON ab.revision_id = r.revision_id "
        "JOIN atom_revision rev ON rev.id = r.revision_id JOIN changeset c ON c.id = rev.changeset_id "
        "WHERE ab.entity_id = %s AND a.kind = ANY(%s) AND a.status <> ALL(%s) ORDER BY r.atom_id",
        (entity_id, list(kinds), list(RETIRED))).fetchall()
    return [{"atom_id": r[0], "revision_id": r[1], "payload": r[2], "status": r[3], "agent": r[4]} for r in rows]


def _values_of(record: dict, prop: str) -> list[dict]:
    return [v for v in (record["payload"].get("content") or {}).get("values") or [] if v.get("property") == prop]


def _canonical(v: dict, unit: str | None) -> tuple:
    """Значение для сравнения: число в единице величины (если переводится) или текст."""
    if v.get("amount") is not None:
        amount = v["amount"]
        if unit and v.get("unit") and v["unit"] != unit:
            converted = units.convert(amount, v["unit"], unit)
            if converted is not None:
                return ("n", round(converted, 9), unit)
        return ("n", round(amount, 9), v.get("unit"))
    return ("t", v.get("value_text"))


def _value_json(v: dict) -> dict:
    return {k: v[k] for k in ("amount", "unit", "value_text", "lower_bound", "upper_bound") if v.get(k) is not None}


def _candidate(conn, record: dict, v: dict) -> dict:
    p = record["payload"]
    return {"atom": f"atm:{record['atom_id']}", "value": _value_json(v), "status": record["status"],
            "by": record["agent"].split(":")[0], "basis": p.get("basis"), "rank": p.get("rank"),
            "confidence": p.get("confidence"),
            "source_role": next((s.get("role") for s in p.get("sources") or [] if s.get("role")), None),
            "sources": lookup.revision_sources(conn, "atom", record["revision_id"])}


def _field(conn, rule: dict, params: list[dict], questions: list[dict], prop_unit: str | None) -> dict:
    prop = rule["property"]
    out = {"property": prop, "required": bool(rule.get("required")), "group": rule.get("group"),
           "origin": rule.get("origin"), "default": rule.get("default"), "ask": rule.get("ask"),
           "hint": rule.get("hint"), "when": rule.get("when"), "state": "missing", "value": None,
           "atoms": [], "candidates": []}
    pairs = [(r, v) for r in params for v in _values_of(r, prop)]
    if not pairs:
        if any(_values_of(q, prop) for q in questions):
            out["state"] = "asked"
        return out
    if all(v.get("value_state") == "none" for _, v in pairs):
        out["state"], out["atoms"] = "na", [f"atm:{r['atom_id']}" for r, _ in pairs]
        return out
    known = [(r, v) for r, v in pairs if v.get("value_state", "known") == "known"]
    if not known:                                              # только unknown — документ величину не называет
        out["atoms"] = [f"atm:{r['atom_id']}" for r, _ in pairs]
        return out
    candidates = [_candidate(conn, r, v) for r, v in known if r["payload"].get("rank") != "deprecated"] or \
                 [_candidate(conn, r, v) for r, v in known]
    distinct = {_canonical(v, prop_unit) for r, v in known if r["payload"].get("rank") != "deprecated"} or \
               {_canonical(v, prop_unit) for _, v in known}
    preferred = [(r, v) for r, v in known if r["payload"].get("rank") == "preferred"]
    chosen = preferred[0] if preferred else (known[0] if len(distinct) == 1 else None)
    out["candidates"] = candidates if len(candidates) > 1 else []
    if chosen is None:
        out["state"], out["atoms"] = "conflict", [c["atom"] for c in candidates]
        return out
    r, v = chosen
    c = _candidate(conn, r, v)
    out.update({"state": "known", "value": c["value"], "atoms": [c["atom"]], "status": c["status"], "by": c["by"],
                "basis": c["basis"], "confidence": c["confidence"], "source_role": c["source_role"],
                "sources": c["sources"]})
    return out


def _one(conn, entity_id: uuid.UUID) -> dict:
    record = lookup.get(conn, "entity", entity_id)      # поля тела + id, revision, content_hash, status, agent…
    if record is None:
        raise LookupError(f"ent:{entity_id}: нет такой сущности")
    rules = rules_for_entity(conn, record["entity_class"])
    prop_units = dict(conn.execute("SELECT code, data->>'unit' FROM concept WHERE scheme = 'property'").fetchall())
    params = _parameter_atoms(conn, entity_id, ("parameter",))
    questions = _parameter_atoms(conn, entity_id, ("question",))
    fields = [_field(conn, rule, params, questions, prop_units.get(rule["property"])) for rule in rules.parameters]
    covered = {f["property"] for f in fields}
    extra = []
    for r in params:
        for v in (r["payload"].get("content") or {}).get("values") or []:
            if v.get("property") not in covered:
                extra.append({"property": v["property"], **_candidate(conn, r, v)})
    own = [name for name in rules.templates if name.split("@")[0] == record["entity_class"]]
    states = {}
    for f in fields:
        states[f["state"]] = states.get(f["state"], 0) + 1
    return {
        "format": FORMAT,
        "entity": {"ref": f"ent:{entity_id}", "entity_class": record["entity_class"], "label": record["label"],
                   "codes": record.get("codes") or [], "status": record["status"]},
        "profile": own[0] if own else None,
        "templates": list(rules.templates),
        "fields": fields,
        "extra": extra,
        "summary": {"states": states,
                    "blockers_open": sum(1 for f in fields if f["required"] and f["state"] not in ("known", "na")),
                    "with_basis": [f["property"] for f in fields if f.get("basis")]},
        "ancestors": [],
    }


def _parents(conn, entity_id: uuid.UUID) -> list[uuid.UUID]:
    rows = conn.execute("SELECT dst_entity FROM link WHERE rel = 'part_of' AND src_entity = %s AND dst_entity IS NOT NULL "
                        "AND retired_at IS NULL ORDER BY dst_entity", (entity_id,)).fetchall()
    return [r[0] for r in rows]


def card(conn: psycopg.Connection, ref: str, *, ancestors: bool = True) -> dict:
    """Карточка сущности формата amem.card/1; ancestors — карточки предков по part_of в порядке обхода в ширину."""
    root = _uuid(ref)
    out = _one(conn, root)
    if ancestors:
        seen, queue = {root}, _parents(conn, root)
        while queue:
            parent = queue.pop(0)
            if parent in seen:
                continue
            seen.add(parent)
            out["ancestors"].append(_one(conn, parent))
            queue.extend(_parents(conn, parent))
    return out
```

`lookup.get` возвращает поля тела ревизии (`entity_class`, `label`, `codes`…) вместе с техническими `id`, `revision`, `content_hash`, `status`, `review_state`, `agent`, `recorded_at` (`lookup._record`); `revision_id` в нём нет — для сущности он карточке не нужен, а у атомов берётся из `atom_current`. Карточка «на момент» (`at`) в подпроект не входит: `at` у `lookup.get` есть, у атомов выбора ревизии на момент нет — отложено до интерфейса истории (подпроект 5), в спецификации 3c параметра `at` нет.

- [ ] **Step 4.** В `amemo_v1.yaml` добавить классы `CardField` (поля карточки с типами: `property`, `state` — перечень `CardState` {`known`, `missing`, `asked`, `na`, `conflict`}, `required`, `value: Any`, `atoms`, `candidates: Any`, остальные — `string`/`LangString`) и `Card` (`format` с шаблоном `^amem\.card/1$`, `entity: Any`, `profile`, `fields: CardField[]`, `extra: Any[]`, `summary: Any`, `ancestors: Any[]`). Тест в `test_profile_card.py`: `model_v1.Card.model_validate(profile.card(...))` проходит. Перегенерировать.
- [ ] **Step 5.** Focused, полный прогон. Commit: `profile: карточка amem.card/1 — состояния полей, признаки значения, конфликт и preferred, предки по part_of, extra; N новых тестов`.

---

### Завершение части B

- [ ] README: раздел «Профили и карточка» (что такое `parameters`, как читать `card`).
- [ ] Ревью ветки, полный прогон на двух базах, `gen_schema.py --check`, проверка на приватное, PR, CI, слияние.

---

## Часть C — подборки (ветка `subproject-3c-bundles` от `main` после B)

### Task 8: `records.commit(keep_ids=True)` и `objects.adopt`

**Files:** `amemo/records.py`, `amemo/objects.py`, `tests/test_bundle_lowlevel.py`.

- [ ] **Step 1: падающие тесты** `tests/test_bundle_lowlevel.py`:

```python
"""Низкоуровневые опоры подборок: запись с заданным id, принятие объекта с версиями и файлом."""
import hashlib
import uuid

import pytest

from amemo import db, lookup, objects, records
from amemo.ids import uuid7
from amemo.ocfl_store import ObjectStore
from amemo.records import Item
from check_support import atom

AGENT = "person:alice"


def test_keep_ids_creates_record_with_given_id(pg):
    db.prepare(pg)
    rid = uuid7()
    body = atom("Заметка", kind="note", body={"ru": "Текст."}, basis="author")
    done = records.commit(pg, [Item("atom", body, record_id=rid)], agent=AGENT, keep_ids=True)
    assert done.revisions[0].record_id == rid and done.revisions[0].n == 1
    assert lookup.get(pg, "atom", rid)["label"] == {"ru": "Заметка"}


def test_without_keep_ids_unknown_record_id_is_error(pg):
    db.prepare(pg)
    body = atom("Заметка", kind="note", body={"ru": "Текст."}, basis="author")
    with pytest.raises(records.RecordError, match="нет такой записи"):
        records.commit(pg, [Item("atom", body, record_id=uuid7())], agent=AGENT)


def test_keep_ids_existing_record_gets_new_revision(pg):
    db.prepare(pg)
    rid = uuid7()
    body = atom("Заметка", kind="note", body={"ru": "Текст."}, basis="author")
    records.commit(pg, [Item("atom", body, record_id=rid)], agent=AGENT, keep_ids=True)
    done = records.commit(pg, [Item("atom", {**body, "body": {"ru": "Другой."}}, record_id=rid)], agent=AGENT, keep_ids=True)
    assert done.revisions[0].n == 2


def test_adopt_object_with_versions_and_file(pg, tmp_path):
    db.prepare(pg)
    store = ObjectStore(tmp_path / "objects"); store.init(create=True)
    oid = uuid7()
    raw = b"hello"
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    file = tmp_path / "hello.txt"; file.write_bytes(raw)
    record = {"id": str(oid), "kind": "file", "original_name": "hello.txt", "media_type": "text/plain",
              "logical_paths": ["notes/hello.txt"],
              "versions": [{"n": 1, "digest": digest, "size": 5, "recorded_at": "2026-01-01T00:00:00+00:00"}]}
    objects.adopt(pg, store, record, files={digest: file}, agent=AGENT)
    got = lookup.get_object(pg, oid)
    assert got["versions"][0]["digest"] == digest and store.head(oid) == 1
    objects.adopt(pg, store, record, files={}, agent=AGENT)                 # повтор — ничего не меняет
    assert store.head(oid) == 1
    bad = {**record, "versions": [{**record["versions"][0], "digest": "sha256:" + "0" * 64}]}
    with pytest.raises(objects.ObjectError, match="digest версии 1 не совпадает"):
        objects.adopt(pg, store, bad, files={}, agent=AGENT)
```

- [ ] **Step 2.** Run. Expected: FAIL — `commit` не знает `keep_ids`.
- [ ] **Step 3: `keep_ids`.** В `records.commit` новый параметр `keep_ids: bool = False`. В разборе `planned`: если `item.record_id` задан — проверить существование `SELECT 1 FROM {target} WHERE id = %s`; нет записи и `keep_ids` — считать новой с этим id (пометить `_Planned.new = True`); нет записи и не `keep_ids` — `RecordError(f"{label}: нет такой записи")`. Дальше `existing` строится из `planned` с `new=False`, `_insert_record` вызывается для `new=True`. Поле `_Planned.new: bool = False` ставится и для записей без `record_id`.
- [ ] **Step 4: `objects.adopt`.**

```python
def adopt(conn: psycopg.Connection, store: ObjectStore, record: dict, *, files: dict[str, Path], agent: str) -> None:
    """Принять объект из подборки: строка object с тем же id, версии по digest, файлы — в OCFL, если есть.

    Существующие версии сверяются по digest: расхождение — ObjectError. Версии без файла остаются без копии:
    их источники получат вердикт no_file до появления файла."""
    _require_autocommit(conn)
    object_id = object_uuid(record["id"])
    with conn.transaction():
        at = _lock(conn)
        row = conn.execute("SELECT kind FROM object WHERE id = %s", (object_id,)).fetchone()
        if row is None:
            conn.execute("INSERT INTO object (id, kind, original_name, media_type, format_puid, url, retrieved_at, created_at) "
                         "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                         (object_id, record["kind"], record.get("original_name"), record.get("media_type"),
                          record.get("format_puid"), record.get("url"), record.get("retrieved_at"), at))
        elif row[0] != record["kind"]:
            raise ObjectError(f"obj:{object_id}: вид {row[0]}, в подборке {record['kind']}")
        for path in record.get("logical_paths") or []:
            if conn.execute("SELECT 1 FROM object_path WHERE path = %s", (path,)).fetchone() is None:
                _add_path(conn, path, object_id, at)
        have = {n: d for n, d in conn.execute("SELECT n, digest FROM object_version WHERE object_id = %s", (object_id,))}
        for v in sorted(record.get("versions") or [], key=lambda v: v["n"]):
            if v["n"] in have:
                if have[v["n"]] != v.get("digest"):
                    raise ObjectError(f"obj:{object_id}: digest версии {v['n']} не совпадает с локальным")
                continue
            conn.execute("INSERT INTO object_version (object_id, n, digest, size, recorded_at) VALUES (%s, %s, %s, %s, %s)",
                         (object_id, v["n"], v.get("digest"), v.get("size"), v.get("recorded_at") or at))
            file = files.get(v.get("digest"))
            if file is not None and record["kind"] == "file":
                store.add_version(object_id, v["n"], file, record.get("original_name") or file.name,
                                  v["digest"], user=agent)
```

Имена столбцов `object` и `object_version` сверить с `0002_objects.sql`; `store.add_version` — сигнатура в `ocfl_store.py:239`. Если версии в OCFL должны идти подряд (`head + 1`), а в подборке пришла только версия 2 без файла версии 1 — пропустить копирование с предупреждением (вернуть список предупреждений из `adopt`).

- [ ] **Step 5.** Focused, полный прогон. Commit: `bundle: records.commit(keep_ids) создаёт запись с заданным id; objects.adopt принимает объект, версии и файлы; N новых тестов`.

---

### Task 9: Отбор, экспорт, `inspect`

**Files:** `amemo/bundle.py`, `amemo/schema/amemo_v1.yaml` (`BundleManifest`), `tests/test_bundle_export.py`.

- [ ] **Step 1: фикстура `store`.** В `tests/conftest.py` (если её ещё не добавила часть 3a):

```python
@pytest.fixture
def store(tmp_path):
    s = ObjectStore(tmp_path / "objects")
    s.init(create=True)
    return s
```

с `from amemo.ocfl_store import ObjectStore`. Тесты части C пишут атомы через `check.submit(conn, store, docs, …)`.

- [ ] **Step 1а: падающие тесты** `tests/test_bundle_export.py` (пакеты `quantities` + `ontology`; данные — через `check.submit`, чтобы были объекты и итоги сверки; подготовить проект `ent:` класса `project`, устройство с `part_of`, два атома с тегом `shared`, один с `visibility: private`, одну связь `see_also`):

```python
"""Экспорт подборки: отбор, замыкание, части, манифест, inspect."""
import json
import os
from pathlib import Path

import pytest

from amemo import bundle, check, db
from amemo.check import Proposal
from check_support import atom, entity, source_md, value

PACKS = Path(__file__).with_name("packs")
PERSON = "person:alice"


@pytest.fixture
def world(pg, monkeypatch, store, docs):
    monkeypatch.setenv("AMEMO_PACKS", os.pathsep.join([str(PACKS / "quantities"), str(PACKS / "ontology")]))
    db.prepare(pg)
    r = check.submit(pg, store, docs, [
        Proposal("entity", entity("Проект А", cls="project", ref="@p")),
        Proposal("entity", entity("Стойка", cls="device", ref="@rack")),
        Proposal("entity", entity("Датчик", cls="sensor", ref="@s")),
        Proposal("atom", atom("Масса 3 кг", kind="parameter", ref="@m", about=["@s"], tags=["shared"],
                              scope={"project": "@p"}, sources=[source_md("заметка.md", "3 кг")],
                              content={"values": [value("mass", 3, "kg")]})),
        Proposal("atom", atom("Заметка", kind="note", ref="@n", body={"ru": "Общая."}, basis="author", tags=["shared"])),
        Proposal("atom", atom("Личное", kind="note", ref="@priv", body={"ru": "Моё."}, basis="author", tags=["shared"],
                              scope={"visibility": "private"})),
        Proposal("atom", atom("Чужое", kind="note", ref="@other", body={"ru": "Не в теге."}, basis="author")),
    ], links=[{"rel": "part_of", "src": "@s", "dst": "@rack"}, {"rel": "see_also", "src": "@n", "dst": "@m",
                                                                "note": {"ru": "связаны"}}], agent=PERSON)
    assert r.state == "approved"
    return pg, r.refs


def _ids(path):
    return {json.loads(line)["id"] for line in path.read_text(encoding="utf-8").splitlines()}


def test_export_by_tag_closes_over_about_and_links(world, tmp_path):
    pg, refs = world
    out = tmp_path / "b"
    m = bundle.export(pg, store=None, folder=out, selection=bundle.Selection(tags=("shared",)), agent=PERSON)
    atoms, entities = _ids(out / "atoms.jsonl"), _ids(out / "entities.jsonl")
    assert atoms == {refs["@m"][4:], refs["@n"][4:]}                      # private исключён, @other не в теге
    assert entities == {refs["@s"][4:], refs["@p"][4:]}                  # about и scope.project; @rack — нет
    links = [json.loads(l) for l in (out / "links.jsonl").read_text().splitlines()]
    assert {l["rel"] for l in links} == {"see_also"}                     # part_of ведёт на @rack вне подборки
    assert m["format"] == "amem.bundle/1" and {p["name"] for p in m["packs"]} == {"core", "quantities", "ontology"}
    assert m["counts"] == {"atoms": 2, "entities": 2, "links": 1, "objects": 1, "concepts": 0}
    assert set(m["parts"]) >= {"atoms.jsonl", "entities.jsonl", "links.jsonl", "objects.jsonl", "sources.jsonl"}


def test_export_by_project_includes_part_of_chain(world, tmp_path):
    pg, refs = world
    out = tmp_path / "b"
    bundle.export(pg, store=None, folder=out, selection=bundle.Selection(project=refs["@p"]), agent=PERSON)
    assert _ids(out / "entities.jsonl") == {refs["@s"][4:], refs["@p"][4:], refs["@rack"][4:]}


def test_export_private_explicit(world, tmp_path):
    pg, refs = world
    out = tmp_path / "b"
    bundle.export(pg, store=None, folder=out, selection=bundle.Selection(tags=("shared",), include_private=True), agent=PERSON)
    assert refs["@priv"][4:] in _ids(out / "atoms.jsonl")


def test_export_with_files_and_inspect(world, tmp_path, store):
    pg, refs = world
    out = tmp_path / "b"
    bundle.export(pg, store=store, folder=out, selection=bundle.Selection(refs=(refs["@m"],)), agent=PERSON, with_files=True)
    files = list((out / "objects" / "sha256").iterdir())
    assert len(files) == 1
    info = bundle.inspect(out)
    assert info["counts"]["atoms"] == 1 and info["ok"] is True
    (out / "atoms.jsonl").write_text("{}\n", encoding="utf-8")
    assert bundle.inspect(out)["ok"] is False and "atoms.jsonl" in bundle.inspect(out)["damaged"]


def test_export_with_packs_checks_digest(world, tmp_path, monkeypatch):
    pg, refs = world
    out = tmp_path / "b"
    bundle.export(pg, store=None, folder=out, selection=bundle.Selection(tags=("shared",)), agent=PERSON, with_packs=True)
    assert (out / "packs" / "ontology" / "pack.yaml").exists()
    pg.execute("UPDATE pack SET digest = 'deadbeef' WHERE name = 'ontology'")
    with pytest.raises(bundle.BundleError, match="digest пакета ontology"):
        bundle.export(pg, store=None, folder=tmp_path / "c", selection=bundle.Selection(tags=("shared",)), agent=PERSON, with_packs=True)


def test_export_zip(world, tmp_path):
    pg, refs = world
    out = tmp_path / "b.zip"
    bundle.export(pg, store=None, folder=out, selection=bundle.Selection(tags=("shared",)), agent=PERSON)
    assert bundle.inspect(out)["ok"] is True
```

- [ ] **Step 2.** Run. Expected: FAIL — нет модуля `bundle`.
- [ ] **Step 3: реализация** `amemo/bundle.py` (экспортная половина):

```python
"""Подборки amem.bundle/1: отбор, экспорт, проверка, импорт (спецификация 3c, разд. 4)."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from . import __version__, canon, lookup, objects, packs, records, review
from .ids import uuid7

FORMAT = "amem.bundle/1"
DEFAULT_STATUSES = ("draft", "needs_review", "auto_verified", "verified", "deprecated", "superseded")
PARTS = ("entities.jsonl", "atoms.jsonl", "links.jsonl", "objects.jsonl", "sources.jsonl", "concepts.jsonl")
CODE_SCHEMES = {"atom": ("kind", "kind"), "entity": ("entity_class", "entity_class")}


class BundleError(ValueError):
    pass


@dataclass(frozen=True)
class Selection:
    tags: tuple[str, ...] = ()
    project: str | None = None
    kinds: tuple[str, ...] = ()
    entity_classes: tuple[str, ...] = ()
    refs: tuple[str, ...] = ()
    statuses: tuple[str, ...] = DEFAULT_STATUSES
    since: datetime | None = None
    include_private: bool = False

    def as_json(self) -> dict:
        return {k: (list(v) if isinstance(v, tuple) else v.isoformat() if isinstance(v, datetime) else v)
                for k, v in self.__dict__.items()}


def _uuid(ref: str) -> uuid.UUID:
    return uuid.UUID(ref.split(":", 1)[1])


def _descendants(conn, roots: set[uuid.UUID]) -> set[uuid.UUID]:
    """Сущности, достижимые от roots по действующим part_of вниз (src part_of dst, dst ∈ roots)."""
    seen, queue = set(roots), list(roots)
    while queue:
        node = queue.pop()
        for (child,) in conn.execute("SELECT src_entity FROM link WHERE rel = 'part_of' AND dst_entity = %s "
                                     "AND src_entity IS NOT NULL AND retired_at IS NULL", (node,)):
            if child not in seen:
                seen.add(child)
                queue.append(child)
    return seen


def _select(conn, s: Selection) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    """Атомы и сущности по условиям отбора (без замыкания)."""
    atoms: set[uuid.UUID] = set()
    entities: set[uuid.UUID] = set()
    for atom_id, payload, status, recorded_at in conn.execute(
            "SELECT r.atom_id, r.payload, a.status, r.recorded_at FROM atom_current r JOIN atom a ON a.id = r.atom_id"):
        if status not in s.statuses:
            continue
        if s.since and recorded_at < s.since:
            continue
        if not s.include_private and (payload.get("scope") or {}).get("visibility") == "private":
            continue
        ref = f"atm:{atom_id}"
        hits = []
        if s.tags:
            hits.append(bool(set(payload.get("tags") or []) & set(s.tags)))
        if s.kinds:
            hits.append(payload["kind"] in s.kinds)
        if s.project:
            about = set(payload.get("about") or [])
            hits.append((payload.get("scope") or {}).get("project") == s.project or s.project in about)
        if s.refs:
            hits.append(ref in s.refs)
        if hits and all(hits):
            atoms.add(atom_id)
    for entity_id, payload, status in conn.execute(
            "SELECT r.entity_id, r.payload, e.status FROM entity_current r JOIN entity e ON e.id = r.entity_id"):
        if status not in s.statuses:
            continue
        hits = []
        if s.entity_classes:
            hits.append(payload["entity_class"] in s.entity_classes)
        if s.refs:
            hits.append(f"ent:{entity_id}" in s.refs)
        if hits and all(hits):
            entities.add(entity_id)
    if s.project:
        project_id = _uuid(s.project)
        about_entities = {_uuid(a) for aid in atoms for a in (lookup.get(conn, "atom", aid)["about"] or [])}
        entities |= _descendants(conn, about_entities | {project_id}) | {project_id}
        # атомы о сущностях проекта тоже его атомы
        for entity_id in list(entities):
            for (atom_id,) in conn.execute("SELECT r.atom_id FROM atom_current r JOIN atom_about ab ON ab.revision_id = r.revision_id "
                                           "JOIN atom a ON a.id = r.atom_id WHERE ab.entity_id = %s AND a.status = ANY(%s)",
                                           (entity_id, list(s.statuses))):
                payload = lookup.get(conn, "atom", atom_id)
                if s.include_private or (payload.get("scope") or {}).get("visibility") != "private":
                    atoms.add(atom_id)
    return atoms, entities


def _closure(conn, atoms: set[uuid.UUID], entities: set[uuid.UUID]) -> set[uuid.UUID]:
    """Сущности из about, scope.project, sources[].edition атомов и edition_of сущностей."""
    out = set(entities)
    changed = True
    while changed:
        changed = False
        for aid in atoms:
            p = lookup.get(conn, "atom", aid)
            refs = list(p.get("about") or []) + [s["edition"] for s in p.get("sources") or [] if s.get("edition")]
            if (p.get("scope") or {}).get("project"):
                refs.append(p["scope"]["project"])
            for ref in refs:
                if _uuid(ref) not in out:
                    out.add(_uuid(ref)); changed = True
        for eid in list(out):
            p = lookup.get(conn, "entity", eid)
            for ref in [p.get("edition_of")] + [s["edition"] for s in p.get("sources") or [] if s.get("edition")]:
                if ref and _uuid(ref) not in out:
                    out.add(_uuid(ref)); changed = True
    return out


def _record_row(conn, target: str, record_id: uuid.UUID, with_history: bool) -> dict:
    """Запись подборки: проекция записи и текущая ревизия как есть (каноническое тело из {target}_revision)."""
    t = target
    r = conn.execute(
        f"SELECT r.revision_id, r.n, r.content_hash, r.payload, r.review_state, r.recorded_at, rec.key, rec.status, "
        f"rec.{CODE_SCHEMES[t][0]}, cs.agent FROM {t}_current r JOIN {t} rec ON rec.id = r.{t}_id "
        f"JOIN changeset cs ON cs.id = r.changeset_id WHERE r.{t}_id = %s", (record_id,)).fetchone()
    row = {"id": str(record_id), "key": r[6], CODE_SCHEMES[t][0]: r[8], "status": r[7],
           "revision": {"id": str(r[0]), "n": r[1], "content_hash": r[2], "payload": r[3], "agent": r[9],
                        "recorded_at": r[5].isoformat(), "review_state": r[4]}}
    if with_history:
        row["history"] = [h for h in lookup.history(conn, target, record_id) if h["n"] < r[1]]
    return row


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _packs_used(conn, atoms, entities, links) -> tuple[list[dict], list[dict]]:
    """Пакеты по кодам записей (владелец — concept.origin) и понятия агентов."""
    codes: set[tuple[str, str]] = set()
    for aid in atoms:
        p = lookup.get(conn, "atom", aid)
        codes.add(("kind", p["kind"]))
        for v in (p.get("content") or {}).get("values") or []:
            codes.add(("property", v["property"]))
        for q in p.get("qualifiers") or []:
            codes.add(("property", q["property"]))
        for s in p.get("sources") or []:
            for sel in s.get("selectors") or []:
                codes.add(("selector_type", sel["type"]))
    for eid in entities:
        codes.add(("entity_class", lookup.get(conn, "entity", eid)["entity_class"]))
    for l in links:
        codes.add(("rel", l["rel"]))
    owners, agent_concepts = set(), []
    for scheme, code in sorted(codes):
        row = conn.execute("SELECT origin, data FROM concept WHERE scheme = %s AND code = %s", (scheme, code)).fetchone()
        if row is None:
            continue
        if row[0] == "agent":
            agent_concepts.append(row[1])
        elif row[0] != "schema":
            owners.add(row[0])
    owners.add("core")
    rows = conn.execute("SELECT name, version, digest, requires FROM pack WHERE name = ANY(%s) ORDER BY name",
                        (sorted(owners),)).fetchall()
    # замыкание по requires
    names = {r[0] for r in rows}
    changed = True
    while changed:
        changed = False
        for _, _, _, req in rows:
            for dep in req or {}:
                if dep not in names:
                    names.add(dep); changed = True
        rows = conn.execute("SELECT name, version, digest, requires FROM pack WHERE name = ANY(%s) ORDER BY name",
                            (sorted(names),)).fetchall()
    return [{"name": n, "version": v, "digest": d, "requires": r or {}} for n, v, d, r in rows], agent_concepts


def export(conn: psycopg.Connection, *, store, folder: Path, selection: Selection, agent: str,
           with_files: bool = False, with_history: bool = False, with_packs: bool = False) -> dict:
    """Записать подборку в папку (или zip, если имя заканчивается на .zip); вернуть манифест."""
    folder = Path(folder)
    as_zip = folder.suffix == ".zip"
    work = folder.with_suffix(".tmp") if as_zip else folder
    if work.exists():
        raise BundleError(f"{work}: папка уже существует")
    work.mkdir(parents=True)
    atoms, entities = _select(conn, selection)
    entities = _closure(conn, atoms, entities)
    nodes = {str(x) for x in atoms | entities}
    links = [l for l in conn.execute(
        "SELECT id, rel, coalesce(src_atom, src_entity) AS src, src_atom IS NOT NULL AS src_is_atom, "
        "coalesce(dst_atom, dst_entity) AS dst, dst_atom IS NOT NULL AS dst_is_atom, note, qualifiers, confidence, "
        "created_at, agent, retired_at FROM link").fetchall() if str(l[2]) in nodes and str(l[4]) in nodes]
    link_rows = [{"id": str(l[0]), "rel": l[1], "src": f"{'atm' if l[3] else 'ent'}:{l[2]}",
                  "dst": f"{'atm' if l[5] else 'ent'}:{l[4]}", "note": l[6], "qualifiers": l[7], "confidence": l[8],
                  "created_at": l[9], "agent": l[10], "retired_at": l[11]} for l in links]
    atom_rows = [_record_row(conn, "atom", a, with_history) for a in sorted(atoms)]
    entity_rows = [_record_row(conn, "entity", e, with_history) for e in sorted(entities)]
    object_ids = {s["object"] for row in atom_rows + entity_rows for s in row["revision"]["payload"].get("sources") or [] if s.get("object")}
    object_rows = [lookup.get_object(conn, _uuid(o)) for o in sorted(object_ids)]
    source_rows = []
    for row in atom_rows + entity_rows:
        target = "atom" if "kind" in row else "entity"
        for s in lookup.revision_sources(conn, target, row["revision"]["id"]):
            source_rows.append({"revision_id": row["revision"]["id"], **s})
    pack_rows, concept_rows = _packs_used(conn, atoms, entities, link_rows)
    _write_jsonl(work / "entities.jsonl", entity_rows)
    _write_jsonl(work / "atoms.jsonl", atom_rows)
    _write_jsonl(work / "links.jsonl", link_rows)
    _write_jsonl(work / "objects.jsonl", object_rows)
    _write_jsonl(work / "sources.jsonl", source_rows)
    _write_jsonl(work / "concepts.jsonl", concept_rows)
    if with_files:
        if store is None:
            raise BundleError("with_files: нужно хранилище объектов")
        (work / "objects" / "sha256").mkdir(parents=True)
        for o in object_rows:
            if o["kind"] != "file":
                continue
            for v in o["versions"]:
                dst = work / "objects" / "sha256" / v["digest"].split(":", 1)[1]
                if not dst.exists():
                    shutil.copyfile(store.content(uuid.UUID(o["id"]), v["n"]), dst)
    if with_packs:
        by_name = {p.name: p for p in packs.load_packs()}
        for p in pack_rows:
            loaded = by_name.get(p["name"])
            if loaded is None or loaded.digest != p["digest"]:
                raise BundleError(f"digest пакета {p['name']} в базе не совпадает с папкой пакета — обновите базу (prepare)")
            shutil.copytree(loaded.path, work / "packs" / p["name"])
    parts = {name: _sha256(work / name) for name in PARTS}
    manifest = {"format": FORMAT, "created_at": datetime.now(timezone.utc).isoformat(), "agent": agent,
                "base_id": conn.execute("SELECT value FROM meta WHERE key = 'base_id'").fetchone()[0],
                "amem_version": __version__, "selection": selection.as_json(), "packs": pack_rows,
                "counts": {"atoms": len(atom_rows), "entities": len(entity_rows), "links": len(link_rows),
                           "objects": len(object_rows), "concepts": len(concept_rows)},
                "parts": parts, "with_files": with_files, "with_history": with_history, "with_packs": with_packs}
    (work / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    if as_zip:
        with zipfile.ZipFile(folder, "w") as z:
            for file in sorted(work.rglob("*")):
                if file.is_file():
                    z.write(file, file.relative_to(work).as_posix(),
                            compress_type=zipfile.ZIP_STORED if "objects/sha256" in file.as_posix() else zipfile.ZIP_DEFLATED)
        shutil.rmtree(work)
    return manifest


def _open(folder: Path) -> Path:
    """Папка подборки; zip распаковывается в соседнюю временную папку."""
    folder = Path(folder)
    if folder.suffix == ".zip":
        target = folder.with_suffix(".unzipped")
        if not target.exists():
            with zipfile.ZipFile(folder) as z:
                z.extractall(target)
        return target
    return folder


def inspect(folder: Path) -> dict:
    """Манифест и сверка частей без базы: ok, damaged, counts, packs."""
    root = _open(folder)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format") != FORMAT:
        raise BundleError(f"формат {manifest.get('format')!r}, ожидается {FORMAT}")
    damaged = [name for name, digest in manifest["parts"].items() if not (root / name).exists() or _sha256(root / name) != digest]
    return {**manifest, "ok": not damaged, "damaged": damaged, "root": str(root)}
```

`amemo.__version__` уже есть (`amemo/__init__.py`). Столбцы `{target}_current` (`revision_id`, `n`, `content_hash`, `payload`, `review_state`, `recorded_at`, `changeset_id`) — как в `0001_core.sql`; `lookup.history` отдаёт ревизии с ключами `n`, `content_hash`, `payload`, `recorded_at`, `agent` — если каких-то нет, расширить `history`, а не собирать историю в `bundle`. Распаковка zip в `_open` идёт в папку рядом с архивом (`<имя>.unzipped`) и остаётся после импорта — так `inspect` и `import_` видят одно и то же; `import_` удаляет её в конце, если создал сам.

- [ ] **Step 4.** В `amemo_v1.yaml` класс `BundleManifest` (поля манифеста; `format` с шаблоном `^amem\.bundle/1$`, `packs: Any[]`, `counts: Any`, `parts: Any`). Тест: `model_v1.BundleManifest.model_validate(manifest)` проходит. Перегенерировать.
- [ ] **Step 5.** Focused, полный прогон. Commit: `bundle: отбор по тегам, проекту, ссылкам; замыкание; формат amem.bundle/1 с частями, файлами, пакетами и zip; inspect; N новых тестов`.

---

### Task 10: Импорт

**Files:** `amemo/bundle.py`, `amemo/review.py` (пункты `imported`), `tests/test_bundle_import.py`.

- [ ] **Step 1: падающие тесты** `tests/test_bundle_import.py`. Две базы в одном тесте: фикстура `pg` даёт одну схему; вторую «базу» получить функцией `v1_support.same_database` с другой `search_path`? Нет — проще: экспорт из `pg`, затем `pg.execute("TRUNCATE ...")` невозможен (триггеры). Решение: фикстура `two(pg_pair)` — добавить в `conftest.py` фикстуру `pg2`, создающую вторую чистую схему на том же DSN тем же способом, что `pg` (вынести тело `pg` в помощник `_schema(dsn)`).

```python
"""Импорт подборки: id сохраняются, повтор идемпотентен, расхождение — pending, trust, пакеты, коллизии, dry_run."""
import json
import os
from pathlib import Path

import pytest

from amemo import bundle, check, db, lookup, records
from amemo.check import Proposal
from check_support import atom, entity, source_md, value

PACKS = Path(__file__).with_name("packs")
PERSON, OTHER = "person:alice", "person:bob"
ENV = os.pathsep.join([str(PACKS / "quantities"), str(PACKS / "ontology")])


def _prepare(conn, monkeypatch, env=ENV):
    monkeypatch.setenv("AMEMO_PACKS", env)
    db.prepare(conn)


def _seed(conn, store, docs):
    r = check.submit(conn, store, docs, [
        Proposal("entity", entity("Датчик", cls="sensor", ref="@s", key="sensor_1")),
        Proposal("atom", atom("Масса 3 кг", kind="parameter", ref="@m", about=["@s"], tags=["shared"],
                              sources=[source_md("заметка.md", "3 кг")], content={"values": [value("mass", 3, "kg")]})),
        Proposal("atom", atom("Заметка", kind="note", ref="@n", body={"ru": "Общая."}, basis="author", tags=["shared"])),
    ], links=[{"rel": "see_also", "src": "@n", "dst": "@m", "note": {"ru": "связаны"}}], agent=PERSON)
    assert r.state == "approved"
    return r.refs


def _export(conn, store, folder):
    return bundle.export(conn, store=store, folder=folder, selection=bundle.Selection(tags=("shared",)), agent=PERSON, with_files=True)


def test_import_into_empty_base_keeps_ids_and_is_idempotent(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    refs = _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    first = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    assert first.counts == {"created": 3, "unchanged": 0, "pending": 0, "skipped": 0, "links": 1, "objects": 1}
    got = lookup.get(pg2, "atom", refs["@m"][4:])
    assert got["status"] == "draft" and got["provenance"]["origin_agent"] == PERSON
    assert got["provenance"]["origin_base"] == pg.execute("SELECT value FROM meta WHERE key = 'base_id'").fetchone()[0]
    assert lookup.get(pg2, "entity", refs["@s"][4:])["key"] == "sensor_1"
    second = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    assert second.counts["created"] == 0 and second.counts["unchanged"] == 3


def test_import_divergence_is_pending_not_overwrite(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    refs = _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    rid = refs["@n"][4:]
    local = lookup.get(pg2, "atom", rid)
    check.submit(pg2, store2, docs, [Proposal("atom", {**_body(local), "body": {"ru": "Моя правка."}}, record_id=rid)], agent=OTHER)
    check.submit(pg, store, docs, [Proposal("atom", {**_body(lookup.get(pg, "atom", rid)), "body": {"ru": "Чужая правка."}}, record_id=rid)], agent=PERSON)
    _export(pg, store, tmp_path / "c")
    r = bundle.import_(pg2, store2, tmp_path / "c", agent=OTHER)
    assert r.counts["pending"] == 1
    assert lookup.get(pg2, "atom", rid)["body"] == {"ru": "Моя правка."}
    assert any(q["reason"] == "imported" for q in r.queued)


def _body(record):
    technical = {"id", "schema_version", "revision", "content_hash", "status", "review_state", "created_at",
                 "recorded_at", "changeset", "agent", "activity", "revision_id", "provenance"}
    return {k: v for k, v in record.items() if k not in technical and v is not None}


def test_trust_review(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    refs = _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    r = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER, trust="review")
    assert lookup.get(pg2, "atom", refs["@n"][4:])["status"] == "needs_review"
    assert len([q for q in r.queued if q["reason"] == "imported"]) == 3


def test_pack_missing_refuses_with_hint(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch)
    _seed(pg, store, docs)
    bundle.export(pg, store=store, folder=tmp_path / "b", selection=bundle.Selection(tags=("shared",)), agent=PERSON, with_packs=True)
    _prepare(pg2, monkeypatch, env=str(PACKS / "quantities"))        # без ontology
    with pytest.raises(bundle.BundleError, match="ontology 1.0.0") as e:
        bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    assert "AMEMO_PACKS" in str(e.value) and str(tmp_path / "b" / "packs" / "ontology") in str(e.value)
    assert pg2.execute("SELECT count(*) FROM atom").fetchone()[0] == 0


def test_key_collision_refuses(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    check.submit(pg2, store2, docs, [Proposal("entity", entity("Другой датчик", cls="sensor", key="sensor_1"))], agent=OTHER)
    with pytest.raises(bundle.BundleError, match="sensor_1"):
        bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    assert pg2.execute("SELECT count(*) FROM atom").fetchone()[0] == 0


def test_dry_run_writes_nothing(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    plan = bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER, dry_run=True)
    assert plan.counts["created"] == 3 and plan.changeset_id is None
    assert pg2.execute("SELECT count(*) FROM atom").fetchone()[0] == 0


def test_history_goes_to_import_history(pg, pg2, monkeypatch, store, store2, docs, tmp_path):
    _prepare(pg, monkeypatch); _prepare(pg2, monkeypatch)
    refs = _seed(pg, store, docs)
    rid = refs["@n"][4:]
    check.submit(pg, store, docs, [Proposal("atom", {**_body(lookup.get(pg, "atom", rid)), "body": {"ru": "Вторая."}}, record_id=rid)], agent=PERSON)
    bundle.export(pg, store=store, folder=tmp_path / "b", selection=bundle.Selection(tags=("shared",)), agent=PERSON, with_history=True)
    bundle.import_(pg2, store2, tmp_path / "b", agent=OTHER)
    assert pg2.execute("SELECT count(*) FROM atom_revision WHERE atom_id = %s", (rid,)).fetchone()[0] == 1
    assert pg2.execute("SELECT count(*) FROM import_history WHERE record_id = %s", (rid,)).fetchone()[0] == 2


def test_round_trip_to_own_base_is_unchanged(pg, monkeypatch, store, docs, tmp_path):
    _prepare(pg, monkeypatch)
    _seed(pg, store, docs)
    _export(pg, store, tmp_path / "b")
    r = bundle.import_(pg, store, tmp_path / "b", agent=PERSON)
    assert r.counts["created"] == 0 and r.counts["unchanged"] == 3 and r.counts["pending"] == 0
```

Фикстуры `pg2`, `store2` — в `conftest.py`: `pg2` — вторая схема на том же DSN, что и `pg` (параметризация общая: оба на одной базе одного параметра); `store2` — `ObjectStore(tmp_path / "objects2")` с `init(create=True)`.

- [ ] **Step 2.** Run. Expected: FAIL — нет `import_`.
- [ ] **Step 3: реализация** (импортная половина `amemo/bundle.py`):

```python
@dataclass
class Imported:
    changeset_id: uuid.UUID | None
    counts: dict[str, int]
    queued: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    complete: bool = True


def _check_packs(conn, manifest: dict, root: Path) -> None:
    have = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT name, version, digest FROM pack").fetchall()}
    missing = []
    for p in manifest["packs"]:
        if have.get(p["name"]) != (p["version"], p["digest"]):
            got = have.get(p["name"])
            missing.append(f"{p['name']} {p['version']} ({'нет' if got is None else f'загружен {got[0]}, другой digest' if got[0] == p['version'] else f'загружен {got[0]}'})")
    if missing:
        hint = ""
        if (root / "packs").is_dir():
            paths = os.pathsep.join(str(root / "packs" / p["name"]) for p in manifest["packs"] if (root / "packs" / p["name"]).is_dir())
            hint = f"; пакеты лежат в подборке: добавьте в AMEMO_PACKS {paths} и выполните prepare"
        raise BundleError("не загружены пакеты подборки: " + "; ".join(missing) + hint)


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _plan_record(conn, target: str, row: dict, origin_base: str, own_base: str) -> tuple[str, dict | None]:
    """Действие для записи подборки: created / unchanged / pending / skipped — и тело для записи."""
    record_id = uuid.UUID(row["id"])
    incoming = row["revision"]["payload"]
    incoming_hash = row["revision"]["content_hash"]
    local = lookup.get(conn, target, record_id)
    body = dict(incoming)
    if origin_base != own_base:
        body["provenance"] = {**(incoming.get("provenance") or {}), "origin_base": origin_base,
                              "origin_revision_hash": incoming_hash, "origin_agent": row["revision"]["agent"]}
    if local is None:
        return "created", body
    if local["status"] in ("deprecated", "superseded"):
        return "skipped", None
    local_hash = local["content_hash"]
    origin_hash = (local.get("provenance") or {}).get("origin_revision_hash")
    if local_hash == incoming_hash or origin_hash == incoming_hash:
        return "unchanged", None
    without_provenance = {k: v for k, v in _strip(local).items() if k != "provenance"}
    if canon.content_hash(canon.canonical(without_provenance, target)) == incoming_hash:
        return "unchanged", None
    return "pending", body


def _strip(record: dict) -> dict:
    technical = {"id", "schema_version", "revision", "content_hash", "status", "review_state", "created_at",
                 "recorded_at", "changeset", "agent", "activity", "revision_id"}
    return {k: v for k, v in record.items() if k not in technical and v is not None}


def import_(conn: psycopg.Connection, store, folder: Path, *, agent: str, trust: str = "keep",
            dry_run: bool = False) -> Imported:
    """Влить подборку: id сохраняются, ничего не затирается (спецификация 3c, разд. 4.3)."""
    if trust not in ("keep", "review"):
        raise BundleError(f"trust: {trust!r} — ожидается keep или review")
    info = inspect(folder)
    if not info["ok"]:
        raise BundleError(f"повреждены части подборки: {', '.join(info['damaged'])}")
    root = Path(info["root"])
    _check_packs(conn, info, root)
    own_base = conn.execute("SELECT value FROM meta WHERE key = 'base_id'").fetchone()[0]
    origin_base = info["base_id"]
    entities, atoms = _read_jsonl(root / "entities.jsonl"), _read_jsonl(root / "atoms.jsonl")
    links, objs, sources = _read_jsonl(root / "links.jsonl"), _read_jsonl(root / "objects.jsonl"), _read_jsonl(root / "sources.jsonl")
    concepts = _read_jsonl(root / "concepts.jsonl")
    warnings: list[str] = []

    # коллизии ключей — до записи
    collisions = []
    for target, rows in (("entity", entities), ("atom", atoms)):
        for row in rows:
            key = row.get("key")
            if key:
                owner = lookup.by_key(conn, target, key)
                if owner is not None and str(owner) != row["id"]:
                    collisions.append(f"{target} {key}: локально {owner}, в подборке {row['id']}")
    if collisions:
        raise BundleError("ключи заняты другими записями: " + "; ".join(collisions))

    plan: list[tuple[str, str, dict, dict | None]] = []          # (target, action, row, body)
    counts = {"created": 0, "unchanged": 0, "pending": 0, "skipped": 0, "links": 0, "objects": 0}
    for target, rows in (("entity", entities), ("atom", atoms)):
        for row in rows:
            action, body = _plan_record(conn, target, row, origin_base, own_base)
            counts[action] += 1
            plan.append((target, action, row, body))
    if dry_run:
        return Imported(None, counts, warnings=warnings)

    # понятия агентов
    for c in concepts:
        row = conn.execute("SELECT data FROM concept WHERE scheme = %s AND code = %s", (c["scheme"], c["code"])).fetchone()
        if row is None:
            conn.execute("INSERT INTO concept (scheme, code, data, origin, updated_at) VALUES (%s, %s, %s, 'agent', now())",
                         (c["scheme"], c["code"], Jsonb(c)))
        elif row[0] != c:
            warnings.append(f"понятие {c['scheme']}.{c['code']} отличается от локального; оставлено локальное")

    # объекты и файлы
    files = {f"sha256:{p.name}": p for p in (root / "objects" / "sha256").glob("*")} if (root / "objects").is_dir() else {}
    for o in objs:
        objects.adopt(conn, store, o, files=files, agent=agent)
        counts["objects"] += 1

    # уровень 1 для тел, которые будут записаны
    from .check import level1_for_import                       # вызов уровня 1 без уровней 2–4 (добавить в check)
    report = level1_for_import(conn, [(t, b) for t, a, _, b in plan if b is not None], agent=agent)
    if report.has_violations():
        raise BundleError("подборка не прошла уровень 1: " + report.summary())

    status_for = (lambda row: "needs_review") if trust == "review" else (lambda row: row["status"])
    items = []
    for target, action, row, body in plan:
        if body is None:
            continue
        items.append(records.Item(target, body, record_id=uuid.UUID(row["id"]),
                                  status=status_for(row) if action == "created" else None,
                                  review_state="none" if action == "created" else "pending"))
    link_payloads, link_meta = [], []
    for l in links:
        link_payloads.append({k: l[k] for k in ("rel", "src", "dst", "note", "qualifiers", "confidence") if l.get(k) is not None})
        link_meta.append(l)
    done = records.commit(conn, items, link_payloads, agent=agent, keep_ids=True,
                          reason=f"import {origin_base} {info['created_at']}")
    counts["links"] = len(done.links)
    queued = []
    with conn.transaction():
        for rev, (target, action, row, body) in zip(done.revisions, [p for p in plan if p[3] is not None]):
            if not rev.created:
                continue
            if trust == "review" or action == "pending":
                queued.append(review.insert_item(conn, target, rev.record_id, rev.revision_id, "imported",
                                                 changeset_id=done.changeset_id, created_by=agent,
                                                 details={"origin_base": origin_base, "action": action}))
            if info.get("with_history"):
                for h in row.get("history") or []:
                    conn.execute("INSERT INTO import_history (id, changeset_id, target, record_id, origin_base, n, content_hash, "
                                 "payload, recorded_at, agent) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                                 "ON CONFLICT (origin_base, record_id, n) DO NOTHING",
                                 (uuid7(), done.changeset_id, target, rev.record_id, origin_base, h["n"], h["content_hash"],
                                  Jsonb(h["payload"]), h["recorded_at"], h.get("agent")))
        for l, link_id in zip(link_meta, done.links):
            if l.get("retired_at"):
                row = conn.execute("SELECT retired_at FROM link WHERE id = %s", (link_id,)).fetchone()
                if row and row[0] is None:
                    records.retire_link(conn, link_id, agent=agent, reason="импорт: выведена в базе-источнике")
        # итоги сверки — только созданным ревизиям и только без файла для своей сверки
        created = {rev.revision_id for rev in done.revisions if rev.created}
        by_old = {row["revision"]["id"]: rev.revision_id for rev, (t, a, row, b) in
                  zip(done.revisions, [p for p in plan if p[3] is not None]) if rev.created}
        for s in sources:
            new_id = by_old.get(s["revision_id"])
            if new_id is None:
                continue
            has_file = conn.execute("SELECT 1 FROM object_version v JOIN source so ON so.object_id = v.object_id AND so.object_version = v.n "
                                    "WHERE coalesce(so.atom_revision_id, so.entity_revision_id) = %s AND v.digest = ANY(%s)",
                                    (new_id, list(files))).fetchone()
            if has_file is None:
                conn.execute("UPDATE source SET verdict = %s, page = %s WHERE coalesce(atom_revision_id, entity_revision_id) = %s AND position = %s",
                             (s.get("verdict") or "no_file", s.get("page"), new_id, s["position"]))
    return Imported(done.changeset_id, counts, queued=queued, warnings=warnings, complete=not queued)
```

Опоры, которые нужно добавить по месту:
- `check.level1_for_import(conn, bodies, *, agent) -> Report` — вызов уровня 1 для уже разрешённых тел (ссылки по UUID, источники с `object`/`object_version`), без шагов 2–4; записи с `created=False` после `commit` не считаются; `Report.has_violations()` и `Report.summary()` — если в `report.py` нет, добавить;
- `review.insert_item(...)` — сигнатура из части 3a (аргументы по спецификации 3, разд. 8.1); возвращает словарь пункта `{id, reason, record_id}`;
- `records.commit` с `review_state="pending"` у существующей записи — как уже делает `submit` для правок `verified`;
- итоги сверки `source.verdict` / `source.page` — имена столбцов из `0002_objects.sql`/`0006_check.sql`; триггер `amemo_source_check` разрешает это обновление;
- `_plan_record`: сравнение «тело без provenance даёт тот же хэш» — `canon.canonical(payload, target)` и `canon.content_hash(body)`, как в `records._prepare_body`.

- [ ] **Step 4.** Focused: `tests/test_bundle_import.py tests/test_bundle_export.py tests/test_bundle_lowlevel.py`. Полный прогон (бэкап считает `import_history`). Commit: `bundle: импорт — id сохраняются, повтор идемпотентен, расхождение pending с пунктом imported, trust, проверка пакетов и ключей до записи, dry_run, история в import_history; N новых тестов`.

---

### Завершение части C

- [ ] README и README.ru: раздел «Подборки» — формат, экспорт, импорт, доверие, что подборки не заменяют бэкап.
- [ ] Мутационные пробы (скрипт вне репозитория): убрать проверку digest пакета → тест `test_pack_missing_refuses_with_hint` красный; убрать `origin_revision_hash` из сравнения → `test_import_into_empty_base_keeps_ids_and_is_idempotent` красный; убрать фильтр `private` → `test_export_by_tag_closes_over_about_and_links` красный.
- [ ] Ревью всей ветки субагентом; Critical и Important исправлены.
- [ ] Полный прогон на pg18 и pg16, `gen_schema.py --check`, проверка на приватное. Пуш, PR с описанием и строкой `🤖 Generated with [Claude Code](https://claude.com/claude-code)`, CI зелёный, слияние.
- [ ] Спецификация: редакция 2 с уточнениями по итогам реализации (как у подпроекта 2).
