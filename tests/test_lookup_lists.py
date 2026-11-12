"""Ссылки по ключу (records.resolve), список записей (lookup.list_records) и подписи (lookup.labels) —
подпроект 4, часть 4.0; на PostgreSQL 18."""
import json
from datetime import datetime

import pytest

from amemo import db, folders, ids, lookup, profile, recipes, records
from amemo.folders import FolderError
from amemo.records import Item, RecordError, RecordNotFound
from v1_support import schema_attrs

MODEL = "model:test"
HUMAN = "person:tester"


@pytest.fixture
def kb(pg):
    db.prepare(pg)
    return pg


def atom(label, *, key=None, kind="fact", tags=None, about=None, ref=None, **item) -> Item:
    payload = {"kind": kind, "label": {"ru": label}, "sources": item.pop("sources", [])}
    payload |= {name: value for name, value in (("key", key), ("tags", tags), ("about", about), ("ref", ref))
                if value is not None}
    return Item("atom", payload, **item)


def entity(label, *, key=None, cls="project", ref=None) -> Item:
    payload = {"entity_class": cls, "label": {"ru": label}}
    payload |= {name: value for name, value in (("key", key), ("ref", ref)) if value is not None}
    return Item("entity", payload)


def commit(kb, *items, agent=MODEL):
    return records.commit(kb, list(items), agent=agent)


def ref_of(revision) -> str:
    return f"{records.PREFIX[revision.target]}:{revision.record_id}"


def listed(kb, **filters) -> set[str]:
    return {item["ref"] for item in lookup.list_records(kb, **filters)["items"]}


class Counting:
    """Соединение, которое считает запросы: подписи берутся одним запросом."""

    def __init__(self, conn):
        self.conn = conn
        self.queries = 0

    def execute(self, *args, **kwargs):
        self.queries += 1
        return self.conn.execute(*args, **kwargs)

    def cursor(self, *args, **kwargs):
        raise AssertionError("подписи — одним conn.execute")

    def __getattr__(self, name):
        return getattr(self.conn, name)


# --- records.resolve ---


def test_resolve_by_uuid_and_key(kb):
    a, e = commit(kb, atom("Ветровая нагрузка", key="wind_load"), entity("Проект Альфа", key="alpha")).revisions
    assert records.resolve(kb, f"atm:{a.record_id}") == ("atom", a.record_id)
    assert records.resolve(kb, "atm:wind_load") == ("atom", a.record_id)
    assert records.resolve(kb, "ent:alpha") == ("entity", e.record_id)
    assert records.resolve(kb, f"ent:{e.record_id}") == ("entity", e.record_id)
    assert records.resolve(kb, f"atm:{str(a.record_id).upper()}") == ("atom", a.record_id)


def test_resolve_unknown_record_is_not_found(kb):
    a = commit(kb, atom("Ветровая нагрузка", key="wind_load")).revisions[0]
    assert issubclass(RecordNotFound, RecordError)
    for ref in (f"atm:{ids.uuid7()}", "atm:no_such_key", "ent:wind_load", f"ent:{a.record_id}"):
        with pytest.raises(RecordNotFound, match="такой записи нет|нет записи с ключом"):
            records.resolve(kb, ref)


def test_resolve_finds_current_key_not_old_one(kb):
    """Ключ — проекция текущей ревизии: после смены ключа старый запись не находит."""
    a = commit(kb, atom("Ветровая нагрузка", key="wind_old")).revisions[0]
    commit(kb, atom("Ветровая нагрузка", key="wind_new", record_id=a.record_id))
    assert records.resolve(kb, "atm:wind_new") == ("atom", a.record_id)
    with pytest.raises(RecordNotFound, match="нет записи с ключом wind_old"):
        records.resolve(kb, "atm:wind_old")
    assert lookup.get(kb, "atom", "atm:wind_old") is None


def test_resolve_key_pattern_matches_schema():
    """Ключ в ссылке — по тому же шаблону, что поле key атома и сущности: другой разбор ключа разошёлся бы с записью."""
    for cls in ("AtomPayload", "EntityPayload"):
        assert schema_attrs(cls)["key"]["pattern"] == f"^{records._KEY.pattern}$"


