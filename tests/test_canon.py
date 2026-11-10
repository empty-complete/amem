"""Каноническая форма тела ревизии: пустое убирается (кроме ячеек таблицы), ссылки только по UUID, строки в NFC,
большие целые — как их вернёт jsonb; хэш устойчив и совпадает с эталоном."""
import copy
import json
import re
import unicodedata
from decimal import Decimal

import pytest
import rfc8785

from amemo import canon
from amemo.ids import uuid7
from v1_support import schema_attrs, schema_yaml

ENT = f"ent:{uuid7()}"
OBJ = f"obj:{uuid7()}"
DIGEST = "sha256:" + "ab" * 32


def atom(**extra) -> dict:
    return {"kind": "norm", "label": {"ru": "Нормативное ветровое давление w0"}, "about": [ENT],
            "sources": [{"object": OBJ, "object_version": 1, "digest": DIGEST, "quote": "Таблица 11.1"}], **extra}


def value(amount) -> dict:
    return atom(content={"values": [{"property": "length", "amount": amount, "unit": "mm"}]})


def test_empty_values_dropped_but_table_cells_kept():
    table = {"columns": [{"code": "wind_pressure_norm", "label": {"ru": "w0"}}], "rows": [["Iа", None], ["I", 0.23]]}
    body = canon.canonical(atom(aliases=[], scope={}, summary_plain=None, content={"table": table, "values": []}), "atom")
    assert "aliases" not in body and "scope" not in body and "summary_plain" not in body
    assert body["content"] == {"table": table}


def test_ref_dropped_and_resolved_path_removed():
    payload = atom(ref="@w0")
    payload["sources"][0]["path"] = "Ресурсы/СП 20.pdf"
    body = canon.canonical(payload, "atom")
    assert "ref" not in body and "path" not in body["sources"][0]


def test_canonical_keeps_input_and_is_idempotent():
    payload = atom(ref="@w0", aliases=[], content={"table": {"columns": [{"code": "c", "label": {"ru": "c"}}],
                                                             "rows": [[None, 1]]}})
    before = copy.deepcopy(payload)
    body = canon.canonical(payload, "atom")
    assert payload == before
    assert canon.canonical(body, "atom") == body
    body["content"]["table"]["rows"][0][1] = 2                  # результат — копия, а не ссылка на вход
    assert payload["content"]["table"]["rows"][0][1] == 1


@pytest.mark.parametrize("target, change, message", [
    ("atom", lambda p: p["sources"][0].pop("object"), "нет object — источник не разрешён"),
    ("atom", lambda p: p["sources"][0].pop("object_version"), "нет object_version"),
    ("atom", lambda p: p.update(about=["ent:sp20_13330"]), r"about\[0\]"),
    ("atom", lambda p: p.update(about=["@sp20"]), r"about\[0\]"),
    ("atom", lambda p: p.update(about=[f"atm:{uuid7()}"]), "нужна ent:"),
    ("atom", lambda p: p.update(derived_from=[ENT]), r"derived_from\[0\]"),
    ("atom", lambda p: p.update(about="ent:sp20"), "about"),                     # одно значение вместо списка
    ("atom", lambda p: p.update(label={"ru": "w0\x00"}), r"label.ru: символ \\u0000"),
    ("entity", lambda p: p.update(edition_of="@sp20"), "edition_of"),
], ids=["нет объекта", "нет версии объекта", "ключ не разрешён", "@имя не разрешено", "about на атом",
        "derived_from на сущность", "about не список", "символ NUL", "редакция сущности не разрешена"])
def test_unresolved_or_wrong_refs_rejected(target, change, message):
    payload = atom() if target == "atom" else {"entity_class": "edition", "label": {"ru": "ред. 2016"}}
    change(payload)
    with pytest.raises(canon.CanonError, match=message):
        canon.canonical(payload, target)


def test_unknown_target_rejected():
    with pytest.raises(canon.CanonError, match="неизвестный вид записи 'link'"):
        canon.canonical(atom(), "link")


@pytest.mark.parametrize("texts", [("2500", "2500.0", "2.5e3"), ("0.3", "0.30", "3e-1")])
def test_numbers_hash_equal_in_any_notation(texts):
    hashes = {canon.content_hash(canon.canonical(value(json.loads(t)), "atom")) for t in texts}
    assert len(hashes) == 1


@pytest.mark.parametrize("number", [1e16, -1e16, 1e23, 1.2345678901234567e17, 1e300],
                         ids=["1e16", "-1e16", "1e23", "17 знаков", "1e300"])
def test_large_numbers_survive_jsonb(number):
    """jsonb хранит самую короткую десятичную запись числа и возвращает большое число целым — хэш не меняется."""
    body = canon.canonical(value(number), "atom")
    from_jsonb = copy.deepcopy(body)
    from_jsonb["content"]["values"][0]["amount"] = int(Decimal(repr(number)))     # как отдаёт psycopg из jsonb
    assert canon.content_hash(from_jsonb) == canon.content_hash(body)
    assert canon.canonical(from_jsonb, "atom") == body


def test_large_integers():
    assert canon.content_hash(canon.canonical(value(10 ** 16), "atom")) == \
        canon.content_hash(canon.canonical(value(1e16), "atom"))
    with pytest.raises(canon.CanonError, match="без потерь"):
        canon.canonical(value(2 ** 53 + 1), "atom")
    with pytest.raises(canon.CanonError, match="больше любого числа JSON"):
        canon.canonical(value(10 ** 400), "atom")


