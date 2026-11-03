"""Общие помощники тестов схемы v1: примеры из tests/v1_examples и две проверки данных — по JSON Schema и по Pydantic."""
import copy
import json
from functools import lru_cache
from pathlib import Path

import jsonschema
import yaml
from jsonschema.validators import validator_for
from pydantic import ValidationError

from amem import model_v1

EXAMPLES = Path(__file__).with_name("v1_examples")
JSON_SCHEMA = Path(__file__).resolve().parents[1] / "amem" / "schema" / "amem_v1.schema.json"


def example(name: str) -> dict:
    """Пример как JSON-данные: даты YAML (2017-06-04) превращаются в строки, как их пришлёт MCP."""
    data = yaml.safe_load((EXAMPLES / name).read_text(encoding="utf-8"))
    return json.loads(json.dumps(data, default=str))


@lru_cache
def _schema() -> dict:
    return json.loads(JSON_SCHEMA.read_text(encoding="utf-8"))


def json_errors(class_name: str, data: dict) -> list[str]:
    """Проверка по JSON Schema; вариант (draft) берётся из самого файла схемы, а не прописан в тесте."""
    full = _schema()
    schema = {"$defs": full["$defs"], "$ref": f"#/$defs/{class_name}"}
    validator = validator_for(full)(schema, format_checker=jsonschema.FormatChecker())
    return [e.message for e in validator.iter_errors(data)]


def pydantic_errors(class_name: str, data: dict) -> list[str]:
    """Проверка моделью Pydantic по тексту JSON в строгом режиме: так сервер проверяет вход MCP.

    Строгий режим не превращает строку в число, число в дату и булево значение в число."""
    model = getattr(model_v1, class_name)
    try:
        model.model_validate_json(json.dumps(data, ensure_ascii=False), strict=True)
    except ValidationError as e:
        return [f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()]
    return []


def changed(name: str, change) -> dict:
    data = copy.deepcopy(example(name))
    change(data)
    return data


@lru_cache
def schema_yaml() -> dict:
    return yaml.safe_load((JSON_SCHEMA.parent / "amem_v1.yaml").read_text(encoding="utf-8"))


def schema_attrs(class_name: str) -> dict:
    """Поля класса LinkML вместе с полями предков (is_a); поле потомка важнее."""
    classes = schema_yaml()["classes"]
    cls, attrs = classes[class_name], {}
    while True:
        attrs = {**(cls.get("attributes") or {}), **attrs}
        if "is_a" not in cls:
            return attrs
        cls = classes[cls["is_a"]]


def same_database(conn, **kwargs):
    """Ещё одно соединение к той же тестовой базе и схеме, что у conn (фикстура pg)."""
    import psycopg

    schema = conn.execute("SELECT current_schema()").fetchone()[0]
    i = conn.info
    return psycopg.connect(host=i.host, port=i.port, dbname=i.dbname, user=i.user, password=i.password,
                           options=f"-c search_path={schema},public", **kwargs)