def test_resolve_garbage_is_record_error(kb):
    for bad in ("мусор", f"obj:{ids.uuid7()}", "@a", "atm:", "atm:Не ключ", "ent:not-a-uuid", "xyz:abc", None, 42):
        with pytest.raises(RecordError) as e:
            records.resolve(kb, bad)
        assert not isinstance(e.value, RecordNotFound), bad


def test_lookup_get_and_history_accept_ref(kb):
    a = commit(kb, atom("Ветровая нагрузка", key="wind_load")).revisions[0]
    by_id = lookup.get(kb, "atom", a.record_id)
    assert by_id["label"] == {"ru": "Ветровая нагрузка"}
    assert lookup.get(kb, "atom", "atm:wind_load") == by_id
    assert lookup.get(kb, "atom", f"atm:{a.record_id}") == by_id
    assert lookup.get(kb, "atom", str(a.record_id)) == by_id                 # как прежде
    assert lookup.get(kb, "atom", "atm:no_such_key") is None
    assert lookup.get(kb, "atom", ids.uuid7()) is None
    assert lookup.history(kb, "atom", "atm:wind_load") == lookup.history(kb, "atom", a.record_id)
    assert lookup.history(kb, "atom", "atm:no_such_key") == []
    with pytest.raises(RecordError, match="atom"):
        lookup.get(kb, "entity", "atm:wind_load")
    with pytest.raises(RecordError):
        lookup.get(kb, "atom", "atm:Не ключ")


# --- по ключу: рецепты и карточка ---


def test_recipes_and_card_find_record_by_key(kb):
    e, a, other = commit(kb, entity("Проект Альфа", key="alpha", ref="@alpha"),
                         atom("Ветровая нагрузка", key="wind_load", about=["@alpha"]),
                         atom("Ветровая нагрузка на фасад", key="facade_wind")).revisions
    ent_ref, atom_ref = ref_of(e), ref_of(a)

    changed = recipes.what_changed(kb, ref="atm:wind_load")
    assert changed["ref"] == atom_ref
    assert changed["events"] and {event["ref"] for event in changed["events"]} == {atom_ref}

    graph = recipes.around_entity(kb, "ent:alpha")
    assert graph["start"] == ent_ref and atom_ref in {node["ref"] for node in graph["nodes"]}

    similar = recipes.similar(kb, "atm:wind_load", agent=MODEL)
    found = {item["ref"] for item in similar["items"]}
    assert ref_of(other) in found and atom_ref not in found                 # сама запись — не похожая

    card = profile.card(kb, "ent:alpha")
    assert card["entity"]["ref"] == ent_ref and card["entity"]["label"] == {"ru": "Проект Альфа"}


def test_recipes_and_card_unknown_key_is_not_found(kb):
    commit(kb, atom("Ветровая нагрузка", key="wind_load"))
    calls = {
        "what_changed": lambda: recipes.what_changed(kb, ref="atm:nope"),
        "around_entity": lambda: recipes.around_entity(kb, "ent:nope"),
        "similar": lambda: recipes.similar(kb, "atm:nope", agent=MODEL),
        "card": lambda: profile.card(kb, "ent:nope"),
        "card uuid": lambda: profile.card(kb, f"ent:{ids.uuid7()}"),
    }
    for name, call in calls.items():
        with pytest.raises(RecordNotFound):
            call()
    with pytest.raises(RecordError, match="сущност"):
        profile.card(kb, "atm:wind_load")                                   # карточка — только у сущности


# --- lookup.list_records ---


def test_list_records_summary_fields(kb):
    e, a = commit(kb, entity("Проект Альфа", key="alpha", ref="@alpha"),
                  atom("Ветровая нагрузка", key="wind", tags=["ветер", "фасад"], about=["@alpha"])).revisions
    folders.move(kb, ref_of(a), "Проекты/Альфа", agent=HUMAN)
    recorded = kb.execute("SELECT recorded_at FROM atom_revision WHERE atom_id = %s", (a.record_id,)).fetchone()[0]

    result = lookup.list_records(kb)

    assert result["total"] == 2 and result["next_cursor"] is None
    items = {item["ref"]: item for item in result["items"]}
    assert items[ref_of(a)] == {
        "ref": ref_of(a), "target": "atom", "label": "Ветровая нагрузка", "kind_or_class": "fact",
        "status": "draft", "folder": "Проекты/Альфа", "about": [ref_of(e)], "tags": ["ветер", "фасад"],
        "recorded_at": recorded.isoformat(), "agent": MODEL}
    assert items[ref_of(e)] == {
        "ref": ref_of(e), "target": "entity", "label": "Проект Альфа", "kind_or_class": "project",
        "status": "draft", "folder": None, "about": [], "tags": [], "recorded_at": recorded.isoformat(),
        "agent": MODEL}
    assert json.loads(json.dumps(result)) == result                          # JSON-совместимо


