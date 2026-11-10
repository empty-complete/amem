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


def test_my_kind_round_trip_keeps_versions_and_required(serve, pg, monkeypatch):
    """Вид с двумя величинами, обязательна одна: GET /templates → PUT того же — версии те же, обязательность та же."""
    monkeypatch.setenv("AMEM_PACKS", str(PACKS / "quantities"))
    db.prepare(pg)
    client = _person(serve())
    draft = {**DRAFT, "form": [
        DRAFT["form"][0],
        {"key": "length", "path": "content.values[property=length]", "label": {"ru": "Длина"}, "type": "quantity",
         "required": False, "property": "length"}]}
    contract.check(client.put(f"{V1}/packs/mine/templates/weighing", json=draft), MINE, "put")

    def state():
        [view] = [v for v in contract.check(client.get(f"{V1}/templates", params={"target": "atom"}), "/templates")
                  if v["code"] == "weighing"]
        versions = (pg.execute("SELECT version FROM template_active WHERE code = 'weighing'").fetchone(),
                    pg.execute("SELECT count(*) FROM pack WHERE name = 'mine'").fetchone())
        return view, versions

    view, versions = state()
    required = {f["property"]: f["required"] for f in view["form"] if f["type"] == "quantity"}
    assert required == {"mass": True, "length": False}
    echo = {k: view[k] for k in ("label", "target", "family", "description", "form", "body", "widgets")}
    contract.check_request(echo, MINE, "put")
    contract.check(client.put(f"{V1}/packs/mine/templates/weighing", json=echo), MINE, "put")
    again, after = state()
    assert after == versions and again["form"] == view["form"]


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


# --- GET / POST /objects (задача 20) ---

ORIGIN = "http://127.0.0.1:8767"


def _upload(client, data: bytes, name="Протокол.md", path=None, origin=ORIGIN):
    return client.post(f"{V1}/objects", files={"file": (name, data, "text/markdown")},
                       data={"path": path} if path is not None else None,
                       headers={"Origin": origin} if origin else {})


def _parts(docs: Path) -> list[str]:
    return [p.name for p in docs.iterdir() if p.name.startswith(".amem-upload")]


def test_upload_new_same_and_other_file(serve, pg, tmp_path):
    docs = tmp_path / "d"
    docs.mkdir()
    client = _person(serve({"AMEM_DOCS": str(docs)}))
    response = _upload(client, b"# Protocol\n")
    assert response.status_code == 201, response.text
    view = contract.check(response, "/objects", "post")
    assert (docs / "Загрузки" / "Протокол.md").read_bytes() == b"# Protocol\n"
    assert view["logical_paths"] == ["Загрузки/Протокол.md"] and len(view["versions"]) == 1
    again = _upload(client, b"# Protocol\n")
    assert again.status_code == 200, again.text
    same = contract.check(again, "/objects", "post")
    assert same["id"] == view["id"] and len(same["versions"]) == 1                 # второй версии нет
    problem(_upload(client, b"# Other\n"), 409, "object_path_taken", "/objects", "post")
    assert (docs / "Загрузки" / "Протокол.md").read_bytes() == b"# Protocol\n"      # файл на диске не тронут
    placed = contract.check(_upload(client, b"# Report\n", name="x.md", path="Отчёты/2026/отчёт.md"), "/objects",
                            "post")
    assert (docs / "Отчёты" / "2026" / "отчёт.md").read_bytes() == b"# Report\n"
    assert placed["logical_paths"] == ["Отчёты/2026/отчёт.md"]
    problem(_upload(client, b"x", path="Отчёты"), 409, "object_path_taken", "/objects", "post")    # там папка
    model = serve({"AMEM_DOCS": str(docs)})                                       # модель тоже загружает
    assert _upload(model, b"model\n", name="m.md").status_code == 201
    assert _parts(docs) == []
    assert pg.execute("SELECT count(*) FROM object").fetchone()[0] == 3