def test_keys_merging_under_nfc_rejected():
    nfd = unicodedata.normalize("NFD", "й")
    table = {"columns": [{"code": "c", "label": {"ru": "c"}}], "rows": [[{"й": 1, nfd: 2}]]}
    with pytest.raises(canon.CanonError, match="совпадают после приведения к NFC"):
        canon.canonical(atom(content={"table": table}), "atom")


def test_nfc_and_nfd_hash_equal():
    nfd = unicodedata.normalize("NFD", "Стойка каркаса — шаг до 2,5 м, ёлочный узел й")
    nfc = unicodedata.normalize("NFC", nfd)
    assert nfd != nfc
    a = canon.canonical(atom(label={"ru": nfd}), "atom")
    b = canon.canonical(atom(label={"ru": nfc}), "atom")
    assert a["label"]["ru"] == nfc and canon.content_hash(a) == canon.content_hash(b)


def test_empty_fields_do_not_change_hash():
    plain = canon.canonical(atom(), "atom")
    padded = canon.canonical(atom(aliases=[], scope={}, tags=None, content={}), "atom")
    assert canon.content_hash(plain) == canon.content_hash(padded)


GOLDEN = {
    "kind": "norm", "label": {"ru": "Нормативное ветровое давление w0"},
    "about": ["ent:01929f3a-7c4e-7b21-9a6f-3d2c8e1f0a55"],
    "content": {
        "values": [{"property": "wind_pressure_norm", "amount": 0.3, "unit": "kPa"},
                   {"property": "length", "amount": 2500.0, "unit": "mm"},
                   {"property": "thickness", "amount": 1e-7, "unit": "mm"},
                   {"property": "mass", "amount": 1e21, "unit": "kg"}],
        "table": {"columns": [{"code": "cell", "label": {"ru": "ячейка"}}],
                  "rows": [[{"\U0001F600": 1, "ﬁ": 2}, None]]}},
    "sources": [{"object": "obj:01929f3a-7c4e-7b21-9a6f-3d2c8e1f0a56", "object_version": 1,
                 "digest": "sha256:" + "ab" * 32, "quote": "Таблица 11.1"}]}
GOLDEN_JCS = (
    '{"about":["ent:01929f3a-7c4e-7b21-9a6f-3d2c8e1f0a55"],"content":{"table":{"columns":[{"code":"cell",'
    '"label":{"ru":"ячейка"}}],"rows":[[{"\U0001F600":1,"ﬁ":2},null]]},"values":[{"amount":0.3,'
    '"property":"wind_pressure_norm","unit":"kPa"},{"amount":2500,"property":"length","unit":"mm"},'
    '{"amount":1e-7,"property":"thickness","unit":"mm"},{"amount":1e+21,"property":"mass","unit":"kg"}]},'
    '"kind":"norm","label":{"ru":"Нормативное ветровое давление w0"},"sources":[{"digest":"sha256:'
    + "ab" * 32 + '","object":"obj:01929f3a-7c4e-7b21-9a6f-3d2c8e1f0a56","object_version":1,'
    '"quote":"Таблица 11.1"}]}')


def test_hash_of_known_body_never_changes():
    """Эталон: хэши ревизий хранятся навсегда — смена сериализатора или правил c1 не должна пройти незамеченной.

    Ключи «😀» и «ﬁ» RFC 8785 сортирует по UTF-16 иначе, чем Python, а числа пишет по правилам ECMAScript."""
    body = canon.canonical(GOLDEN, "atom")
    assert rfc8785.dumps(body).decode() == GOLDEN_JCS
    assert canon.content_hash(body) == "sha256-c1:cb931abca2c61d078b47c4a9134dce782596aee96123c633fca0818881f81bf2"


def test_hash_matches_schema_pattern():
    """Хэш из canon проходит шаблон content_hash схемы: формат задан в схеме, canon ему следует."""
    pattern = schema_attrs("Atom")["content_hash"]["pattern"]
    assert re.fullmatch(pattern, canon.content_hash(canon.canonical(atom(), "atom")))


def test_rows_only_in_table():
    """Ячейки таблицы не чистятся по имени поля rows — значит, rows не должно быть больше нигде в схеме."""
    owners = [name for name in schema_yaml()["classes"] if "rows" in schema_attrs(name)]
    assert owners == ["Table"]


PREFIXES = {"^(ent:": "ent", "^(atm:": "atm", "^obj:": "obj"}
REF_MARK = re.compile(r"\b(ent|atm|obj)\b")        # и вида ^((atm|ent):


def _ref_paths(class_name: str, prefix: str = "", seen: tuple = ()) -> dict:
    out = {}
    for name, slot in schema_attrs(class_name).items():
        slot = slot or {}
        step = name + ("[]" if slot.get("multivalued") else "")
        pattern = str(slot.get("pattern", ""))
        kind = next((v for k, v in PREFIXES.items() if pattern.startswith(k)), None)
        assert kind or not REF_MARK.search(pattern), f"{class_name}.{name}: шаблон ссылки не распознан: {pattern}"
        rng = slot.get("range", "string")
        if kind:
            out[prefix + step] = kind
        elif rng in schema_yaml()["classes"] and rng != "Any" and rng not in seen:
            out |= _ref_paths(rng, f"{prefix}{step}.", seen + (class_name,))
    return out


@pytest.mark.parametrize("target, class_name", [("atom", "AtomPayload"), ("entity", "EntityPayload")])
def test_ref_fields_match_schema(target, class_name):
    """REF_FIELDS — ровно все поля-ссылки тела в схеме: новое поле-ссылка не останется неразрешённым."""
    assert canon.REF_FIELDS[target] == _ref_paths(class_name)