def test_list_records_shows_current_revision_not_pending(kb):
    first = commit(kb, atom("Старая подпись")).revisions[0]
    recorded = kb.execute("SELECT recorded_at FROM atom_revision WHERE atom_id = %s",
                          (first.record_id,)).fetchone()[0]
    commit(kb, atom("Новая подпись", record_id=first.record_id, review_state="pending"), agent="model:other")
    [item] = lookup.list_records(kb)["items"]
    assert (item["label"], item["recorded_at"], item["agent"]) == ("Старая подпись", recorded.isoformat(), MODEL)

    commit(kb, atom("Принятая подпись", record_id=first.record_id), agent=HUMAN)
    [item] = lookup.list_records(kb)["items"]
    assert (item["label"], item["agent"]) == ("Принятая подпись", HUMAN)


def test_list_records_filters(kb):
    alpha, doc, wind, snow, sibling, plain, old = commit(
        kb,
        entity("Проект Альфа", key="alpha", ref="@alpha"),
        entity("Положение о складе", key="store_rules", cls="document"),
        atom("Ветер", key="wind", tags=["ветер"], about=["@alpha"]),
        atom("Снег", key="snow", kind="decision", tags=["снег"]),
        atom("Сосед", key="sibling"),
        atom("Без папки", key="plain"),
        atom("Было про Альфу", key="old", about=["@alpha"], tags=["ветер"]),
    ).revisions
    every = {ref_of(r) for r in (alpha, doc, wind, snow, sibling, plain, old)}
    folders.move(kb, ref_of(alpha), "Проекты/Альфа", agent=HUMAN)
    folders.move(kb, ref_of(wind), "Проекты", agent=HUMAN)
    folders.move(kb, ref_of(snow), "Проекты/Альфа/Узлы", agent=HUMAN)
    folders.move(kb, ref_of(sibling), "Проекты2", agent=HUMAN)               # общее начало строки — не вложенная
    records.set_status(kb, "atom", plain.record_id, "verified", agent=HUMAN)
    records.set_status(kb, "atom", old.record_id, "deprecated", agent=HUMAN)
    commit(kb, atom("Было про Альфу", key="old", record_id=old.record_id))     # текущая ревизия — без about и тегов

    assert listed(kb) == every                                                # по умолчанию — все статусы
    assert listed(kb, folder="") == every and listed(kb, folder=None) == every
    assert listed(kb, folder="Проекты") == {ref_of(alpha), ref_of(wind), ref_of(snow)}
    assert listed(kb, folder=" Проекты / Альфа ") == {ref_of(alpha), ref_of(snow)}
    assert listed(kb, folder="-") == {ref_of(doc), ref_of(plain), ref_of(old)}
    assert listed(kb, folder="Нет такой") == set()
    assert listed(kb, kinds=["fact"]) == {ref_of(wind), ref_of(sibling), ref_of(plain), ref_of(old)}
    assert listed(kb, kinds=["project", "decision"]) == {ref_of(alpha), ref_of(snow)}
    assert listed(kb, kinds=[]) == every                                      # пустой набор — без фильтра
    assert listed(kb, statuses=["verified"]) == {ref_of(plain)}
    assert listed(kb, statuses=["draft", "deprecated"]) == every - {ref_of(plain)}
    assert listed(kb, tag="ветер") == {ref_of(wind)}
    assert listed(kb, tag="снег") == {ref_of(snow)}
    assert listed(kb, about="ent:alpha") == {ref_of(wind)}
    assert listed(kb, about=ref_of(alpha)) == {ref_of(wind)}
    assert listed(kb, folder="Проекты", kinds=["fact"], statuses=["draft"], tag="ветер",
                  about="ent:alpha") == {ref_of(wind)}

    assert lookup.list_records(kb, folder="Проекты")["total"] == 3
    assert lookup.list_records(kb, folder="Проекты", limit=1)["total"] == 3   # total — по фильтру, не по странице
    assert lookup.list_records(kb, folder="Нет такой") == {"items": [], "next_cursor": None, "total": 0}