def test_upload_of_known_content_at_a_new_path_is_200(serve, pg, tmp_path):
    """То же содержимое уже есть у объекта по другому пути: файл ложится по новому пути, но новой версии нет — 200."""
    docs = tmp_path / "d"
    docs.mkdir()
    client = _person(serve({"AMEM_DOCS": str(docs)}))
    first = contract.check(_upload(client, b"# Protocol\n"), "/objects", "post")
    again = _upload(client, b"# Protocol\n", path="Архив/копия.md")
    assert again.status_code == 200, again.text
    view = contract.check(again, "/objects", "post")
    assert view["id"] == first["id"] and len(view["versions"]) == 1
    assert (docs / "Архив" / "копия.md").read_bytes() == b"# Protocol\n" and _parts(docs) == []


def test_upload_part_is_removed_when_the_database_is_down(serve, pg, tmp_path, monkeypatch):
    """Сбой до object_upload (база недоступна) не оставляет .part в папке документов; старые .part убирает запуск."""
    import time

    import psycopg
    from amem.service import http_v1

    docs = tmp_path / "d"
    docs.mkdir()
    stale = docs / ".amem-upload-old.part"
    stale.write_bytes(b"x")
    old = time.time() - 2 * 3600
    os.utime(stale, (old, old))
    fresh = docs / ".amem-upload-now.part"
    fresh.write_bytes(b"y")
    client = _person(serve({"AMEM_DOCS": str(docs)}))
    assert not stale.exists() and fresh.exists()                    # брошенный — долой, свежий не тронут
    fresh.unlink()

    def down(request):
        raise psycopg.OperationalError("нет базы")
    monkeypatch.setattr(http_v1, "connection", down)
    problem(_upload(client, b"# Protocol\n"), 503, "db_unavailable", "/objects", "post")
    assert _parts(docs) == [] and not (docs / "Загрузки").exists()


def test_upload_bad_path_is_400(serve, pg, tmp_path):
    docs = tmp_path / "d"
    docs.mkdir()
    client = _person(serve({"AMEM_DOCS": str(docs)}))
    for path in ("../вне.md", "/abs.md", "a\x00b.md", "Загрузки/../../x.md"):
        problem(_upload(client, b"x", path=path), 400, "bad_request", "/objects", "post")
    assert _parts(docs) == [] and not (tmp_path / "вне.md").exists()
    assert pg.execute("SELECT count(*) FROM object").fetchone()[0] == 0


def test_upload_without_docs_is_503(serve, pg, tmp_path):
    problem(_upload(_person(serve()), b"x"), 503, "docs_unavailable", "/objects", "post")
    missing = serve({"AMEM_DOCS": str(tmp_path / "нет")})
    problem(_upload(missing, b"x"), 503, "docs_unavailable", "/objects", "post")


def test_upload_limits_origin_and_read_only(serve, pg, tmp_path, monkeypatch):
    from amem.service import http_v1
    from test_service_core import tokens_file

    docs = tmp_path / "d"
    docs.mkdir()
    client = _person(serve({"AMEM_DOCS": str(docs)}))
    monkeypatch.setattr(http_v1, "UPLOAD_LIMIT", 4096)
    problem(_upload(client, b"z" * 20000), 413, "too_large", "/objects", "post")
    assert _parts(docs) == [] and not (docs / "Загрузки").exists()                 # недокачанное удалено
    problem(_upload(client, b"x", origin=None), 403, "bad_origin", "/objects", "post")
    problem(client.post(f"{V1}/objects", json={"file": "x"}, headers={"Origin": ORIGIN}), 415,
            "unsupported_media_type", "/objects", "post")
    path = tokens_file(tmp_path, ("t-read", "person:anna", False))
    reader = serve({"AMEM_DOCS": str(docs), "AMEM_TOKENS": path})
    reader.headers["Authorization"] = "Bearer t-read"
    problem(_upload(reader, b"x"), 403, "read_only", "/objects", "post")
    assert pg.execute("SELECT count(*) FROM object").fetchone()[0] == 0


