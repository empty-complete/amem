"""Контракт HTTP v1 для тестов службы: схемы ответов и тел запросов из docs/api/http-v1.openapi.yaml и проверка
по ним.

OpenAPI 3.1 — это JSON Schema 2020-12, поэтому ответ проверяет jsonschema: документ контракта целиком — один ресурс
реестра (referencing), схема ответа берётся ссылкой на своё место в документе (JSON Pointer), и ссылки
«#/components/…» внутри неё разрешаются по тому же документу. Форматы uuid и date-time проверяются.

Сверка строгая: у каждой схемы со списком properties лишние поля запрещены (additionalProperties: false), если
контракт сам не сказал иначе (Problem — расширения RFC 9457). Открытые объекты без properties (payload, details,
summary, channels…) остаются открытыми. Так поле, которого нет в контракте, не уходит вебу незамеченным.
"""
from __future__ import annotations

import copy
from functools import cache
from pathlib import Path
from urllib.parse import quote

import jsonschema
import yaml
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "docs" / "api" / "http-v1.openapi.yaml"
URI = "urn:amemo:http-v1"
JSON = ("application/json", "application/problem+json")


@cache
def spec() -> dict:
    return yaml.safe_load(PATH.read_text(encoding="utf-8"))


def _strict(node):
    """Копия схемы, где у объектов со списком properties лишние поля запрещены (если контракт не задал иначе)."""
    if isinstance(node, dict):
        node = {key: _strict(value) for key, value in node.items()}
        if isinstance(node.get("properties"), dict) and "additionalProperties" not in node:
            node["additionalProperties"] = False
        return node
    if isinstance(node, list):
        return [_strict(value) for value in node]
    return node


@cache
def strict_spec() -> dict:
    return _strict(copy.deepcopy(spec()))


@cache
def _registry() -> Registry:
    return Registry().with_resource(URI, Resource.from_contents(strict_spec(), default_specification=DRAFT202012))


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


def request_ref(path: str, method: str, media: str = "application/json") -> str:
    """Место схемы тела запроса операции."""
    body = operation(path, method).get("requestBody")
    assert body is not None and media in body["content"], f"{method.upper()} {path}: тела {media} в контракте нет"
    return pointer("paths", path, method, "requestBody", "content", media, "schema")


def example(path: str, method: str, media: str = "application/json"):
    """Пример тела запроса из контракта."""
    content = operation(path, method)["requestBody"]["content"][media]
    assert "example" in content, f"{method.upper()} {path}: у тела нет примера"
    return content["example"]


def check_request(body, path: str, method: str) -> None:
    """Тело запроса — по схеме контракта, так же строго, как ответы."""
    validate(body, request_ref(path, method))


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