def test_list_records_about_unknown_is_empty(kb):
    commit(kb, atom("Ветер", key="wind"))
    empty = {"items": [], "next_cursor": None, "total": 0}
    assert lookup.list_records(kb, about="ent:nope") == empty
    assert lookup.list_records(kb, about=f"ent:{ids.uuid7()}") == empty
    assert lookup.list_records(kb, about=f"obj:{ids.uuid7()}") == empty
    assert lookup.list_records(kb, about=str(ids.uuid7())) == empty
    with pytest.raises(RecordError):
        lookup.list_records(kb, about="obj:не-uuid")


def test_list_records_about_object(kb, tmp_path):
    """about=obj:<UUID> или голый UUID — записи (атомы и сущности), у текущей ревизии которых источник на объект."""
    from amemo import objects
    from amemo.ocfl_store import ObjectStore
    from samples import make_docs

    docs, store = make_docs(tmp_path / "docs"), ObjectStore(tmp_path / "objects")
    pdf, note = (objects.ingest(kb, store, docs, p, agent=MODEL) for p in ("НД/СП 99.pdf", "Заметки/узел.md"))

    def src(version):
        return [{"object": version.ref, "object_version": 1, "digest": version.digest, "quote": "Таблица 1"}]

    wind, other, spec, old = commit(
        kb, atom("Ветер", key="wind", sources=src(pdf)), atom("Про заметку", sources=src(note)),
        Item("entity", {"entity_class": "document", "label": {"ru": "СП 99"}, "sources": src(pdf)}),
        atom("Было из СП", sources=src(pdf))).revisions
    commit(kb, atom("Стало без источника", record_id=old.record_id))      # текущая ревизия — без источника
    assert listed(kb, about=pdf.ref) == {ref_of(wind), ref_of(spec)}
    assert listed(kb, about=str(pdf.object_id)) == {ref_of(wind), ref_of(spec)}
    assert listed(kb, about=note.ref) == {ref_of(other)}
    assert lookup.list_records(kb, about=pdf.ref)["total"] == 2
    assert listed(kb, about=pdf.ref, kinds=["document"]) == {ref_of(spec)}
    assert listed(kb, about=pdf.ref, tag="нет") == set()
    folders.move(kb, ref_of(wind), "Проекты", agent=HUMAN)
    assert listed(kb, about=pdf.ref, folder="Проекты") == {ref_of(wind)}
    assert lookup.list_records(kb, about=pdf.ref, folder="Проекты")["total"] == 1


def test_get_has_folder(kb):
    [a] = commit(kb, atom("Ветер", key="wind")).revisions
    assert lookup.get(kb, "atom", a.record_id)["folder"] is None
    folders.move(kb, ref_of(a), "Проекты/Альфа", agent=HUMAN)
    assert lookup.get(kb, "atom", a.record_id)["folder"] == "Проекты/Альфа"


def test_list_records_rejects_bad_filters(kb):
    commit(kb, atom("Ветер", key="wind"))
    with pytest.raises(FolderError):
        lookup.list_records(kb, folder="a//b")
    bad = [{"about": "atm:wind"}, {"about": "мусор"}, {"statuses": ["nope"]}, {"statuses": "draft"},
           {"kinds": "fact"}, {"kinds": [1]}, {"tag": 5}, {"limit": 0}, {"limit": 201}, {"limit": True},
           {"limit": "10"}, {"cursor": "мусор"}, {"cursor": "bm90IGEgY3Vyc29y"}]
    for filters in bad:
        with pytest.raises(RecordError):
            lookup.list_records(kb, **filters)


def test_list_records_cursor_pages_without_gaps_or_repeats(kb):
    first = commit(kb, *[atom(f"Атом {i}") for i in range(60)])          # одно время на пакет: порядок — по id
    commit(kb, *[atom(f"Атом {i}") for i in range(60, 100)])
    commit(kb, *[entity(f"Сущность {i}") for i in range(20)])
    lifted = first.revisions[7]
    commit(kb, atom("Атом 7, правка", record_id=lifted.record_id))           # новая ревизия поднимает запись наверх

    seen, sizes, cursor = [], [], None
    while True:
        page = lookup.list_records(kb, limit=50, cursor=cursor)
        assert page["total"] == 120
        sizes.append(len(page["items"]))
        seen += page["items"]
        cursor = page["next_cursor"]
        if cursor is None:
            break
        assert isinstance(cursor, str)
    assert sizes == [50, 50, 20]
    refs = [item["ref"] for item in seen]
    assert len(refs) == len(set(refs)) == 120
    assert refs[0] == ref_of(lifted)
    order = [(datetime.fromisoformat(item["recorded_at"]), item["ref"].split(":", 1)[1]) for item in seen]
    assert order == sorted(order, reverse=True)
    assert lookup.list_records(kb, limit=50, cursor="")["items"] == seen[:50]      # пустой курсор — с начала


