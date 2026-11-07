"""Подборки HTTP v1 (подпроект 4, часть 4a, задача 8): экспорт и антология, скачивание и отчёт, загрузка с проверкой
(inspect), пробный и настоящий импорт; владелец подборки, срок хранения, пределы загрузки. И журнал запросов
(amem/journal.py): строка на явный поиск через HTTP. Каждый ответ сверяется со схемой контракта
docs/api/http-v1.openapi.yaml; starlette.testclient на настоящей базе (PostgreSQL 18 и 16), порт не слушается."""
import io
import json
import time
import uuid
import zipfile
from pathlib import Path

import pytest

import contract
from amem import api, check, db, journal, review
from amem.check import Proposal
from amem.service import app as service_app
from amem.service import http_v1
from check_support import atom
from test_service_core import tokens_file

PERSON = "person:ann"
MODEL = "model:local"
V1 = "/api/v1"
ORIGIN = "http://127.0.0.1:8767"
CSP_REPORT = "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:"


def problem(response, status: int, code: str, path: str, method: str = "get") -> dict:
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body = contract.check(response, path, method)
    assert body["code"] == code, body
    return body


@pytest.fixture
def kb(pg, monkeypatch, store, docs):
    """База с двумя заметками человека (verified — для антологии) и черновиком модели."""
    monkeypatch.setenv("AMEM_BACKEND", "none")
    monkeypatch.setattr(review, "AUDIT_RATE", 0.0)
    db.prepare(pg)
    made = check.submit(pg, store, docs, [
        Proposal("atom", atom("@a", kind="note", basis="author", sources=None, body={"ru": "Своё о кронштейне."})),
        Proposal("atom", atom("@b", kind="note", basis="author", sources=None, body={"ru": "Своё об анкере."},
                              tags=["зима"])),
    ], agent=PERSON)
    assert made.state == "approved", made.report
    return pg


@pytest.fixture
def start(serve, kb, docs):
    def run(env=None, *, person=False, **kw):
        client = serve({"AMEM_DOCS": str(docs), **(env or {})}, **kw)
        if person:
            response = client.get(f"{V1}/session", headers={"Sec-Fetch-Site": "same-origin"})
            assert response.json()["agent"] == PERSON
        return client
    return run


def state_dir(tmp_path) -> Path:
    return tmp_path / "home" / ".local" / "state" / "amem"         # AMEM_STATE по умолчанию при HOME фикстуры serve


def export(client, body=None, status=200):
    response = client.post(f"{V1}/bundles/export", json={"selection": {}} if body is None else body)
    assert response.status_code == status, response.text
    return contract.check(response, "/bundles/export", "post")


def upload(client, data: bytes, name="bundle.zip", origin=ORIGIN):
    headers = {"Origin": origin} if origin else {}
    return client.post(f"{V1}/bundles/inspect", files={"file": (name, data, "application/zip")}, headers=headers)


def downloaded(client, made) -> bytes:
    response = client.get(made["download"])
    assert response.status_code == 200, response.text
    contract.check(response, "/bundles/{id}/download")
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["x-content-type-options"] == "nosniff"
    return response.content


# --- экспорт, скачивание, отчёт ---

def test_export_and_download(start, kb, tmp_path):
    client = start(person=True)
    contract.check_request({"selection": {}, "with_files": False}, "/bundles/export", "post")
    made = export(client)
    assert uuid.UUID(made["id"]).version == 7
    assert made["download"] == f"{V1}/bundles/{made['id']}/download" and made["report"] is None
    summary = made["summary"]
    assert summary["counts"]["atoms"] == 2 and summary["with_files"] is False and summary["with_packs"] is False
    assert "core" in summary["packs"] and summary["anthology"] is False
    data = downloaded(client, made)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        manifest = json.loads(z.read("manifest.json"))
    assert manifest["agent"] == PERSON and manifest["counts"]["atoms"] == 2
    disposition = client.get(made["download"]).headers["content-disposition"]
    assert disposition == f'attachment; filename="amem-{made["id"]}.zip"'
    assert (state_dir(tmp_path) / "bundles" / made["id"] / "bundle.zip").is_file()
    # у обычной подборки отчёта нет
    problem(client.get(f"{V1}/bundles/{made['id']}/report"), 404, "not_found", "/bundles/{id}/report")


def test_export_selection_and_packs(start, kb):
    client = start(person=True)
    made = export(client, {"selection": {"tags": ["зима"], "statuses": []}, "with_packs": True})
    assert made["summary"]["counts"]["atoms"] == 1 and made["summary"]["with_packs"] is True
    with zipfile.ZipFile(io.BytesIO(downloaded(client, made))) as z:
        assert any(name.startswith("packs/core/") for name in z.namelist())