def test_list_objects(serve, pg, tmp_path):
    docs = tmp_path / "d"
    docs.mkdir()
    client = _person(serve({"AMEM_DOCS": str(docs)}))
    for name in ("Протокол.md", "Акт.md", "Схема.md"):
        assert _upload(client, name.encode(), name=name).status_code == 201
    page = contract.check(client.get(f"{V1}/objects", params={"limit": 2}), "/objects")
    assert [i["original_name"] for i in page["items"]] == ["Схема.md", "Акт.md"] and page["next_cursor"]
    rest = contract.check(client.get(f"{V1}/objects", params={"limit": 2, "cursor": page["next_cursor"]}), "/objects")
    assert [i["original_name"] for i in rest["items"]] == ["Протокол.md"] and rest["next_cursor"] is None
    found = contract.check(client.get(f"{V1}/objects", params={"q": "загрузки/акт"}), "/objects")
    assert [i["original_name"] for i in found["items"]] == ["Акт.md"]
    problem(client.get(f"{V1}/objects", params={"limit": 0}), 400, "bad_request", "/objects")
    problem(client.get(f"{V1}/objects", params={"cursor": "мусор"}), 400, "bad_request", "/objects")


# --- GET / POST /tasks (задача 21) ---

def _file(client, name="Протокол.md") -> dict:
    view = contract.check(_upload(client, name.encode(), name=name), "/objects", "post")
    return {"kind": "parse", "object": view["id"], "version": view["versions"][-1]["n"]}


def test_tasks_create_and_list(serve, pg, tmp_path):
    docs = tmp_path / "d"
    docs.mkdir()
    person = _person(serve({"AMEM_DOCS": str(docs)}))
    body = {**_file(person), "note": "разобрать протокол"}
    contract.check_request(body, "/tasks", "post")
    made = person.post(f"{V1}/tasks", json=body)
    assert made.status_code == 202, made.text
    task_id = contract.check(made, "/tasks", "post")["task_id"]
    again = person.post(f"{V1}/tasks", json=body)
    assert again.status_code == 202 and again.json()["task_id"] == task_id                # та же задача
    model = serve({"AMEM_DOCS": str(docs)})
    other = _file(model, "Акт.md")
    by_model = model.post(f"{V1}/tasks", json=other)                                    # модель тоже ставит
    assert by_model.status_code == 202, by_model.text
    every = contract.check(person.get(f"{V1}/tasks"), "/tasks")
    assert [t["id"] for t in every] == [task_id, by_model.json()["task_id"]]
    first = every[0]
    assert (first["state"], first["note"], first["created_by"], first["claimed_by"]) == \
        ("open", "разобрать протокол", "person:ann", None)
    assert every[1]["created_by"].startswith("model:")
    only = contract.check(person.get(f"{V1}/tasks", params={"object": other["object"]}), "/tasks")
    assert [t["object"] for t in only] == [other["object"]]
    assert contract.check(person.get(f"{V1}/tasks", params={"state": "done"}), "/tasks") == []
    problem(person.get(f"{V1}/tasks", params={"state": "busy"}), 400, "bad_request", "/tasks")
    problem(person.get(f"{V1}/tasks", params={"object": "мусор"}), 400, "bad_request", "/tasks")
    problem(person.post(f"{V1}/tasks", json={**body, "version": 9}), 404, "not_found", "/tasks", "post")
    problem(person.post(f"{V1}/tasks", json={"kind": "parse", "object": body["object"]}), 400, "bad_request",
            "/tasks", "post")
    problem(person.post(f"{V1}/tasks", json={**body, "kind": "summarize"}), 400, "bad_request", "/tasks", "post")


def test_tasks_read_only_token(serve, pg, tmp_path):
    from test_service_core import tokens_file

    docs = tmp_path / "d"
    docs.mkdir()
    body = _file(_person(serve({"AMEM_DOCS": str(docs)})))
    path = tokens_file(tmp_path, ("t-read", "person:anna", False))
    reader = serve({"AMEM_DOCS": str(docs), "AMEM_TOKENS": path})
    reader.headers["Authorization"] = "Bearer t-read"
    problem(reader.post(f"{V1}/tasks", json=body), 403, "read_only", "/tasks", "post")
    assert contract.check(reader.get(f"{V1}/tasks"), "/tasks") == []
    assert pg.execute("SELECT count(*) FROM task").fetchone()[0] == 0