def test_list_records_cursor_skips_record_lifted_by_new_revision(kb):
    """Курсор — по recorded_at показанной ревизии: запись, поднятая новой ревизией выше курсора, на следующих
    страницах не встречается (так и описано в list_records)."""
    old, middle, new = (commit(kb, atom(label)).revisions[0] for label in ("Старый", "Средний", "Новый"))
    first = lookup.list_records(kb, limit=1)
    assert [i["ref"] for i in first["items"]] == [ref_of(new)]
    commit(kb, atom("Старый, правка", record_id=old.record_id))             # теперь он самый новый
    second = lookup.list_records(kb, limit=1, cursor=first["next_cursor"])
    assert [i["ref"] for i in second["items"]] == [ref_of(middle)] and second["next_cursor"] is None
    assert [i["ref"] for i in lookup.list_records(kb)["items"]] == [ref_of(old), ref_of(new), ref_of(middle)]


def test_list_records_inside_outer_transaction(kb):
    """Внутри транзакции вызывающего list_records читает её снимок и уровень изоляции не меняет."""
    commit(kb, atom("Ветер", tags=["ветер"]))
    with kb.transaction():
        kb.execute("SELECT 1")
        result = lookup.list_records(kb, tag="ветер")
    assert result["total"] == 1 and len(result["items"]) == 1


def test_list_records_agrees_with_folder_tree(kb):
    """Список и дерево папок считают записи любого статуса, и запись без текущей ревизии (единственная
    отклонена) тоже: иначе счётчики папок и список разошлись бы."""
    kept, moved = commit(kb, atom("Ветер"), atom("Снег")).revisions
    folders.move(kb, ref_of(moved), "Архив", agent=HUMAN)
    declined = commit(kb, atom("Отклонённый", review_state="pending")).revisions[0]
    records.decide(kb, "atom", declined.revision_id, False, agent=HUMAN)
    records.set_status(kb, "atom", declined.record_id, "rejected", agent=HUMAN)
    folders.move(kb, ref_of(declined), "Архив", agent=HUMAN)

    tree = folders.tree(kb)
    archive = next(f for f in tree["folders"] if f["path"] == "Архив")
    assert lookup.list_records(kb)["total"] == tree["total"] == 3
    assert lookup.list_records(kb, folder="-")["total"] == tree["unfiled"] == 1
    assert lookup.list_records(kb, folder="Архив")["total"] == archive["count"] == 2
    item = next(i for i in lookup.list_records(kb)["items"] if i["ref"] == ref_of(declined))
    assert (item["label"], item["status"], item["folder"]) == ("Отклонённый", "rejected", "Архив")


# --- lookup.labels ---


def test_labels_one_query_and_unknown_refs_omitted(kb):
    e, a = commit(kb, entity("Проект Альфа", key="alpha"), atom("Ветер", key="wind", kind="decision")).revisions
    commit(kb, atom("Ветер, ждёт проверки", key="wind", kind="decision", record_id=a.record_id,
                    review_state="pending"))
    records.set_status(kb, "entity", e.record_id, "verified", agent=HUMAN)
    counting = Counting(kb)

    got = lookup.labels(counting, [ref_of(a), "ent:alpha", ref_of(e), f"atm:{ids.uuid7()}", "atm:nope",
                                   "ent:wind", f"obj:{ids.uuid7()}", "мусор", ref_of(a)])

    assert counting.queries == 1
    assert got == {
        ref_of(a): {"label": "Ветер", "kind": "decision", "status": "draft"},
        "ent:alpha": {"label": "Проект Альфа", "entity_class": "project", "status": "verified"},
        ref_of(e): {"label": "Проект Альфа", "entity_class": "project", "status": "verified"},
    }
    empty = Counting(kb)
    assert lookup.labels(empty, []) == {} and lookup.labels(empty, ["мусор"]) == {} and empty.queries == 0
    with pytest.raises(RecordError):
        lookup.labels(kb, ref_of(a))                                          # строка — не набор ссылок