def test_anthology_report_inline_in_sandbox(start, kb):
    client = start(person=True)
    title = "Датчики «зима»/2026"
    made = export(client, {"selection": {}, "anthology": True, "title": title})
    assert made["report"] == f"{V1}/bundles/{made['id']}/report" and made["summary"]["anthology"] is True
    response = client.get(made["report"])
    assert response.status_code == 200
    contract.check(response, "/bundles/{id}/report")
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert response.headers["content-disposition"] == "inline"
    assert response.headers["content-security-policy"] == CSP_REPORT
    assert "allow-scripts" not in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert title in response.text and "кронштейн" in response.text.lower()
    # имя zip — заголовок без «/» и кавычек, не ASCII — filename* (RFC 5987), как у файлов объектов
    disposition = client.get(made["download"]).headers["content-disposition"]
    assert disposition.startswith("attachment; filename*=utf-8''") and "/" not in disposition.split("''", 1)[1]
    assert "%C2%AB" not in disposition                     # «» заменены: в имени файла только буквы, цифры, -_.()


def test_export_errors(start, kb, pg):
    client = start(person=True)
    path = "/bundles/export"
    problem(client.post(f"{V1}{path}", json={}), 400, "bad_request", path, "post")
    problem(client.post(f"{V1}{path}", json={"selection": []}), 400, "bad_request", path, "post")
    body = problem(client.post(f"{V1}{path}", json={"selection": {"tag": ["зима"]}}), 400, "bad_request", path,
                   "post")
    assert "tag" in body["detail"]
    problem(client.post(f"{V1}{path}", json={"selection": {"statuses": ["нет"]}}), 400, "bad_request", path, "post")
    problem(client.post(f"{V1}{path}", json={"selection": {"project": "atm:x"}}), 400, "bad_request", path, "post")
    problem(client.post(f"{V1}{path}", json={"selection": {"since": "вчера"}}), 400, "bad_request", path, "post")
    problem(client.post(f"{V1}{path}", json={"selection": {}, "with_files": "да"}), 400, "bad_request", path, "post")
    problem(client.post(f"{V1}{path}", json={"selection": {}, "anthology": True, "with_packs": True}), 400,
            "bad_request", path, "post")
    problem(client.post(f"{V1}{path}", json={"selection": {}, "anthology": True, "title": "я" * 201}), 400,
            "bad_request", path, "post")
    # антология без проверенного — BundleError → 422; папки подборки после отказа нет
    body = problem(client.post(f"{V1}{path}", json={"selection": {"tags": ["нет такого"]}, "anthology": True}),
                   422, "bundle_invalid", path, "post")
    assert "антология пуста" in body["detail"]
    # ссылка на запись, которой нет, — тоже отказ библиотеки
    problem(client.post(f"{V1}{path}", json={"selection": {"refs": [f"atm:{uuid.uuid4()}"]}}), 422,
            "bundle_invalid", path, "post")


def test_export_failure_leaves_nothing(start, kb, tmp_path):
    client = start(person=True)
    client.post(f"{V1}/bundles/export", json={"selection": {"tags": ["нет"]}, "anthology": True})
    root = state_dir(tmp_path) / "bundles"
    assert not root.exists() or list(root.iterdir()) == []


def test_foreign_and_missing_bundle_is_404(start, kb, tmp_path):
    person = start(person=True)
    made = export(person)
    model = start()                                         # другой клиент той же службы — без cookie, модель
    assert model.get(f"{V1}/session").json()["agent"] != PERSON
    problem(model.get(made["download"]), 404, "not_found", "/bundles/{id}/download")
    anthology = export(person, {"selection": {}, "anthology": True})
    problem(model.get(anthology["report"]), 404, "not_found", "/bundles/{id}/report")
    for bid in (str(uuid.uuid4()), "не-uuid", "%2e%2e"):
        problem(person.get(f"{V1}/bundles/{bid}/download"), 404, "not_found", "/bundles/{id}/download")
    # папка без meta.json (недописанная) не видна
    (state_dir(tmp_path) / "bundles" / made["id"] / "meta.json").unlink()
    problem(person.get(made["download"]), 404, "not_found", "/bundles/{id}/download")


def test_bundle_belongs_to_token_not_agent(start, kb, tmp_path):
    """В общей службе подборка — токена: второй токен того же агента её не видит."""
    path = tokens_file(tmp_path, ("t-one", "person:anna", True), ("t-two", "person:anna", True))
    client = start({"AMEM_TOKENS": path})
    client.headers["Authorization"] = "Bearer t-one"
    made = export(client)
    downloaded(client, made)
    client.headers["Authorization"] = "Bearer t-two"
    problem(client.get(made["download"]), 404, "not_found", "/bundles/{id}/download")


