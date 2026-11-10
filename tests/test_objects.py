"""Объекты источников на PostgreSQL 18 и 16: файл копируется в хранилище один раз, изменённый даёт следующую версию,
старый источник открывает свою копию; страницы сайтов и переписка; текст по digest; отметки статуса."""
import copy
import json
import os
import re
import shutil
import threading
import unicodedata
import uuid
from datetime import date, datetime, timedelta, timezone

import psycopg

import pytest

from amemo import db, lookup, model_v1, objects, sources
from amemo.ocfl_store import ObjectStore, StoreError
from amemo.objects import ObjectError
from amemo.records import Item, commit
from ocfl_check import validate
from samples import make_docs
from v1_support import same_database

AGENT = "model:claude"
PDF = "НД/СП 99.pdf"


@pytest.fixture
def kb(pg):
    db.prepare(pg)
    return pg


@pytest.fixture
def docs(tmp_path):
    return make_docs(tmp_path / "docs")


@pytest.fixture
def store(tmp_path):
    return ObjectStore(tmp_path / "objects")


def files_in(store) -> list:
    return sorted(p for p in store.root.rglob("*") if p.is_file() and "/content/" in p.as_posix())


def test_file_is_copied_once(kb, docs, store):
    first = objects.ingest(kb, store, docs, PDF, agent=AGENT)
    again = objects.ingest(kb, store, docs, PDF, agent=AGENT)
    assert first.created and not again.created
    assert (again.object_id, again.n, again.digest) == (first.object_id, 1, first.digest)
    assert len(files_in(store)) == 1
    assert store.content(first.object_id, 1).read_bytes() == (docs / PDF).read_bytes()
    record = lookup.get_object(kb, first.object_id)
    model_v1.ObjectRecord.model_validate_json(json.dumps(record), strict=True)          # выдача — в формате схемы
    assert record["logical_paths"] == [PDF] and record["kind"] == "file" and record["media_type"] == "application/pdf"
    assert record["versions"] == [{"n": 1, "digest": first.digest, "size": (docs / PDF).stat().st_size,
                                   "recorded_at": record["versions"][0]["recorded_at"]}]
    ok, log = validate(store.root)
    assert ok, log


def test_same_content_at_another_path_is_the_same_version(kb, docs, store):
    first = objects.ingest(kb, store, docs, PDF, agent=AGENT)
    (docs / "Архив").mkdir()
    shutil.copy(docs / PDF, docs / "Архив" / "СП 99 копия.pdf")
    copy = objects.ingest(kb, store, docs, "Архив/СП 99 копия.pdf", agent=AGENT)
    assert (copy.object_id, copy.n, copy.created) == (first.object_id, 1, False)
    assert lookup.get_object(kb, first.object_id)["logical_paths"] == ["Архив/СП 99 копия.pdf", PDF]
    assert lookup.object_by_path(kb, "Архив/СП 99 копия.pdf") == first.ref
    assert len(files_in(store)) == 1


def test_changed_file_gets_next_version_and_old_copy_stays(kb, docs, store):
    old = (docs / PDF).read_bytes()
    first = objects.ingest(kb, store, docs, PDF, agent=AGENT)
    (docs / PDF).write_bytes(old + "\n% ред. 2".encode())
    second = objects.ingest(kb, store, docs, PDF, agent=AGENT)
    assert (second.object_id, second.n, second.created) == (first.object_id, 2, True)
    assert store.content(first.object_id, 1).read_bytes() == old
    assert [v["n"] for v in lookup.get_object(kb, first.object_id)["versions"]] == [1, 2]
    ok, log = validate(store.root)
    assert ok, log


def test_file_returned_to_old_content_reuses_old_version(kb, docs, store):
    old = (docs / PDF).read_bytes()
    first = objects.ingest(kb, store, docs, PDF, agent=AGENT)
    (docs / PDF).write_bytes(old + b"%2")
    objects.ingest(kb, store, docs, PDF, agent=AGENT)
    (docs / PDF).write_bytes(old)
    back = objects.ingest(kb, store, docs, PDF, agent=AGENT)
    assert (back.n, back.created) == (1, False)
    assert store.head(first.object_id) == 2