# --- поиск объектов (подпроект 4, часть 4d, задача 20) ---

def test_object_search_by_name_path_and_url(kb, store, tmp_path):
    from amemo import objects

    docs = tmp_path / "d"
    (docs / "Отчёты").mkdir(parents=True)
    (docs / "Отчёты" / "Протокол испытаний.md").write_text("Протокол.", encoding="utf-8")
    (docs / "notes.md").write_text("Заметки.", encoding="utf-8")
    a = objects.ingest(kb, store, docs, "Отчёты/Протокол испытаний.md", agent=HUMAN).object_id
    b = objects.ingest(kb, store, docs, "notes.md", agent=HUMAN).object_id
    w = objects.web(kb, "https://example.org/Page").object_id

    def found(q, **kw):
        return [i["id"] for i in lookup.object_search(kb, q, **kw)["items"]]

    assert found("протокол ИСП") == [str(a)]              # часть имени без учёта регистра
    assert found("отчёты/") == [str(a)]                   # часть пути
    assert found("NOTES") == [str(b)]
    assert found("example.org/page") == [str(w)]          # адрес страницы
    assert found("%") == [] and found("_") == []          # знаки LIKE — обычные знаки
    assert found(None) == [str(w), str(b), str(a)]        # пустой q — последние объекты, новые первыми
    assert found("  ") == found(None)
    first = lookup.object_search(kb, "", limit=2)
    assert [i["id"] for i in first["items"]] == [str(w), str(b)] and first["next_cursor"]
    assert first["items"][0]["kind"] == "web" and "cited_by" in first["items"][0]
    rest = lookup.object_search(kb, "", limit=2, cursor=first["next_cursor"])
    assert [i["id"] for i in rest["items"]] == [str(a)] and rest["next_cursor"] is None


def test_object_search_by_file_type(kb, store, tmp_path):
    """Род файла — по типу содержимого или расширению имени: PDF находится и среди сотни таблиц."""
    from amemo import objects

    docs = tmp_path / "d"
    docs.mkdir()
    for name in ("Отчёт.pdf", "Нагрузки.xlsx", "Справка.docx", "Итоги.md", "Схема.pptx", "Фото.png"):
        (docs / name).write_bytes(b"x" + name.encode())
    made = {name.rsplit(".", 1)[1]: str(objects.ingest(kb, store, docs, name, agent=HUMAN).object_id)
            for name in ("Отчёт.pdf", "Нагрузки.xlsx", "Справка.docx", "Итоги.md", "Схема.pptx", "Фото.png")}

    def found(file_type, q=None):
        return {i["id"] for i in lookup.object_search(kb, q, file_type=file_type)["items"]}

    assert found("pdf") == {made["pdf"]}
    assert found("sheet") == {made["xlsx"]}
    assert found("doc") == {made["docx"], made["md"]}
    assert found("slides") == {made["pptx"]}
    assert found("image") == {made["png"]}
    assert found("doc", "итоги") == {made["md"]}               # вместе с частью имени
    with pytest.raises(RecordError):
        lookup.object_search(kb, "", file_type="video")


@pytest.mark.parametrize("kw", [{"limit": 0}, {"limit": 101}, {"limit": "5"}, {"limit": True}, {"cursor": "мусор"},
                                {"cursor": lookup._cursor(datetime(2026, 1, 1).astimezone(), ids.uuid7())}])
def test_object_search_bad_arguments(kb, kw):
    with pytest.raises(RecordError):
        lookup.object_search(kb, "", **kw)


def test_list_records_by_several_tags(kb):
    """Несколько тегов — записи, у которых есть все; повтор и пустой тег не мешают."""
    both, wind = commit(kb, atom("Порыв в снегопад", tags=["ветер", "снег"]), atom("Ветер", tags=["ветер"])).revisions
    assert [i["ref"] for i in lookup.list_records(kb, tag=["ветер", "снег"])["items"]] == [ref_of(both)]
    assert lookup.list_records(kb, tag=["ветер", "", "ветер"])["total"] == 2
    assert lookup.list_records(kb, tag=[])["total"] == 2
    with pytest.raises(RecordError):
        lookup.list_records(kb, tag=["ветер", 1])
