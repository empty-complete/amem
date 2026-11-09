"""Пути части 4d HTTP v1 (подпроект 4, часть 4d; спецификация разд. 6a): ответы — по строгой схеме контракта.

starlette.testclient на настоящей базе (PostgreSQL 18 и 16), порт не слушается."""
import os
from pathlib import Path

import contract
from amem import db

V1 = "/api/v1"
PACKS = Path(__file__).with_name("packs")


def problem(response, status: int, code: str, path: str, method: str = "get") -> dict:
    """Ответ-ошибка по контракту: статус описан, тело — Problem с этим code."""
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body = contract.check(response, path, method)
    assert body["code"] == code
    return body


# --- GET /templates (задача 17) ---

def test_templates(serve, pg, monkeypatch):
    monkeypatch.setenv("AMEM_PACKS", os.pathsep.join([str(PACKS / "forms"), str(PACKS / "quantities")]))
    db.prepare(pg)
    client = serve()
    every = contract.check(client.get(f"{V1}/templates"), "/templates")
    assert {v["target"] for v in every} == {"atom", "entity"}
    atoms = contract.check(client.get(f"{V1}/templates", params={"target": "atom"}), "/templates")
    assert {v["target"] for v in atoms} == {"atom"} and "reading" in {v["code"] for v in atoms}
    reading = next(v for v in atoms if v["code"] == "reading")
    assert {f["type"] for f in reading["form"]} == {"object", "quantity", "period", "choice", "record", "tags"}
    entities = contract.check(client.get(f"{V1}/templates", params={"target": "entity"}), "/templates")
    assert entities and all(v["family"] == "object" for v in entities)
    assert len(every) == len(atoms) + len(entities)
    problem(client.get(f"{V1}/templates", params={"target": "link"}), 400, "bad_request", "/templates")