@pytest.mark.parametrize("path, message", [
    ("НД/нет такого.pdf", "файла нет в папке документов"), ("../outside.pdf", "«..» в пути не допускается"),
    ("НД", "файла нет в папке документов")], ids=["нет файла", "наружу", "папка"])
def test_missing_or_outside_file_rejected(kb, docs, store, path, message):
    (docs.parent / "outside.pdf").write_bytes(b"%PDF")
    with pytest.raises(ObjectError, match=message):
        objects.ingest(kb, store, docs, path, agent=AGENT)
    assert kb.execute("SELECT count(*) FROM object").fetchone()[0] == 0


def test_failed_rows_leave_no_copy(kb, docs, store):
    """Сначала строки базы, потом копия: сбой записи строк не оставляет копии в хранилище."""
    kb.execute("CREATE FUNCTION fail_version() RETURNS trigger LANGUAGE plpgsql AS "
               "$$ BEGIN RAISE EXCEPTION 'сбой записи версии'; END $$")
    kb.execute("CREATE TRIGGER fail_version BEFORE INSERT ON object_version FOR EACH ROW EXECUTE FUNCTION fail_version()")
    with pytest.raises(psycopg.errors.RaiseException, match="сбой записи версии"):
        objects.ingest(kb, store, docs, PDF, agent=AGENT)
    assert files_in(store) == [] and kb.execute("SELECT count(*) FROM object").fetchone()[0] == 0