# --- срок хранения ---

def shift_clock(monkeypatch, seconds: float) -> None:
    real = time.time
    monkeypatch.setattr(api, "_now", lambda: real() + seconds)


def test_expired_bundle_is_removed_on_access(start, kb, tmp_path, monkeypatch):
    client = start(person=True)
    made = export(client)
    folder = state_dir(tmp_path) / "bundles" / made["id"]
    shift_clock(monkeypatch, -3600)                         # часы ушли назад — не просрочка
    downloaded(client, made)
    shift_clock(monkeypatch, api.BUNDLE_TTL - 60)
    downloaded(client, made)
    shift_clock(monkeypatch, api.BUNDLE_TTL + 60)
    problem(client.get(made["download"]), 404, "not_found", "/bundles/{id}/download")
    assert not folder.exists()


def test_sweep_removes_old_bundles_and_uploads(start, kb, tmp_path, monkeypatch):
    client = start(person=True)
    old = export(client)
    data = downloaded(client, old)
    uploaded = contract.check(upload(client, data), "/bundles/inspect", "post")
    root = state_dir(tmp_path)
    stray = root / "uploads" / f".{uuid.uuid4()}.part"       # недокачанное после сбоя
    stray.write_bytes(b"x")
    foreign = root / "bundles" / "чужое.txt"                 # чужие имена в папке состояния не трогаются
    foreign.write_text("x", encoding="utf-8")
    shift_clock(monkeypatch, api.BUNDLE_TTL + 60)
    fresh = export(client)                                   # создана уже по сдвинутым часам
    assert api.bundle_sweep(root) == 3
    assert not (root / "bundles" / old["id"]).exists() and not (root / "uploads" / uploaded["upload_id"]).exists()
    assert not stray.exists() and foreign.exists()
    downloaded(client, fresh)


def test_service_sweeps_at_start(serve, kb, tmp_path, monkeypatch):
    root = state_dir(tmp_path)
    old = root / "bundles" / str(uuid.uuid4())
    old.mkdir(parents=True)
    (old / "meta.json").write_text(json.dumps({"owner": f"agent:{PERSON}", "created_at": time.time() - 2 * 86400}),
                                   encoding="utf-8")
    young = root / "bundles" / str(uuid.uuid4())
    young.mkdir()
    (young / "meta.json").write_text(json.dumps({"owner": f"agent:{PERSON}", "created_at": time.time()}),
                                     encoding="utf-8")
    serve()
    assert not old.exists() and young.exists()
    assert service_app.SWEEP_EVERY == 3600


# --- загрузка и проверка ---

def test_inspect_upload(start, kb, tmp_path):
    client = start(person=True)
    data = downloaded(client, export(client))
    response = upload(client, data)
    assert response.status_code == 200, response.text
    body = contract.check(response, "/bundles/inspect", "post")
    assert uuid.UUID(body["upload_id"]).version == 7
    report = body["report"]
    assert report["ok"] is True and report["damaged"] == [] and report["format"] == "amem.bundle/1"
    assert report["counts"]["atoms"] == 2
    folder = state_dir(tmp_path) / "uploads" / body["upload_id"]
    assert (folder / "bundle.zip").read_bytes() == data
    assert [p.name for p in (state_dir(tmp_path) / "uploads").iterdir()] == [body["upload_id"]]


def test_inspect_needs_origin_and_multipart(start, kb):
    client = start(person=True)
    data = downloaded(client, export(client))
    problem(upload(client, data, origin=None), 403, "bad_origin", "/bundles/inspect", "post")
    problem(upload(client, data, origin="http://evil.example"), 403, "bad_origin", "/bundles/inspect", "post")
    problem(client.post(f"{V1}/bundles/inspect", json={"file": "x"}, headers={"Origin": ORIGIN}), 415,
            "unsupported_media_type", "/bundles/inspect", "post")
    response = client.post(f"{V1}/bundles/inspect", data={"note": "без файла"}, files={"other": ("x", b"x")},
                           headers={"Origin": ORIGIN})
    problem(response, 400, "bad_request", "/bundles/inspect", "post")


def test_inspect_rejects_non_bundle(start, kb, tmp_path):
    client = start(person=True)
    body = problem(upload(client, b"not a zip at all"), 422, "bundle_invalid", "/bundles/inspect", "post")
    assert "zip" in body["detail"]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("readme.txt", "не подборка")
    problem(upload(client, buffer.getvalue()), 422, "bundle_invalid", "/bundles/inspect", "post")
    assert list((state_dir(tmp_path) / "uploads").iterdir()) == []          # отказ — загрузка удалена


