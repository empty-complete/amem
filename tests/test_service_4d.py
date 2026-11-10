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


# --- PUT / DELETE /packs/mine/templates/{code} (задача 18) ---

MINE = "/packs/mine/templates/{code}"
DRAFT = {"label": {"ru": "Взвешивание", "en": "Weighing"}, "target": "atom", "family": "source",
         "form": [{"key": "mass", "path": "content.values[property=mass]", "label": {"ru": "Масса"},
                   "type": "quantity", "required": True, "property": "mass"}],
         "body": "wanted", "widgets": ["sources", "values_table"]}


def _person(client):
    response = client.get(f"{V1}/session", headers={"Sec-Fetch-Site": "same-origin"})
    assert response.json()["agent"].startswith("person:")
    return client


def test_my_kinds_by_the_person(serve, pg, monkeypatch):
    monkeypatch.setenv("AMEM_PACKS", str(PACKS / "quantities"))
    db.prepare(pg)
    client = _person(serve())
    contract.check_request(DRAFT, MINE, "put")
    response = client.put(f"{V1}/packs/mine/templates/weighing", json=DRAFT)
    view = contract.check(response, MINE, "put")
    assert (view["code"], view["pack"], view["editable"], view["records"]) == ("weighing", "mine", True, 0)
    listed = contract.check(client.get(f"{V1}/templates", params={"target": "atom"}), "/templates")
    assert next(v for v in listed if v["code"] == "weighing")["editable"]
    problem(client.put(f"{V1}/packs/mine/templates/fact", json=DRAFT), 409, "template_exists", MINE, "put")
    bad = {**DRAFT, "form": [{**DRAFT["form"][0], "path": "content.values[property=nope]"}]}
    body = problem(client.put(f"{V1}/packs/mine/templates/weighing", json=bad), 422, "template_invalid", MINE, "put")
    assert body["issues"][0]["path"] == "form[0].path"
    problem(client.put(f"{V1}/packs/mine/templates/weighing", json=[1]), 400, "bad_request", MINE, "put")
    deleted = client.delete(f"{V1}/packs/mine/templates/weighing")
    assert deleted.status_code == 204
    contract.check(deleted, MINE, "delete")
    problem(client.delete(f"{V1}/packs/mine/templates/weighing"), 404, "not_found", MINE, "delete")


def test_my_kind_in_use_cannot_be_deleted(serve, pg, monkeypatch):
    monkeypatch.setenv("AMEM_PACKS", str(PACKS / "quantities"))
    db.prepare(pg)
    client = _person(serve())
    contract.check(client.put(f"{V1}/packs/mine/templates/weighing", json=DRAFT), MINE, "put")
    atom = {"kind": "weighing", "label": {"ru": "Кронштейн весит 2 кг"}, "summary_plain": {"ru": "Два килограмма."},
            "basis": "author", "content": {"values": [{"property": "mass", "amount": 2, "unit": "kg"}]}}
    submitted = client.post(f"{V1}/submit", json={"proposals": [{"target": "atom", "payload": atom}]})
    assert submitted.status_code == 200, submitted.text
    problem(client.delete(f"{V1}/packs/mine/templates/weighing"), 409, "template_in_use", MINE, "delete")


def test_my_kinds_are_not_for_the_model_or_a_read_only_token(serve, pg, monkeypatch, tmp_path):
    from test_service_core import tokens_file

    monkeypatch.setenv("AMEM_PACKS", str(PACKS / "quantities"))
    db.prepare(pg)
    model = serve()
    problem(model.put(f"{V1}/packs/mine/templates/weighing", json=DRAFT), 403, "forbidden", MINE, "put")
    problem(model.delete(f"{V1}/packs/mine/templates/weighing"), 403, "forbidden", MINE, "delete")
    path = tokens_file(tmp_path, ("t-read", "person:anna", False))
    reader = serve({"AMEM_TOKENS": path})
    reader.headers["Authorization"] = "Bearer t-read"
    problem(reader.put(f"{V1}/packs/mine/templates/weighing", json=DRAFT), 403, "read_only", MINE, "put")
    problem(reader.delete(f"{V1}/packs/mine/templates/weighing"), 403, "read_only", MINE, "delete")
    assert pg.execute("SELECT count(*) FROM concept WHERE origin = 'mine'").fetchone()[0] == 0


# --- блоки ui видов ядра ---

def test_core_parameter_and_decision_forms(serve, pg):
    """Формы ядра — как их ждёт веб: у параметра значение величины и период, у решения «действует с»;
    правила без required — строгость проверки не меняется."""
    db.prepare(pg)
    atoms = contract.check(serve().get(f"{V1}/templates", params={"target": "atom"}), "/templates")
    by = {v["code"]: v for v in atoms}
    parameter = {f["key"]: f for f in by["parameter"]["form"]}
    assert list(parameter) == ["about", "value", "valid", "tags"]
    assert (parameter["value"]["path"], parameter["value"]["type"]) == ("content.values", "quantity")
    assert (parameter["valid"]["path"], parameter["valid"]["type"]) == ("valid_from", "period")
    assert not any(f["required"] for f in parameter.values())
    assert "values_table" in by["parameter"]["widgets"] and by["parameter"]["pack"] == "core"
    decision = {f["key"]: f for f in by["decision"]["form"]}
    assert list(decision) == ["about", "valid_from", "tags"]
    assert (decision["valid_from"]["type"], decision["valid_from"]["required"]) == ("date", False)
    assert by["decision"]["widgets"] == ["sources", "links", "around", "similar"]
