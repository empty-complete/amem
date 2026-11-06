"""Ссылки по ключу (records.resolve), список записей (lookup.list_records) и подписи (lookup.labels) —
подпроект 4, часть 4.0; на PostgreSQL 18 и 16."""
import json
from datetime import datetime

import pytest

from amem import db, folders, ids, lookup, profile, recipes, records
from amem.folders import FolderError
from amem.records import Item, RecordError, RecordNotFound
from v1_support import schema_attrs

MODEL = "model:test"
HUMAN = "person:tester"


@pytest.fixture
def kb(pg):
    db.prepare(pg)
    return pg


def atom(label, *, key=None, kind="fact", tags=None, about=None, ref=None, **item) -> Item:
    payload = {"kind": kind, "label": {"ru": label}, "sources": []}
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


def test_list_records_rejects_bad_filters(kb):
    commit(kb, atom("Ветер", key="wind"))
    with pytest.raises(FolderError):
        lookup.list_records(kb, folder="a//b")
    with pytest.raises(RecordNotFound):
        lookup.list_records(kb, about="ent:nope")
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