def test_failed_copy_leaves_no_rows(kb, docs, store, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("диск переполнен")

    monkeypatch.setattr(store, "add_version", broken)
    with pytest.raises(OSError):
        objects.ingest(kb, store, docs, PDF, agent=AGENT)
    assert kb.execute("SELECT count(*) FROM object").fetchone()[0] == 0
    monkeypatch.undo()
    assert objects.ingest(kb, store, docs, PDF, agent=AGENT).created


def test_missing_store_with_files_in_db_is_refused(kb, docs, store):
    """Хранилище пропало (пустая папка данных вместо тома), а база знает файлы: новый корень молча не создаётся —
    иначе копии новых файлов ушли бы в пустую папку, а старые файлы второй раз уже не скопировались бы."""
    objects.ingest(kb, store, docs, PDF, agent=AGENT)
    shutil.rmtree(store.root)
    with pytest.raises(StoreError, match="корня хранилища нет"):
        objects.ingest(kb, store, docs, "Заметки/узел.md", agent=AGENT)
    with pytest.raises(StoreError, match=r"sources\[0\]: .*: корня хранилища нет"):      # сбой сервера, не данных
        objects.resolve_sources(kb, store, docs, {"sources": [{"path": "Заметки/узел.md"}]}, agent=AGENT)
    assert kb.execute("SELECT count(*) FROM object").fetchone()[0] == 1 and not store.root.exists()


def test_first_file_after_web_page_creates_the_store(kb, docs, store):
    """Объекты без файлов не в счёт: страница сайта до первого файла не мешает создать корень хранилища."""
    objects.web(kb, "https://example.org/")
    objects.message(kb, "Письмо")
    assert objects.ingest(kb, store, docs, PDF, agent=AGENT).created and store.root.exists()


def test_concurrent_ingest_of_one_file_gives_one_object(kb, docs, store):
    results, errors = [], []

    def run():
        try:
            with same_database(kb, autocommit=True) as conn:
                results.append(objects.ingest(conn, store, docs, PDF, agent=AGENT))
        except Exception as e:          # noqa: BLE001 — ошибку проверяет тест
            errors.append(e)

    threads = [threading.Thread(target=run) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len({r.object_id for r in results}) == 1 and sorted(r.created for r in results) == [False, False, True]
    assert kb.execute("SELECT count(*) FROM object_version").fetchone()[0] == 1


def test_web_and_message_have_one_version_without_file(kb, monkeypatch):
    class Today(date):
        @classmethod
        def today(cls):
            return date(2026, 1, 2)

    monkeypatch.setattr(objects, "date", Today)            # дата обращения — сегодня по часам сервера, а не UTC
    page = objects.web(kb, "https://example.org/catalog/item-1")
    assert objects.web(kb, "https://example.org/catalog/item-1") == \
        objects.Version(page.object_id, 1, None, "web", created=False)
    title = "Письмо ООО «Ромашка» от 12.03.2024, й"
    letter = objects.message(kb, unicodedata.normalize("NFD", title))
    assert letter.kind == "message" and letter.digest is None
    assert not objects.message(kb, title).created                          # название — в NFC
    assert lookup.get_object(kb, letter.object_id)["original_name"] == title
    record = lookup.get_object(kb, page.object_id)
    model_v1.ObjectRecord.model_validate_json(json.dumps(record), strict=True)
    assert record["url"] == "https://example.org/catalog/item-1" and record["retrieved_at"] == "2026-01-02"
    assert record["versions"] == [{"n": 1, "recorded_at": record["versions"][0]["recorded_at"]}]
    with pytest.raises(ObjectError, match="пустой"):
        objects.message(kb, "  ")
    with pytest.raises(ObjectError, match="символ NUL"):
        objects.web(kb, "https://example.org/\x00")
    assert kb.execute("SELECT count(*) FROM object").fetchone()[0] == 2


def test_concurrent_message_gives_one_object(kb):
    results, errors = [], []

    def run():
        try:
            with same_database(kb, autocommit=True) as conn:
                results.append(objects.message(conn, "Письмо от 12.03.2024"))
        except Exception as e:          # noqa: BLE001 — ошибку проверяет тест
            errors.append(e)

    threads = [threading.Thread(target=run) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [] and len({r.object_id for r in results}) == 1


def test_resolve_sources_fills_object_version_and_digest(kb, docs, store):
    (docs / "Заметки" / "LICENSE").write_text("MIT\n", encoding="utf-8")       # файл без расширения — тоже файл
    agent_digest = "sha256:" + "00" * 32
    payload = {"kind": "fact", "label": {"ru": "Факт"}, "sources": [
        {"path": PDF, "quote": "Таблица 1", "digest": agent_digest},
        {"path": "example.org/docs/TS.pdf"},
        {"path": "https://example.org/catalog", "digest": agent_digest},
        {"path": "Письмо ООО «Ромашка» от 12.03.2024"},
        {"path": "Заметки/LICENSE"},
        {"path": "Ответ на письмо № 12\\03"},
        {"object": "obj:уже-разрешён", "object_version": 3}]}
    before = copy.deepcopy(payload)
    resolved = objects.resolve_sources(kb, store, docs, payload, agent=AGENT)
    pdf, site, page, letter, license_, answer, untouched = resolved["sources"]
    file = lookup.object_by_path(kb, PDF)
    assert (pdf["object"], pdf["object_version"], pdf["quote"]) == (file, 1, "Таблица 1")
    assert pdf["digest"] == lookup.get_object(kb, file)["versions"][0]["digest"]       # не из входа
    for web_source in (site, page):
        assert lookup.get_object(kb, web_source["object"])["kind"] == "web" and "digest" not in web_source
    assert lookup.get_object(kb, letter["object"])["kind"] == "message"
    assert lookup.get_object(kb, license_["object"])["kind"] == "file"
    assert lookup.get_object(kb, answer["object"])["original_name"] == "Ответ на письмо № 12\\03"   # «\\» — не путь
    assert untouched == payload["sources"][6] and payload == before                    # вход не изменён


@pytest.mark.parametrize("path, message", [
    ("НД/СП 99", "файла нет в папке документов — возможно, «НД/СП 99.pdf»?"),
    ("НД", "это папка, а не файл"),
    ("НД/СП 20.13330.2016", "файла нет в папке документов"),
    ("example.org", "похоже на адрес сайта — укажите его со схемой: https://example.org"),
    ("НД/Архив/СП 99", "файла нет в папке документов"),
    ("Йод/Письмо", "файла нет в папке документов"),
    ("Йод", "это папка, а не файл"),
    ("example.net/каталог", "файла нет в папке документов"),
    ("example.net", "это папка, а не файл"),
    ("manual.final", "файла нет в папке документов — возможно, «manual.final.pdf»?"),
    ("НД/../НД/СП 99.pdf", "«..» в пути не допускается"),
], ids=["без расширения", "папка", "точки в имени", "домен без схемы", "глубже существующей папки", "папка в NFD",
        "папка в NFD целиком", "папка с именем сайта", "папка с именем сайта целиком", "расширение раньше домена",
        "выход выше"])
def test_source_that_looks_like_a_file_is_not_a_message(kb, docs, store, path, message):
    """Путь к файлу без расширения, папка, путь в существующую папку, домен — ошибка с подсказкой, а не переписка:
    иначе источник остался бы без копии и без сверки цитаты. Папки ищутся по первой части пути с именами в NFC
    и раньше адреса сайта."""
    (docs / unicodedata.normalize("NFD", "Йод")).mkdir()
    (docs / "example.net").mkdir()
    shutil.copy(docs / PDF, docs / "manual.final.pdf")
    with pytest.raises(ObjectError, match=re.escape(f"sources[0]: {path}: {message}")):
        objects.resolve_sources(kb, store, docs, {"sources": [{"path": path}]}, agent=AGENT)
    assert kb.execute("SELECT count(*) FROM object").fetchone()[0] == 0


def test_path_forms(kb, docs, store):
    """Обратная косая черта — разделитель; абсолютный путь — ошибка; ссылка внутри папки документов — свой путь
    к тому же объекту."""
    first = objects.ingest(kb, store, docs, PDF.replace("/", "\\"), agent=AGENT)
    assert lookup.object_by_path(kb, PDF) == first.ref == lookup.object_by_path(kb, PDF.replace("/", "\\"))
    with pytest.raises(ObjectError, match="нужен путь от корня папки документов"):
        objects.ingest(kb, store, docs, str(docs / PDF), agent=AGENT)
    (docs / "Ссылки").mkdir()
    (docs / "Ссылки" / "СП.pdf").symlink_to(docs / PDF)
    link = objects.ingest(kb, store, docs, "Ссылки/СП.pdf", agent=AGENT)
    assert (link.object_id, link.created) == (first.object_id, False)
    assert lookup.object_by_path(kb, "Ссылки/СП.pdf") == first.ref
    for same in ("./НД/СП 99.pdf", "НД//СП 99.pdf"):                  # ключ — путь после normpath
        again = objects.ingest(kb, store, docs, same, agent=AGENT)
        assert (again.object_id, again.created) == (first.object_id, False)
    assert lookup.get_object(kb, first.ref)["logical_paths"] == [PDF, "Ссылки/СП.pdf"]
    for outside in ("../docs/" + PDF, "НД/../НД/СП 99.pdf"):         # «..» не даёт ключа выше корня
        with pytest.raises(ObjectError, match="«..» в пути не допускается"):
            objects.ingest(kb, store, docs, outside, agent=AGENT)


def test_link_without_suffix_takes_the_file_name(kb, docs, store):
    """Ссылка без расширения на PDF: имя объекта — имя самого файла, текст извлекается как у PDF."""
    (docs / "Ссылки").mkdir()
    (docs / "Ссылки" / "СП без расширения").symlink_to(docs / PDF)
    version = objects.ingest(kb, store, docs, "Ссылки/СП без расширения", agent=AGENT)
    assert lookup.get_object(kb, version.ref)["original_name"] == "СП 99.pdf"
    assert objects.text(kb, store, version.object_id, 1)


def test_nfd_file_name(kb, docs, store):
    """Имя файла на диске в NFD (архивы, macOS): ключ пути и имя — в NFC, файл находится по обоим написаниям."""
    nfc = "Заметки/й узел.md"
    (docs / unicodedata.normalize("NFD", nfc)).write_text("Узел\n", encoding="utf-8")
    first = objects.ingest(kb, store, docs, unicodedata.normalize("NFD", nfc), agent=AGENT)
    assert lookup.object_by_path(kb, nfc) == first.ref
    assert lookup.get_object(kb, first.ref)["original_name"] == "й узел.md"
    again = objects.ingest(kb, store, docs, nfc, agent=AGENT)
    assert (again.object_id, again.created) == (first.object_id, False)


@pytest.mark.skipif(os.geteuid() == 0, reason="root читает файл и без прав")
def test_unreadable_file_is_an_object_error(kb, docs, store):
    (docs / "Заметки" / "узел.md").chmod(0)
    try:
        with pytest.raises(ObjectError, match=r"sources\[0\]: Заметки/узел.md: файл не читается"):
            objects.resolve_sources(kb, store, docs, {"sources": [{"path": "Заметки/узел.md"}]}, agent=AGENT)
    finally:
        (docs / "Заметки" / "узел.md").chmod(0o644)


def test_resolve_sources_names_the_failing_source(kb, docs, store):
    payload = {"kind": "fact", "label": {"ru": "Факт"}, "sources": [{"path": PDF}, {"path": "НД/нет такого.pdf"}]}
    with pytest.raises(ObjectError, match=r"sources\[1\]: НД/нет такого.pdf: файла нет"):
        objects.resolve_sources(kb, store, docs, payload, agent=AGENT)


def test_old_source_opens_its_own_copy(kb, docs, store):
    """Атом ссылается на v1, файл изменили, новая ревизия — на v2: источник первой ревизии открывает копию v1."""
    old = (docs / PDF).read_bytes()

    def fact(codes):
        return {"ref": "@f", "kind": "fact", "key": "sp99.t1", "label": {"ru": "Значение из табл. 1 СП 99"},
                "codes": codes, "sources": [{"path": PDF, "quote": "Таблица 1"}]}

    first = commit(kb, [Item("atom", objects.resolve_sources(kb, store, docs, fact(["t1"]), agent=AGENT))],
                   agent=AGENT)
    record_id = first.revisions[0].record_id
    (docs / PDF).write_bytes(old + b"%2")
    body = {k: v for k, v in fact(["t1", "ред. 2"]).items() if k != "ref"}
    commit(kb, [Item("atom", objects.resolve_sources(kb, store, docs, body, agent=AGENT), record_id=record_id)],
           agent=AGENT)
    old_revision, new_revision = lookup.history(kb, "atom", record_id)
    [old_source] = lookup.revision_sources(kb, "atom", old_revision["id"])
    [new_source] = lookup.revision_sources(kb, "atom", new_revision["id"])
    assert (old_source["object"], old_source["object_version"]) == (new_source["object"], 1)
    assert new_source["object_version"] == 2
    object_id = old_source["object"].split(":", 1)[1]
    assert store.content(object_id, 1).read_bytes() == old
    assert "path" not in lookup.get(kb, "atom", record_id)["sources"][0]          # путь не входит в тело ревизии


def test_text_is_extracted_once_per_content(kb, docs, store, monkeypatch):
    version = objects.ingest(kb, store, docs, PDF, agent=AGENT)
    pages = objects.text(kb, store, version.object_id, 1)
    assert pages and len(pages) == len(sources.extract_pages(docs / PDF))

    def no_more(path):
        raise AssertionError("текст уже в кэше — извлекать заново не нужно")

    monkeypatch.setattr(sources, "extract_pages", no_more)
    assert objects.text(kb, store, version.object_id, 1) == pages


def test_text_is_nfc_and_missing_text_is_cached(kb, docs, store, monkeypatch):
    nfd = unicodedata.normalize("NFD", "Узел примыкания: шаг кронштейнов й")
    (docs / "Заметки" / "nfd.md").write_text(nfd, encoding="utf-8")
    note = objects.ingest(kb, store, docs, "Заметки/nfd.md", agent=AGENT)
    assert objects.text(kb, store, note.object_id, 1) == [unicodedata.normalize("NFC", nfd)]
    scan = objects.ingest(kb, store, docs, "НД/скан.docx", agent=AGENT)
    assert objects.text(kb, store, scan.object_id, 1) is None
    assert kb.execute("SELECT page FROM object_text WHERE digest = %s", (scan.digest,)).fetchall() == [(0,)]
    (docs / "Заметки" / "nul.md").write_bytes("e\x00\u0301 и a\x00b".encode())         # NUL — до NFC: «é», а не «é»
    nul = objects.ingest(kb, store, docs, "Заметки/nul.md", agent=AGENT)
    assert objects.text(kb, store, nul.object_id, 1) == ["\u00e9 и ab"]
    assert objects.text(kb, store, objects.web(kb, "https://example.org/").object_id, 1) is None
    with pytest.raises(ObjectError, match="нет версии 2") as e:
        objects.text(kb, store, note.object_id, 2)
    assert e.value.code == "not_found"


def test_mark_keeps_history_and_latest_wins(kb, docs, store, monkeypatch):
    version = objects.ingest(kb, store, docs, PDF, agent=AGENT)
    assert lookup.object_status(kb, version.object_id) is None
    objects.mark(kb, version.object_id, "partial", agent=AGENT, note="разд. 10–11")
    assert lookup.object_status(kb, version.object_id)["note"] == "разд. 10–11"
    earlier = datetime.now(timezone.utc) - timedelta(minutes=5)
    monkeypatch.setattr(objects, "_now", lambda: earlier)           # часы ушли назад (WSL2 после сна)
    # и id меньше прежнего (другой процесс со своими часами): порядок решает только время, и оно растёт
    monkeypatch.setattr(objects, "uuid7", lambda: uuid.UUID("01929f3a-7c4e-7b21-9a6f-3d2c8e1f0a55"))
    objects.mark(kb, version.object_id, "parsed", agent="person:filipp")
    status = lookup.object_status(kb, version.object_id)
    assert (status["status"], status["agent"], "note" in status) == ("parsed", "person:filipp", False)
    assert kb.execute("SELECT count(*) FROM object_status").fetchone()[0] == 2


def test_concurrent_marks_get_distinct_times(kb, docs, store, monkeypatch):
    """Отметки одного объекта идут по очереди: даже при одинаковых часах у каждой своё время, последняя — одна."""
    version = objects.ingest(kb, store, docs, PDF, agent=AGENT)
    frozen = datetime.now(timezone.utc)
    monkeypatch.setattr(objects, "_now", lambda: frozen)
    start, errors = threading.Barrier(4), []

    def run():
        try:
            with same_database(kb, autocommit=True) as conn:
                start.wait()
                objects.mark(conn, version.object_id, "partial", agent=AGENT)
        except Exception as e:          # noqa: BLE001 — ошибку проверяет тест
            errors.append(e)

    threads = [threading.Thread(target=run) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    times = [r[0] for r in kb.execute("SELECT changed_at FROM object_status")]
    assert errors == [] and len(times) == len(set(times)) == 4


def test_object_functions_take_obj_ref(kb, docs, store):
    """Ссылка obj:<UUID> из object_by_path годится всем функциям объекта, как и UUID."""
    objects.ingest(kb, store, docs, PDF, agent=AGENT)
    ref = lookup.object_by_path(kb, PDF)
    objects.mark(kb, ref, "parsed", agent=AGENT)
    assert lookup.object_status(kb, ref)["status"] == "parsed"
    assert lookup.get_object(kb, ref)["logical_paths"] == [PDF]
    assert objects.text(kb, store, ref, 1) == objects.text(kb, store, ref.split(":", 1)[1], 1)


@pytest.mark.parametrize("call, message", [
    (lambda kb, oid: objects.mark(kb, oid, "разобран", agent=AGENT), "нужен один из parsed, partial, skipped"),
    (lambda kb, oid: objects.mark(kb, "01929f3a-7c4e-7b21-9a6f-3d2c8e1f0a55", "parsed", agent=AGENT),
     "такого объекта нет"),
    (lambda kb, oid: objects.mark(kb, "не uuid", "parsed", agent=AGENT), "это не UUID"),
], ids=["статус", "нет объекта", "не UUID"])
def test_mark_errors(kb, docs, store, call, message):
    version = objects.ingest(kb, store, docs, PDF, agent=AGENT)
    with pytest.raises((ObjectError, ValueError), match=message) as e:
        call(kb, version.object_id)
    assert getattr(e.value, "code", None) == ("not_found" if message == "такого объекта нет" else None)


@pytest.mark.parametrize("agent", ["claude", "Model:Claude", "person:", "model:клод", "model:a b", None])
def test_bad_agent_is_object_error(kb, docs, store, agent):
    """Агент пишется в базу: неверный формат — ObjectError до любой записи, а не сбой ограничения agent."""
    with pytest.raises(objects.ObjectError, match="person:<имя> или model:<имя>"):
        objects.ingest(kb, store, docs, "Заметки/узел.md", agent=agent)
    with pytest.raises(objects.ObjectError, match="person:<имя> или model:<имя>"):
        objects.resolve_sources(kb, store, docs, {"sources": [{"path": "Заметки/узел.md"}]}, agent=agent)
    assert kb.execute("SELECT count(*) FROM object").fetchone()[0] == 0