def test_inspect_too_large_is_413_and_removed(start, kb, tmp_path, monkeypatch):
    client = start(person=True)
    monkeypatch.setattr(http_v1, "UPLOAD_LIMIT", 4096)
    body = problem(upload(client, b"z" * 20000), 413, "too_large", "/bundles/inspect", "post")
    assert "МиБ" in body["detail"]
    assert list((state_dir(tmp_path) / "uploads").iterdir()) == []          # недокачанное удалено
    # быстрый отказ по Content-Length — тело не читается
    monkeypatch.setattr(http_v1, "FORM_LIMIT", 0)
    response = client.post(f"{V1}/bundles/inspect", content=b"-" * 5000,
                           headers={"Origin": ORIGIN, "Content-Type": "multipart/form-data; boundary=xyz"})
    problem(response, 413, "too_large", "/bundles/inspect", "post")


def test_inspect_rejects_broken_multipart(start, kb, tmp_path):
    client = start(person=True)
    headers = {"Origin": ORIGIN, "Content-Type": "multipart/form-data"}
    problem(client.post(f"{V1}/bundles/inspect", content=b"x", headers=headers), 400, "bad_request",
            "/bundles/inspect", "post")
    headers["Content-Type"] = "multipart/form-data; boundary=xyz"
    cut = (b'--xyz\r\nContent-Disposition: form-data; name="file"; filename="b.zip"\r\n'
           b'Content-Type: application/zip\r\n\r\nPK\x03\x04')                    # тело оборвано посреди файла
    problem(client.post(f"{V1}/bundles/inspect", content=cut, headers=headers), 400, "bad_request",
            "/bundles/inspect", "post")
    assert list((state_dir(tmp_path) / "uploads").iterdir()) == []


# --- импорт ---

def test_import_dry_run_by_default(start, kb):
    client = start(person=True)
    data = downloaded(client, export(client))
    uploaded = contract.check(upload(client, data), "/bundles/inspect", "post")
    contract.check_request({"upload_id": uploaded["upload_id"]}, "/bundles/import", "post")
    atoms = kb.execute("SELECT count(*) FROM atom_revision").fetchone()[0]
    response = client.post(f"{V1}/bundles/import", json={"upload_id": uploaded["upload_id"]})
    assert response.status_code == 200, response.text
    body = contract.check(response, "/bundles/import", "post")
    assert body["changeset_id"] is None and body["counts"]["unchanged"] == 2 and "report" in body
    assert kb.execute("SELECT count(*) FROM atom_revision").fetchone()[0] == atoms
    # настоящий импорт той же базы — человек; всё совпало, пакет изменений не нужен
    body = contract.check(client.post(f"{V1}/bundles/import", json={"upload_id": uploaded["upload_id"],
                                                                    "dry_run": False, "trust": "review"}),
                          "/bundles/import", "post")
    assert body["complete"] is True and body["counts"]["unchanged"] == 2


def test_import_writes_only_for_person(start, kb):
    """Модель видит план импорта (dry_run), но влить подборку вправе только человек."""
    person = start(person=True)
    data = downloaded(person, export(person))
    model = start()
    uploaded = contract.check(upload(model, data), "/bundles/inspect", "post")
    plan = contract.check(model.post(f"{V1}/bundles/import", json={"upload_id": uploaded["upload_id"]}),
                          "/bundles/import", "post")
    assert plan["changeset_id"] is None
    body = problem(model.post(f"{V1}/bundles/import", json={"upload_id": uploaded["upload_id"], "dry_run": False}),
                   403, "forbidden", "/bundles/import", "post")
    assert "человек" in body["detail"]
    # загрузка модели — её: человек её не видит
    problem(person.post(f"{V1}/bundles/import", json={"upload_id": uploaded["upload_id"]}), 404, "not_found",
            "/bundles/import", "post")


def test_import_errors(start, kb):
    client = start(person=True)
    path = "/bundles/import"
    problem(client.post(f"{V1}{path}", json={"upload_id": str(uuid.uuid4())}), 404, "not_found", path, "post")
    problem(client.post(f"{V1}{path}", json={}), 404, "not_found", path, "post")
    uploaded = contract.check(upload(client, downloaded(client, export(client))), "/bundles/inspect", "post")
    problem(client.post(f"{V1}{path}", json={"upload_id": uploaded["upload_id"], "trust": "всем"}), 400,
            "bad_request", path, "post")
    problem(client.post(f"{V1}{path}", json={"upload_id": uploaded["upload_id"], "dry_run": "нет"}), 400,
            "bad_request", path, "post")


