"""Контракт HTTP v1 для тестов службы: схемы ответов из docs/api/http-v1.openapi.yaml и проверка ответа по ним.

OpenAPI 3.1 — это JSON Schema 2020-12, поэтому ответ проверяет jsonschema: документ контракта целиком — один ресурс
реестра (referencing), схема ответа берётся ссылкой на своё место в документе (JSON Pointer), и ссылки
«#/components/…» внутри неё разрешаются по тому же документу. Форматы uuid и date-time проверяются.
"""
from __future__ import annotations

from functools import cache
from pathlib import Path
from urllib.parse import quote

import jsonschema
import yaml
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "docs" / "api" / "http-v1.openapi.yaml"
URI = "urn:amem:http-v1"
JSON = ("application/json", "application/problem+json")


@cache
def spec() -> dict:
    return yaml.safe_load(PATH.read_text(encoding="utf-8"))


@cache
def _registry() -> Registry:
    return Registry().with_resource(URI, Resource.from_contents(spec(), default_specification=DRAFT202012))


def pointer(*parts) -> str:
    """JSON Pointer (RFC 6901) места в документе контракта как фрагмент URI."""
    return "#/" + "/".join(quote(str(p).replace("~", "~0").replace("/", "~1"), safe="") for p in parts)


def _at(ref: str):
    return _registry().resolver().lookup(URI + ref).contents


def validate(data, ref: str) -> None:
    """Проверить данные по схеме контракта в месте ref («#/components/schemas/X» или pointer(…)); ошибка —
    AssertionError со всеми местами расхождения."""
    validator = jsonschema.Draft202012Validator({"$ref": URI + ref}, registry=_registry(),
                                                format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    assert not errors, f"ответ не по контракту ({ref}):\n" + "\n".join(
        f"  {'/'.join(map(str, e.absolute_path)) or '(корень)'}: {e.message}" for e in errors[:20])


def component(name: str, data) -> None:
    """Проверить данные по схеме components/schemas/<name>."""
    validate(data, f"#/components/schemas/{name}")


def operation(path: str, method: str = "get") -> dict:
    """Операция контракта по шаблону пути (/records/{ref}) и методу."""
    item = spec()["paths"].get(path)
    assert item is not None, f"в контракте нет пути {path}"
    assert method in item, f"в контракте нет {method.upper()} {path}"
    return item[method]


def response_ref(path: str, method: str, status: int, media: str) -> str | None:
    """Место схемы ответа операции на статус (или default) и тип тела; None — у ответа нет тела этого типа."""
    responses = operation(path, method)["responses"]
    key = next((k for k in (str(status), f"{str(status)[0]}XX", "default") if k in responses), None)
    assert key is not None, f"{method.upper()} {path}: в контракте нет ответа {status}"
    where = pointer("paths", path, method, "responses", key)
    while "$ref" in _at(where):                      # общий ответ: components/responses/Problem
        where = _at(where)["$ref"]
    if media not in (_at(where).get("content") or {}):
        return None
    return where + "/" + pointer("content", media, "schema")[2:]


def check(response, path: str, method: str = "get"):
    """Сверить ответ службы (httpx) с контрактом: статус описан, тело JSON — по схеме. Вернуть тело (JSON или байты)."""
    media = response.headers.get("content-type", "").partition(";")[0].strip()
    ref = response_ref(path, method, response.status_code, media)
    if media not in JSON:
        return response.content
    assert ref is not None, f"{method.upper()} {path}: ответ {response.status_code} {media} в контракте не описан"
    body = response.json()
    validate(body, ref)
    return body