def test_read_only_token_cannot_export(start, kb, tmp_path):
    path = tokens_file(tmp_path, ("t-read", "person:anna", False))
    client = start({"AMEM_TOKENS": path})
    client.headers["Authorization"] = "Bearer t-read"
    problem(client.post(f"{V1}/bundles/export", json={"selection": {}}), 403, "read_only", "/bundles/export", "post")


# --- журнал запросов ---

def log_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_query_log_line_per_explicit_search(start, kb, tmp_path):
    client = start(person=True)
    path = state_dir(tmp_path) / "queries.jsonl"             # AMEM_QUERY_LOG по умолчанию — AMEM_STATE/queries.jsonl
    found = contract.check(client.get(f"{V1}/search", params={"q": "кронштейн <private>пароль щита</private>"}),
                           "/search")
    lines = log_lines(path)
    assert len(lines) == 1
    line = lines[0]
    assert set(line) == {"at", "recipe", "query", "base_id", "agent", "count", "duration_ms", "retrieval_id"}
    assert line["recipe"] == "exact_fact" and line["agent"] == PERSON and line["count"] == len(found["items"])
    assert line["query"] == "кронштейн " and "пароль" not in path.read_text(encoding="utf-8")
    assert line["retrieval_id"] == found["retrieval_id"] and line["count"] >= 1
    assert line["base_id"] == kb.execute("SELECT value FROM meta WHERE key = 'base_id'").fetchone()[0]
    assert "Своё" not in path.read_text(encoding="utf-8")              # находок в журнале нет
    assert path.stat().st_mode & 0o777 == 0o600
    ref = found["items"][0]["ref"]
    contract.check(client.get(f"{V1}/similar", params={"ref": ref}), "/similar")
    contract.check(client.get(f"{V1}/similar", params={"q": "анкер"}), "/similar")
    lines = log_lines(path)
    assert [(x["recipe"], x["query"]) for x in lines[1:]] == [("similar", ref), ("similar", "анкер")]
    # ошибка запроса — не поиск: строки нет
    client.get(f"{V1}/search")
    assert len(log_lines(path)) == 3


def test_query_log_off_and_custom_path(start, kb, tmp_path):
    off = start({"AMEM_QUERY_LOG": "off"})
    contract.check(off.get(f"{V1}/search", params={"q": "кронштейн"}), "/search")
    assert not (state_dir(tmp_path) / "queries.jsonl").exists()
    custom = tmp_path / "logs" / "q.jsonl"
    client = start({"AMEM_QUERY_LOG": str(custom)})
    contract.check(client.get(f"{V1}/search", params={"q": "кронштейн"}), "/search")
    assert [x["agent"] for x in log_lines(custom)] == [MODEL]


def test_query_log_failure_does_not_break_search(start, kb, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    client = start({"AMEM_QUERY_LOG": str(blocker / "q.jsonl")})        # родитель — файл: записать нельзя
    response = client.get(f"{V1}/search", params={"q": "кронштейн"})
    assert response.status_code == 200
    contract.check(response, "/search")


def test_library_search_does_not_log(kb, tmp_path):
    """Журнал пишут только пути явного поиска службы: поиск мимо HTTP (хук, CLI) строк не добавляет."""
    api.search(kb, "кронштейн", agent=MODEL)
    assert not (state_dir(tmp_path) / "queries.jsonl").exists()
    assert journal.record(None, recipe="exact_fact", query="x", agent=MODEL, base_id=None, count=0, duration_ms=1,
                          retrieval_id=None) is False


# --- словарь величин: единица по умолчанию ---

def test_vocab_property_unit(serve, pg, monkeypatch):
    packs_dir = Path(__file__).with_name("packs")
    monkeypatch.setenv("AMEM_PACKS", str(packs_dir / "quantities"))
    db.prepare(pg)
    pg.execute("INSERT INTO concept (scheme, code, data, origin, updated_at) VALUES ('property', 'agent_made', "
               "%s, 'agent', now())", (json.dumps({"scheme": "property", "code": "agent_made",
                                                   "label": {"ru": "своя величина"}}),))
    client = serve()
    entries = {e["code"]: e for e in contract.check(client.get(f"{V1}/vocab/property"), "/vocab/{scheme}")}
    assert entries["mass"]["unit"] == "kg" and entries["temperature"]["unit"] == "Cel"
    assert entries["agent_made"]["unit"] is None
    kinds = contract.check(client.get(f"{V1}/vocab/kind"), "/vocab/{scheme}")
    assert all("unit" not in k for k in kinds)
