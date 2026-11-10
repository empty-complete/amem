"""Подборки amem.bundle/1: отбор записей, экспорт в папку или zip, проверка без базы (спецификация 3c, разд. 4).

Подборка — папка (или zip той же структуры): manifest.json и части JSON Lines — entities, atoms, links, objects,
sources, concepts; по выбору — файлы объектов objects/sha256/<hex> и копии пакетов packs/<name>/. Записи идут
как есть: id, key, статус и текущая ревизия с каноническим телом и content_hash — получатель узнаёт то же
содержание по хэшу. Манифест пишется последним и даёт sha256 каждого файла: inspect сверяет их без базы.
Импорт (import_) вливает подборку с теми же id и ничего не затирает: расхождение с локальной записью — ревизия,
ждущая решения человека (пункт imported); устройство — в докстринге import_.

Отбор: запись попадает, если подходит под все заданные условия своего вида (пустое условие не ограничивает):
tags и kinds — условия атомов, entity_classes — сущностей, refs — явные ссылки своего вида (atm: / ent:),
project — обоих. Условия другого вида запись не отбирают и не отсекают: Selection(kinds=("note",)) берёт заметки,
а сущности приходят только замыканием. Selection() без условий — вся база. Статус (по умолчанию — все, кроме
rejected), since и приватность ограничивают всегда; visibility: private исключается, пока не задано
include_private. Замыкание — всегда, до неподвижной точки: все поля-ссылки тел (canon.REF_FIELDS: about,
scope.project, sources[].edition, edition_of, derived_from, content.formula.symbols[].term) у записей подборки и
у записей, пришедших замыканием; связи с обоими концами в подборке (и выведенные из оборота); объекты источников;
пакеты кодов и понятия агентов. Записи замыкания идут с любым статусом и вне since — ради целостности ссылок:
иначе получатель не примет подборку (ref_unknown). Исключение — атом rejected или приватный (без include_private):
выгрузить его молча нельзя, и подборка отклоняется с их перечнем.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import tempfile
import unicodedata
import uuid
import zipfile
from dataclasses import dataclass, field, fields
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from . import __version__, canon, lookup, mine, model_v1, objects, packs, records, review
from .ids import uuid7
from .ocfl_store import StoreError
from .records import PREFIX, RecordError, Target

FORMAT = "amem.bundle/1"
STATUSES = ("draft", "needs_review", "auto_verified", "verified", "rejected", "deprecated", "superseded")
DEFAULT_STATUSES = tuple(s for s in STATUSES if s != "rejected")
PARTS = ("entities.jsonl", "atoms.jsonl", "links.jsonl", "objects.jsonl", "sources.jsonl", "concepts.jsonl")
_CODE = {"atom": "kind", "entity": "entity_class"}      # столбец вида записи — из закрытого набора
_TARGET = {prefix: target for target, prefix in PREFIX.items()}
# пределы распаковки zip: подборка из чужих рук не должна заполнить диск или зависнуть на миллионе записей
MAX_UNPACKED = 4 << 30              # байт в сумме
MAX_MEMBERS = 200_000               # файлов в архиве
MAX_RATIO = 200                     # сжатие больше 200:1 у файла больше RATIO_FROM — признак zip-бомбы
RATIO_FROM = 1 << 20


class BundleError(ValueError):
    """Неверный отбор, подборка, которую нельзя записать или принять, или повреждённая подборка.

    code — код отказа импорта из CheckCode (bundle_pack_missing, bundle_key_collision) или None; details — для
    машины: missing, collisions, report (отчёт amem.check/1 уровня 1)."""

    def __init__(self, message: str, *, code: str | None = None, **details):
        # сообщение уходит наружу (ответ службы, вывод CLI): полных путей на диске в нём нет — только имя файла,
        # даже если путь пришёл в тексте вложенной ошибки (OSError, StoreError)
        super().__init__(_without_paths(message))
        self.code, self.details = code, details


_ABSOLUTE = re.compile(r"(?<![\w.~])/(?:[^\s/:'\"()]+/)+([^\s/:'\"()]+)")


def _without_paths(text: str) -> str:
    """Абсолютные пути в тексте → последнее имя: «/…/uploads/<id>/bundle.zip» → «bundle.zip»."""
    return _ABSOLUTE.sub(r"\1", text)


def _reason(e: BaseException) -> str:
    """Причина ошибки без пути: у OSError — strerror, иначе текст ошибки."""
    if isinstance(e, OSError) and e.strerror:
        return e.strerror
    return str(e)


@dataclass(frozen=True)
class Selection:
    """Условия отбора (разд. 4.1). Ссылки — atm:/ent: с UUID или ключом; project — ent:."""
    tags: tuple[str, ...] = ()
    project: str | None = None
    kinds: tuple[str, ...] = ()
    entity_classes: tuple[str, ...] = ()
    refs: tuple[str, ...] = ()
    statuses: tuple[str, ...] = DEFAULT_STATUSES
    since: datetime | None = None
    include_private: bool = False

    def __post_init__(self):
        # строка вместо кортежа дала бы отбор по буквам: tags="shared" — теги «s», «h», …
        for name in ("tags", "kinds", "entity_classes", "refs", "statuses"):
            value = getattr(self, name)
            if isinstance(value, (str, bytes)) or not isinstance(value, (tuple, list)) or \
                    not all(isinstance(v, str) for v in value):
                raise BundleError(f"Selection.{name}: нужен кортеж строк, получено {value!r}")
        if self.project is not None and not isinstance(self.project, str):
            raise BundleError(f"Selection.project: нужна строка ent:…, получено {self.project!r}")

    def as_json(self) -> dict:
        out = {}
        for f in fields(self):
            v = getattr(self, f.name)
            out[f.name] = list(v) if isinstance(v, (tuple, list)) else v.isoformat() if isinstance(v, datetime) else v
        return out


def _json(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    raise TypeError(f"{type(value).__name__} не переводится в JSON")


def _ref_uuid(ref: str) -> uuid.UUID:
    """Каноническая ссылка тела (ent:/atm:/obj:<UUID>) → UUID."""
    return uuid.UUID(ref.split(":", 1)[1])


def _resolve(conn, ref: str, allowed: tuple[str, ...]) -> tuple[Target, uuid.UUID]:
    """Ссылка отбора → вид записи и id; по UUID или ключу; записи нет — BundleError."""
    prefix, _, rest = ref.partition(":") if isinstance(ref, str) else ("", "", "")
    if prefix not in allowed or not rest:
        raise BundleError(f"{ref!r}: нужна ссылка {' или '.join(p + ':' for p in allowed)}<UUID или ключ>")
    target = _TARGET[prefix]
    try:
        record_id = uuid.UUID(rest)
        found = conn.execute(f"SELECT 1 FROM {target} WHERE id = %s", (record_id,)).fetchone() is not None
    except ValueError:
        found_ref = lookup.by_key(conn, target, rest)
        found, record_id = found_ref is not None, _ref_uuid(found_ref) if found_ref else None
    if not found:
        raise BundleError(f"{ref}: записи нет")
    return target, record_id


def _part_tree(conn, root: uuid.UUID) -> set[uuid.UUID]:
    """Сущность и всё, что входит в неё по действующим part_of (src part_of dst — вниз от dst)."""
    rows = conn.execute(
        "WITH RECURSIVE down(id) AS (SELECT %s::uuid UNION SELECT l.src_entity FROM link l JOIN down d "
        "ON l.dst_entity = d.id WHERE l.rel = 'part_of' AND l.retired_at IS NULL AND l.src_entity IS NOT NULL) "
        "SELECT id FROM down", (root,)).fetchall()
    return {r[0] for r in rows}


def _containers(conn, start: set[uuid.UUID], statuses: list[str]) -> set[uuid.UUID]:
    """Сущности, в которые start входит по действующим part_of (вверх), со статусом из отбора; UNION рвёт циклы."""
    if not start:
        return set()
    rows = conn.execute(
        "WITH RECURSIVE up(id) AS (SELECT unnest(%s::uuid[]) UNION SELECT l.dst_entity FROM link l JOIN up u "
        "ON l.src_entity = u.id WHERE l.rel = 'part_of' AND l.retired_at IS NULL AND l.dst_entity IS NOT NULL) "
        "SELECT up.id FROM up JOIN entity e ON e.id = up.id WHERE e.status = ANY(%s)",
        (list(start), statuses)).fetchall()
    return {r[0] for r in rows}


def _select(conn, s: Selection) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    """Атомы и сущности по условиям отбора, до замыкания."""
    unknown = set(s.statuses) - set(STATUSES)
    if unknown:
        raise BundleError(f"statuses: неизвестные статусы {sorted(unknown)}")
    if s.since is not None and (not isinstance(s.since, datetime) or s.since.tzinfo is None):
        raise BundleError(f"since {s.since!r}: нужно время с часовым поясом")
    refs: dict[str, list[uuid.UUID]] = {"atom": [], "entity": []}
    for ref in s.refs:
        target, record_id = _resolve(conn, ref, ("atm", "ent"))
        refs[target].append(record_id)
    project = _resolve(conn, s.project, ("ent",))[1] if s.project else None
    tree = _part_tree(conn, project) if project else set()
    anything = bool(s.tags or s.kinds or s.entity_classes or s.refs or project)
    params = {"statuses": list(s.statuses), "since": s.since, "tags": list(s.tags), "kinds": list(s.kinds),
              "classes": list(s.entity_classes), "atoms": refs["atom"], "entities": refs["entity"],
              "project": f"ent:{project}", "tree": list(tree)}

    def chosen(target: Target, own: list[str]) -> set[uuid.UUID]:
        if anything and not own:
            return set()                                  # заданы только условия другого вида
        where = ["rec.status = ANY(%(statuses)s)", *own]
        if s.since is not None:
            where.append("r.recorded_at >= %(since)s")
        if target == "atom" and not s.include_private:
            where.append("coalesce(r.payload->'scope'->>'visibility', '') <> 'private'")
        rows = conn.execute(f"SELECT rec.id FROM {target}_current r JOIN {target} rec ON rec.id = r.{target}_id "
                            f"WHERE {' AND '.join(where)}", params).fetchall()
        return {r[0] for r in rows}

    atom_own = [*(["r.payload->'tags' ?| %(tags)s::text[]"] if s.tags else []),
                *(["rec.kind = ANY(%(kinds)s)"] if s.kinds else []),
                *(["rec.id = ANY(%(atoms)s)"] if refs["atom"] else []),
                *(["(r.payload->'scope'->>'project' = %(project)s OR EXISTS (SELECT 1 FROM atom_about ab "
                   "WHERE ab.revision_id = r.id AND ab.entity_id = ANY(%(tree)s)))"] if project else [])]
    entity_own = [*(["rec.entity_class = ANY(%(classes)s)"] if s.entity_classes else []),
                  *(["rec.id = ANY(%(entities)s)"] if refs["entity"] else []),
                  *(["rec.id = ANY(%(tree)s)"] if project else [])]
    return chosen("atom", atom_own), chosen("entity", entity_own)


def _current(conn, target: Target, ids: set[uuid.UUID]) -> dict[uuid.UUID, dict]:
    """Текущие ревизии записей одним запросом: id → строка записи и ревизии."""
    if not ids:
        return {}
    t = target
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            f"SELECT rec.id AS record_id, rec.key, rec.status, rec.{_CODE[t]} AS code, r.id, r.n, r.schema_version, "
            f"r.content_hash, r.payload, r.review_state, r.recorded_at, cs.agent FROM {t}_current r "
            f"JOIN {t} rec ON rec.id = r.{t}_id JOIN changeset cs ON cs.id = r.changeset_id "
            f"WHERE rec.id = ANY(%s)", (list(ids),)).fetchall()
    return {r["record_id"]: r for r in rows}


def _body_refs(target: Target, payload: dict) -> dict[str, set[uuid.UUID]]:
    """Ссылки тела на атомы и сущности — по полям canon.REF_FIELDS (ссылки на объекты идут через sources.jsonl)."""
    out: dict[str, set[uuid.UUID]] = {"atm": set(), "ent": set()}
    for path, prefix in canon.REF_FIELDS[target].items():
        if prefix in out:
            out[prefix] |= {_ref_uuid(ref) for _, ref in canon.values_at(payload, path)}
    return out


def _private(row: dict) -> bool:
    return (row["payload"].get("scope") or {}).get("visibility") == "private"


def _closure(conn, s: Selection, atoms: dict[uuid.UUID, dict],
             entity_ids: set[uuid.UUID]) -> tuple[dict[uuid.UUID, dict], dict[uuid.UUID, dict]]:
    """Отбор и всё, на что ссылаются тела его записей и записей, пришедших так же, — до неподвижной точки.

    Ответ — текущие ревизии атомов и сущностей. Атом-цель rejected, приватный (без include_private) или без
    действующей ревизии — BundleError с перечнем: подборка без него сломала бы ссылку у получателя."""
    atoms = dict(atoms)
    entities: dict[uuid.UUID, dict] = {}
    want = {"atm": set(), "ent": set(entity_ids)}
    fresh = [("atom", row) for row in atoms.values()]
    visited = {"atm": set(atoms), "ent": set()}
    refused: list[str] = []
    while True:
        for target, row in fresh:
            for prefix, ids in _body_refs(target, row["payload"]).items():
                want[prefix] |= ids
        fresh = []
        new_atoms, new_entities = want["atm"] - visited["atm"], want["ent"] - visited["ent"]
        if not new_atoms and not new_entities:
            break
        visited["atm"] |= new_atoms
        visited["ent"] |= new_entities
        got = _current(conn, "atom", new_atoms)
        for atom_id in sorted(new_atoms):
            row = got.get(atom_id)
            why = ("нет действующей ревизии" if row is None else "rejected" if row["status"] == "rejected"
                   else "private" if not s.include_private and _private(row) else None)
            if why:
                refused.append(f"atm:{atom_id} ({why})")
            else:
                atoms[atom_id] = row
                fresh.append(("atom", row))
        got = _current(conn, "entity", new_entities)
        entities |= got
        fresh += [("entity", row) for row in got.values()]
    if refused:
        raise BundleError("записи подборки ссылаются на атомы, которые нельзя выгрузить: " + ", ".join(refused)
                          + " — уберите ссылку из отбора или задайте include_private")
    return atoms, entities


def _revision(row: dict) -> dict:
    return {"id": str(row["id"]), "n": row["n"], "schema_version": row["schema_version"],
            "content_hash": row["content_hash"], "payload": row["payload"], "agent": row["agent"],
            "recorded_at": row["recorded_at"].isoformat(), "review_state": row["review_state"]}


def _record_rows(conn, target: Target, current: dict[uuid.UUID, dict], with_history: bool) -> list[dict]:
    """Строки atoms.jsonl / entities.jsonl: запись и её текущая ревизия как есть; история — остальные ревизии."""
    out = []
    for record_id in sorted(current):
        row = current[record_id]
        item = {"id": str(record_id), "key": row["key"], _CODE[target]: row["code"], "status": row["status"],
                "revision": _revision(row)}
        if with_history:
            item["history"] = [_revision(h) for h in lookup.history(conn, target, record_id) if h["id"] != row["id"]]
        out.append(item)
    return out


def _links(conn, nodes: set[uuid.UUID]) -> list[dict]:
    """Связи с обоими концами в подборке, включая выведенные из оборота."""
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            "SELECT id, rel, src_atom, src_entity, dst_atom, dst_entity, note, qualifiers, confidence, created_at, "
            "agent, retired_at FROM link WHERE coalesce(src_atom, src_entity) = ANY(%(n)s) "
            "AND coalesce(dst_atom, dst_entity) = ANY(%(n)s) ORDER BY id", {"n": list(nodes)}).fetchall()
    return [{"id": str(r["id"]), "rel": r["rel"],
             "src": f"atm:{r['src_atom']}" if r["src_atom"] else f"ent:{r['src_entity']}",
             "dst": f"atm:{r['dst_atom']}" if r["dst_atom"] else f"ent:{r['dst_entity']}",
             "note": r["note"], "qualifiers": r["qualifiers"], "confidence": r["confidence"],
             "created_at": r["created_at"].isoformat(), "agent": r["agent"],
             "retired_at": r["retired_at"].isoformat() if r["retired_at"] else None} for r in rows]


def _codes(atoms: list[dict], entities: list[dict], links: list[dict]) -> set[tuple[str, str]]:
    """Коды словарей, которыми пользуются записи подборки: (scheme, code)."""
    codes: set[tuple[str, str]] = set()
    for row in atoms + entities:
        p = row["revision"]["payload"]
        codes.add(("kind", row["kind"]) if "kind" in row else ("entity_class", row["entity_class"]))
        for v in (p.get("content") or {}).get("values") or []:
            codes.add(("property", v["property"]))
        for q in p.get("qualifiers") or []:
            codes.add(("property", q["property"]))
        for s in p.get("sources") or []:
            for sel in s.get("selectors") or []:
                codes.add(("selector_type", sel["type"]))
    codes |= {("rel", link["rel"]) for link in links}
    return codes


def _packs_used(conn, codes: set[tuple[str, str]]) -> tuple[list[dict], list[dict]]:
    """Пакеты-владельцы кодов (concept.origin) с зависимостями по requires и понятия агентов (origin = agent).
    Пакет mine (свои виды) тянет и владельцев кодов, на которые ссылаются его шаблоны.

    Версия пакета — последняя загруженная: старые версии остаются в pack навсегда."""
    def owners(codes):
        schemes, values = [c[0] for c in sorted(codes)], [c[1] for c in sorted(codes)]
        return conn.execute("SELECT c.origin, c.data FROM concept c JOIN unnest(%s::text[], %s::text[]) "
                            "AS u(scheme, code) ON c.scheme = u.scheme AND c.code = u.code ORDER BY c.scheme, c.code",
                            (schemes, values)).fetchall()

    rows = owners(codes)
    if any(origin == mine.NAME for origin, _ in rows):
        # пакет mine едет целиком: коды, на которые ссылаются его шаблоны (классы, величины), — тоже
        rows = owners(codes | mine.refs(conn))
    agent_concepts = [data for origin, data in rows if origin == "agent"]
    names = {origin for origin, _ in rows if origin not in ("schema", "agent")} | {"core"}
    found: dict[str, dict] = {}
    while names - set(found):
        for name, version, digest, requires in conn.execute(
                "SELECT DISTINCT ON (name) name, version, digest, requires FROM pack WHERE name = ANY(%s) "
                "ORDER BY name, loaded_at DESC, version DESC", (sorted(names - set(found)),)):
            found[name] = {"name": name, "version": version, "digest": digest, "requires": requires or {}}
        missing = names - set(found)
        if missing:
            raise BundleError(f"пакеты {sorted(missing)} не загружены в базу — выполните prepare")
        names |= {dep for p in found.values() for dep in p["requires"]}
    if mine.NAME in found:              # версия mine — наибольшая по номеру, а не по часам загрузки (как у as_pack)
        found[mine.NAME] = mine.pack_row(conn)
    return [found[n] for n in sorted(found)], agent_concepts


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=_json, sort_keys=True) + "\n")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _copy_files(store, objects: list[dict], dst: Path) -> None:
    """Файлы версий объектов из хранилища — по digest; копия сверяется с digest базы."""
    dst.mkdir(parents=True)
    for o in objects:
        if o["kind"] != "file":
            continue
        for v in o["versions"]:
            hexdigest = v["digest"].split(":", 1)[1]
            target = dst / hexdigest
            if target.exists():
                continue
            try:
                shutil.copyfile(store.content(o["id"], v["n"]), target)
            except (StoreError, OSError) as e:
                raise BundleError(f"obj:{o['id']} версия {v['n']}: файл не скопирован из хранилища: "
                                  f"{_reason(e)}") from e
            if _sha256(target) != hexdigest:
                raise BundleError(f"obj:{o['id']} версия {v['n']}: копия в хранилище не совпадает с digest базы")


def _copy_packs(conn, pack_rows: list[dict], dst: Path) -> None:
    """Копии папок пакетов (packs.discover); digest папки обязан совпасть с базой. Копируются файлы, по которым
    считается digest (.yaml, .md), — у копии тот же digest. Пакет «Мои виды» (mine) живёт в базе: его папка
    собирается из базы (mine.write_pack) — понятия и действующие шаблоны своих видов."""
    by_name = {p.name: p for p in packs.load_packs()}
    for row in pack_rows:
        if row["name"] == mine.NAME:
            written = mine.write_pack(conn, dst / mine.NAME)
            if written.version != row["version"]:
                raise BundleError(f"пакет {mine.NAME}: версия сменилась во время экспорта ({row['version']} → "
                                  f"{written.version}) — повторите экспорт")
            continue
        loaded = by_name.get(row["name"])
        if loaded is None or loaded.version != row["version"] or loaded.digest != row["digest"]:
            raise BundleError(f"digest пакета {row['name']} {row['version']} в базе не совпадает с папкой пакета "
                              f"(или пакета нет в AMEMO_PACKS) — обновите базу (prepare)")
        for file in sorted(p for p in loaded.path.rglob("*") if p.is_file() and p.suffix in (".yaml", ".md")):
            target = dst / row["name"] / file.relative_to(loaded.path)
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(file, target)
            except OSError as e:
                raise BundleError(f"пакет {row['name']}: {file.name} не скопирован: {_reason(e)}") from e


def _files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def _zip(work: Path, out: Path) -> None:
    """Zip той же структуры: файлы объектов без сжатия (они и так сжаты или большие), манифест — последним."""
    names = [n for n in _files(work) if n != "manifest.json"] + ["manifest.json"]
    with zipfile.ZipFile(out, "w") as z:
        for name in names:
            stored = name.startswith("objects/")
            z.write(work / name, name, compress_type=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)


def export(conn: psycopg.Connection, *, store, folder: Path, selection: Selection, agent: str,
           with_files: bool = False, with_history: bool = False, with_packs: bool = False) -> dict:
    """Записать подборку в папку folder (или zip, если имя кончается на .zip) и вернуть манифест.

    Подборка собирается во временной папке рядом и появляется под своим именем только целиком: при ошибке
    ничего не остаётся. with_files — файлы версий из store (обязателен); with_history — все ревизии записей;
    with_packs — копии пакетов, digest которых совпал с базой."""
    folder = Path(folder)
    if folder.exists():
        raise BundleError(f"{folder.name}: уже есть — подборка пишется в новое место")
    if with_files and store is None:
        raise BundleError("with_files: нужно хранилище объектов (store)")
    as_zip = folder.suffix == ".zip"
    folder.parent.mkdir(parents=True, exist_ok=True)
    work = folder.parent / f".{folder.name}.{uuid7()}.part"
    work.mkdir()
    try:
        atom_ids, entity_ids = _select(conn, selection)
        atoms, entities = _closure(conn, selection, _current(conn, "atom", atom_ids), entity_ids)
        if selection.project:
            # сущности проекта видны вместе с тем, во что они входят (датчик → стойка)
            more = _containers(conn, set(entities), list(selection.statuses)) - set(entities)
            if more:
                atoms, entities = _closure(conn, selection, atoms, set(entities) | more)
        atom_rows = _record_rows(conn, "atom", atoms, with_history)
        entity_rows = _record_rows(conn, "entity", entities, with_history)
        link_rows = _links(conn, set(atoms) | set(entities))
        source_rows, object_ids = [], set()
        for target, rows in (("atom", atom_rows), ("entity", entity_rows)):
            found = lookup.revisions_sources(conn, target, [r["revision"]["id"] for r in rows])
            for row in rows:
                for s in found[uuid.UUID(row["revision"]["id"])]:
                    source_rows.append({"revision_id": row["revision"]["id"], "target": target, **s})
                    object_ids.add(_ref_uuid(s["object"]))
        object_rows = [{**lookup.get_object(conn, o), "status": lookup.object_status(conn, o)}
                       for o in sorted(object_ids)]
        pack_rows, concept_rows = _packs_used(conn, _codes(atom_rows, entity_rows, link_rows))
        base_id = conn.execute("SELECT value FROM meta WHERE key = 'base_id'").fetchone()
        if base_id is None:
            raise BundleError("у базы нет base_id — выполните prepare")
        for name, rows in zip(PARTS, (entity_rows, atom_rows, link_rows, object_rows, source_rows, concept_rows)):
            _write_jsonl(work / name, rows)
        if with_files:
            _copy_files(store, object_rows, work / "objects" / "sha256")
        if with_packs:
            _copy_packs(conn, pack_rows, work / "packs")
        manifest = {"format": FORMAT, "created_at": datetime.now(timezone.utc).isoformat(), "base_id": base_id[0],
                    "agent": agent, "amem_version": __version__, "selection": selection.as_json(),
                    "packs": pack_rows,
                    "counts": {"atoms": len(atom_rows), "entities": len(entity_rows), "links": len(link_rows),
                               "objects": len(object_rows), "sources": len(source_rows),
                               "concepts": len(concept_rows)},
                    "parts": {name: _sha256(work / name) for name in _files(work)},
                    "with_files": with_files, "with_history": with_history, "with_packs": with_packs}
        try:
            model_v1.BundleManifest.model_validate(manifest)
        except ValidationError as e:
            raise BundleError(f"манифест подборки не прошёл схему: {e}") from e
        # манифест — последним: подборка без него не считается записанной
        (work / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        if as_zip:
            part = work.with_name(work.name + ".zip")
            try:
                _zip(work, part)
                os.replace(part, folder)
            finally:
                part.unlink(missing_ok=True)
        else:
            work.rename(folder)
    finally:
        if work.exists():
            shutil.rmtree(work)
    return manifest


@contextlib.contextmanager
def opened(path: Path, *, tmp_dir: Path | None = None):
    """Корень подборки: папка как есть, zip — распакованный во временную папку в tmp_dir (по умолчанию —
    системная временная), удаляется на выходе."""
    path = Path(path)
    if path.suffix != ".zip":
        yield path
        return
    with tempfile.TemporaryDirectory(prefix="amemo-bundle-", dir=tmp_dir) as tmp:
        _extract(path, Path(tmp))
        yield Path(tmp)


def _extract(path: Path, dest: Path) -> None:
    try:
        with zipfile.ZipFile(path) as z:
            _check_zip(path, z.infolist())        # до распаковки: ни байта на диск из вредного архива
            z.extractall(dest)
    except (OSError, zipfile.BadZipFile) as e:
        raise BundleError(f"{path.name}: не читается как zip: {_reason(e)}") from e


def unpack(path: Path, dest: Path) -> Path:
    """Распаковать zip подборки в новую папку dest (с теми же проверками архива, что у opened) и вернуть её:
    так служба распаковывает загрузку один раз — для inspect и import_. Отказ — BundleError, dest не остаётся."""
    dest = Path(dest)
    dest.mkdir()
    try:
        _extract(Path(path), dest)
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return dest


def _check_zip(path: Path, members: list[zipfile.ZipInfo]) -> None:
    """Имена, ссылки и размеры записей архива: вредное — BundleError, не полагаясь на чистку extractall."""
    if len(members) > MAX_MEMBERS:
        raise BundleError(f"{path.name}: {len(members)} записей в архиве — больше предела {MAX_MEMBERS}")
    total = 0
    for m in members:
        name = m.filename
        parts = PurePosixPath(name).parts
        if (not name or "\\" in name or "\0" in name or name.startswith("/") or ".." in parts
                or (len(name) > 1 and name[1] == ":")):
            raise BundleError(f"{path.name}: недопустимое имя в архиве {name!r}")
        if (m.external_attr >> 16) & 0o170000 == 0o120000:
            raise BundleError(f"{path.name}: {name} — символическая ссылка, в подборке их не бывает")
        total += m.file_size
        if total > MAX_UNPACKED:
            raise BundleError(f"{path.name}: распакованный размер больше предела {MAX_UNPACKED} байт")
        if m.file_size > RATIO_FROM and m.file_size > MAX_RATIO * max(m.compress_size, 1):
            raise BundleError(f"{path.name}: {name} сжат больше {MAX_RATIO}:1 — похоже на zip-бомбу")


def _manifest(root: Path, label: Path) -> dict:
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise BundleError(f"{label.name}: нет manifest.json — это не подборка или она записана не до конца") from None
    except (OSError, ValueError) as e:
        raise BundleError(f"{label.name}/manifest.json: не читается: {_reason(e)}") from e
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        got = manifest.get("format") if isinstance(manifest, dict) else None
        raise BundleError(f"{label.name}: формат {got!r}, ожидается {FORMAT}")
    try:
        model_v1.BundleManifest.model_validate(manifest)
    except ValidationError as e:
        raise BundleError(f"{label.name}/manifest.json: {e}") from e
    if not isinstance(manifest["parts"], dict):
        raise BundleError(f"{label.name}/manifest.json: parts — не словарь")
    for name in manifest["parts"]:
        p = PurePosixPath(name)
        if not isinstance(name, str) or p.is_absolute() or ".." in p.parts or name == "manifest.json":
            raise BundleError(f"{label.name}/manifest.json: недопустимый путь части {name!r}")
    return manifest


def _damaged(root: Path, manifest: dict) -> list[str]:
    """Части, которых нет или чей sha256 не совпал с манифестом; файлы объектов сверяются и по имени (digest)."""
    out = {name for name in PARTS if name not in manifest["parts"]}     # обязательные части — всегда
    for name, digest in manifest["parts"].items():
        file = root / name
        if not file.is_file() or _sha256(file) != digest:
            out.add(name)
        elif name.startswith("objects/sha256/") and PurePosixPath(name).name != digest:
            out.add(name)
    return sorted(out)


def inspect(path: Path, *, tmp_dir: Path | None = None) -> dict:
    """Манифест и сверка частей без базы: манифест + ok, damaged (части с ошибкой), unexpected (файлы вне parts).
    zip распаковывается во временную папку в tmp_dir (opened).

    Неверный формат или манифест — BundleError; повреждённая часть — не исключение, а damaged."""
    path = Path(path)
    with opened(path, tmp_dir=tmp_dir) as root:
        manifest = _manifest(root, path)
        damaged = _damaged(root, manifest)
        unexpected = [n for n in _files(root) if n != "manifest.json" and n not in manifest["parts"]]
    return {**manifest, "ok": not damaged, "damaged": damaged, "unexpected": unexpected}


# --- импорт (разд. 4.3) ---

TRUST = ("keep", "review")
ORIGIN = ("origin_base", "origin_revision_hash", "origin_agent")       # поля provenance, которые пишет импорт
RETIRED = ("deprecated", "superseded")
TRUSTED = ("verified", "auto_verified")      # проверенное в чужой базе: сохраняется, только если вливает человек
CONCEPT_SCHEMES = ("property",)              # понятия агентов, которые импорт добавляет (величины, разд. 4.1)
SHAKY = ("fuzzy", "not_found", "unresolved", "no_text", "error")     # итоги своей сверки — предупреждение
UNCONFIRMED = ("fuzzy", "not_found", "no_file")   # своя сверка атома не подтвердила место — запись на проверку
_NAME = re.compile(r"@b\d+")
PACK_CONFLICT = "bundle_pack_conflict"   # свой вид подборки (packs/mine) с тем же кодом и другим содержимым
# коды отказа импорта без своего CheckCode: в отчёт amem.check/1 они не попадают, это коды BundleError.code
DAMAGED = "bundle_damaged"          # нет части или sha256 не совпал с манифестом
LEVEL1 = "bundle_level1"            # тела не прошли уровень 1 (details["report"] — отчёт amem.check/1)

SourceKey = tuple[str, int]                  # (obj:<UUID>, номер версии)


@dataclass
class Imported:
    """Ответ импорта: пакет изменений (None — ничего не записано: dry_run или всё совпало), счётчики по действиям
    (created, unchanged, pending, skipped; links — новые связи; objects — новые объекты), пункты очереди,
    предупреждения, коллизии ключей и id связей (только у dry_run: без него коллизия — отказ), отчёт уровня 1
    (amem.check/1; у dry_run — всегда, иначе при записи он без ошибок), complete — очередь пуста и отказа нет, и
    kinds — коды своих видов (пакет mine подборки), которых в базе не было: импорт их добавил (у dry_run — добавит);
    тогда же в counts есть kinds — их число."""
    changeset_id: uuid.UUID | None
    counts: dict[str, int]
    queued: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    collisions: list[str] = field(default_factory=list)
    report: dict | None = None
    complete: bool = True
    kinds: list[str] = field(default_factory=list)


@dataclass
class _Rec:
    """Запись подборки и решение о ней: действие, тело для записи (None — писать нечего), статус новой записи,
    причины пунктов очереди, итоги своей сверки (до транзакции записи: (position, verdict, page, anchor) и
    источники атома с итогом из UNCONFIRMED), ревизия после commit."""
    target: Target
    row: dict
    record_id: uuid.UUID
    action: str = ""
    body: dict | None = None
    status: str | None = None
    reasons: list[tuple[str, dict]] = field(default_factory=list)
    checks: list[tuple[int, str, int | None, str | None]] = field(default_factory=list)
    unconfirmed: list[dict] = field(default_factory=list)
    revision: records.Revision | None = None

    @property
    def ref(self) -> str:
        return f"{PREFIX[self.target]}:{self.record_id}"


def _read_jsonl(root: Path, name: str) -> list[dict]:
    rows = []
    for i, line in enumerate((root / name).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as e:
            raise BundleError(f"{name}: строка {i} — не JSON: {e}") from e
        if not isinstance(row, dict):
            raise BundleError(f"{name}: строка {i} — не объект JSON")
        rows.append(row)
    return rows


def _check_packs(conn, manifest: dict, root: Path, folder: Path) -> list[tuple]:
    """Пакеты подборки загружены с теми же name, version, digest; иначе — отказ со списком и подсказкой.

    Пакет «Мои виды» (mine) живёт в базе, а не в AMEMO_PACKS: с папкой packs/mine/ (with_packs) его виды
    сверяются с базой по содержимому, и ответ — эти виды (mine.read_pack) для _plan_mine; без папки он есть, если в
    базе была версия mine с тем же digest (та же база или те же свои виды)."""
    have = {(n, v): d for n, v, d in conn.execute("SELECT name, version, digest FROM pack")}
    latest = dict(conn.execute("SELECT DISTINCT ON (name) name, version FROM pack "
                               "ORDER BY name, loaded_at DESC, version DESC").fetchall())
    missing, names = [], []
    kinds: list[tuple] = []
    for p in manifest["packs"]:
        if not isinstance(p, dict):
            raise BundleError(f"{folder.name}/manifest.json: пакет {p!r} — не объект")
        name, version, digest = p.get("name"), p.get("version"), p.get("digest")
        got = have.get((name, version))
        if got is not None and got == digest:
            continue
        if name == mine.NAME:
            if (root / "packs" / mine.NAME / "pack.yaml").is_file():
                try:
                    kinds = mine.read_pack(root / "packs" / mine.NAME)
                except mine.MineError as e:
                    raise BundleError(f"{folder.name}: {e}") from e
                continue
            if digest in {d for (n, _), d in have.items() if n == mine.NAME}:
                continue
            missing.append(f"{name} {version} (свои виды базы-источника: экспортируйте подборку с пакетами — "
                           f"with_packs)")
            continue
        why = ("загружен с другим digest" if got is not None else
               f"загружена версия {latest[name]}" if name in latest else "не загружен")
        missing.append(f"{name} {version} ({why})")
        names.append(name)
    if not missing:
        return kinds
    bundled = [n for n in names if isinstance(n, str) and (root / "packs" / n / "pack.yaml").is_file()]
    if not names:                                        # недостаёт только своих видов: AMEMO_PACKS не поможет
        raise BundleError("не загружены пакеты подборки: " + "; ".join(missing), code="bundle_pack_missing",
                          missing=missing)
    if bundled and folder.suffix == ".zip":
        hint = "; пакеты лежат в подборке (packs/): распакуйте её, добавьте их папки в AMEMO_PACKS и выполните prepare"
    elif bundled:
        hint = (f"; пакеты лежат в подборке {folder.name}: добавьте в AMEMO_PACKS её папки "
                f"{', '.join('packs/' + n for n in bundled)} и выполните prepare")
    else:
        hint = "; добавьте папки пакетов в AMEMO_PACKS и выполните prepare"
    raise BundleError("не загружены пакеты подборки: " + "; ".join(missing) + hint, code="bundle_pack_missing",
                      missing=missing)


def _check_hash(payload, content_hash, where: str) -> None:
    """Хэш тела совпадает с content_hash ревизии: иначе подборка повреждена или изменена после экспорта."""
    if not isinstance(payload, dict) or not isinstance(content_hash, str):
        raise BundleError(f"{where}: ревизия без тела или хэша")
    try:
        same = canon.content_hash(payload) == content_hash
    except canon.CanonError as e:
        raise BundleError(f"{where}: тело ревизии не приводится к канонической форме: {e}") from e
    if not same:
        raise BundleError(f"{where}: content_hash не совпадает с телом ревизии — подборка повреждена или "
                          "изменена после экспорта")


def _check_row(target: Target, row: dict, part: str) -> uuid.UUID:
    """Строка записи подборки: id, статус, ревизия с телом; хэши текущей ревизии и ревизий истории сходятся."""
    try:
        record_id = uuid.UUID(row["id"])
        rev = row["revision"]
        if not isinstance(rev["id"], str):
            raise TypeError("ревизия без id")
        history = row.get("history") or []
        if not isinstance(history, list) or not all(isinstance(h, dict) for h in history):
            raise TypeError("history — не список ревизий")
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise BundleError(f"{part}: запись {row.get('id')!r} — неполная строка ({e})") from e
    ref = f"{PREFIX[target]}:{record_id}"
    if row.get("status") not in STATUSES:
        raise BundleError(f"{part}: {ref}: статус {row.get('status')!r} — не из перечня")
    _check_hash(rev.get("payload"), rev.get("content_hash"), f"{part}: {ref}")
    for h in history:
        _check_hash(h.get("payload"), h.get("content_hash"), f"{part}: {ref}: история, ревизия {h.get('n')}")
    return record_id


def _swap(value, mapping: dict[str, str]):
    """Тело с заменой ссылок-строк по mapping (atm:/ent:<UUID> → @имя)."""
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        return [_swap(v, mapping) for v in value]
    if isinstance(value, dict):
        return {k: _swap(v, mapping) for k, v in value.items()}
    return value


def _map_sources(payload: dict, vmap: dict[SourceKey, SourceKey]) -> dict:
    """Тело, где источники на сопоставленные объекты подборки ведут на локальные объект и версию."""
    if not vmap or not payload.get("sources"):
        return payload
    out = []
    for s in payload["sources"]:
        to = vmap.get((s.get("object"), s.get("object_version"))) if isinstance(s, dict) else None
        out.append({**s, "object": to[0], "object_version": to[1]} if to else s)
    return {**payload, "sources": out}


def _without_origin(payload: dict) -> dict:
    """Тело без полей происхождения, которые дописывает импорт: то же содержание, что в базе-источнике."""
    provenance = {k: v for k, v in (payload.get("provenance") or {}).items() if k not in ORIGIN}
    body = {k: v for k, v in payload.items() if k != "provenance"}
    return {**body, "provenance": provenance} if provenance else body


def _referenced(recs: list["_Rec"]) -> set[SourceKey]:
    """Версии объектов, на которые ссылаются источники записей подборки."""
    out = set()
    for r in recs:
        for s in r.row["revision"]["payload"].get("sources") or []:
            if isinstance(s, dict) and isinstance(s.get("object"), str) and isinstance(s.get("object_version"), int):
                out.add((s["object"], s["object_version"]))
    return out


def _local_versions(conn, o: dict) -> dict[int, tuple[uuid.UUID, int]]:
    """Версии объекта подборки, которые база знает под другим id: файл — по digest версии; страница сайта
    и переписка — объект с тем же адресом или названием, версия с тем же номером."""
    kind = o.get("kind")
    versions = [v for v in o.get("versions") or [] if isinstance(v, dict) and isinstance(v.get("n"), int)]
    found: dict[int, tuple[uuid.UUID, int]] = {}
    if kind == "file":
        for v in versions:
            if isinstance(v.get("digest"), str):
                row = conn.execute("SELECT object_id, n FROM object_version WHERE digest = %s",
                                   (v["digest"],)).fetchone()
                if row is not None:
                    found[v["n"]] = (row[0], row[1])
        return found
    column = {"web": "url", "message": "original_name"}.get(kind)
    value = o.get(column) if column else None
    if not isinstance(value, str) or not value.strip():
        return found
    row = conn.execute(f"SELECT id FROM object WHERE kind = %s AND {column} = normalize(%s, NFC)",
                       (kind, value.strip())).fetchone()
    if row is not None:
        have = {n for (n,) in conn.execute("SELECT n FROM object_version WHERE object_id = %s", (row[0],))}
        found = {v["n"]: (row[0], v["n"]) for v in versions if v["n"] in have}
    return found


def _known(conn, store, object_id: uuid.UUID, o: dict, files: dict[str, Path]) -> bool:
    """Объект базы, которому подборка ничего не добавляет: все версии есть с тем же digest, все пути записаны,
    копии файлов подборки уже в хранилище. Его adopt не нужен: повтор той же подборки не берёт исключительную
    блокировку объектов вовсе."""
    have = dict(conn.execute("SELECT n, digest FROM object_version WHERE object_id = %s", (object_id,)).fetchall())
    versions = o.get("versions") or []
    if not all(isinstance(v, dict) and v.get("n") in have and have[v["n"]] == v.get("digest") for v in versions):
        return False                    # новая версия или расхождение digest — решает adopt (с отказом при расхождении)
    paths = sorted({unicodedata.normalize("NFC", p) for p in o.get("logical_paths") or [] if isinstance(p, str)})
    if paths and conn.execute("SELECT count(*) FROM object_path WHERE path = ANY(%s)",
                              (paths,)).fetchone()[0] < len(paths):
        return False
    with_copy = [v["n"] for v in versions if o.get("kind") == "file" and v.get("digest") in files]
    return not with_copy or store.head(object_id) >= max(with_copy)


def _plan_objects(conn, store, rows: list[dict], referenced: set[SourceKey], files: dict[str, Path],
                  warnings: list[str]) -> tuple[list[dict], dict[SourceKey, SourceKey], int]:
    """Объекты подборки: что принимать (adopt), какие источники перевести на локальные объекты и сколько новых.
    Известный объект без новых версий, путей и копий не принимается заново (_known).

    Объект, известный базе под другим id (тот же файл по digest, тот же адрес сайта или название переписки), — тот же
    источник: ссылки на него переводятся на локальный (предупреждение), иначе уникальные индексы отвергли бы его.
    Совпадение частичное — не все версии, на которые ссылаются источники, найдены, или они ведут на разные
    локальные объекты — отказ bundle_object_conflict: молча принять второй экземпляр документа нельзя."""
    adopt, vmap, new = [], {}, 0
    for o in rows:
        try:
            object_id = objects.object_uuid(o.get("id", ""))
        except ValueError as e:
            raise BundleError(f"objects.jsonl: объект {o.get('id')!r}: {e}") from e
        ref = f"obj:{object_id}"
        record = {k: v for k, v in o.items() if k != "status"}
        if conn.execute("SELECT 1 FROM object WHERE id = %s", (object_id,)).fetchone() is not None:
            if not _known(conn, store, object_id, o, files):
                adopt.append(record)
            continue
        found = _local_versions(conn, o)
        if not found:
            adopt.append(record)
            new += 1
            continue
        targets = sorted({oid for oid, _ in found.values()})
        lost = sorted(n for r, n in referenced if r == ref and n not in found)
        if len(targets) > 1 or lost:
            why = (f"версии ведут на разные локальные объекты {', '.join(f'obj:{t}' for t in targets)}"
                   if len(targets) > 1 else f"нет локальных версий {lost}, на которые ссылаются источники")
            raise BundleError(f"{ref}: объект подборки совпал с базой лишь частично — {why}",
                              code="bundle_object_conflict", object=ref, local=[f"obj:{t}" for t in targets], lost=lost)
        for n, (oid, m) in found.items():
            vmap[(ref, n)] = (f"obj:{oid}", m)
        what = o.get("url") or o.get("original_name") or ""
        others = sorted(n for n in (v.get("n") for v in o.get("versions") or [] if isinstance(v, dict))
                        if n not in found)
        warnings.append(f"{ref}: {o.get('kind')} {what!r} уже есть в базе как obj:{targets[0]} — источники подборки "
                        "ссылаются на него" + (f"; версии {others}, на которые источники не ссылаются и которых в "
                                               "базе нет, не переносятся" if others else ""))
    return adopt, vmap, new


def _plan_record(conn, rec: _Rec, vmap: dict[SourceKey, SourceKey], *, origin_base: str, own_base: str,
                 trust: str, person: bool, warnings: list[str], collisions: list[str]) -> None:
    """Действие для записи (разд. 4.3, шаг 6): created / unchanged / pending / skipped — тело, статус и пункты.

    Совпадением считается любая локальная ревизия записи (текущая, ждущая, отклонённая, старая), чей content_hash
    или provenance.origin_revision_hash равен хэшу тела подборки или того же тела без полей происхождения (и с
    источниками на локальные объекты): это содержание база уже видела, и повтор подборки ничего не меняет — даже
    если о нём уже решили (отклонили или ушли дальше). origin_revision_hash — хэш тела подборки как есть."""
    t, rev = rec.target, rec.row["revision"]
    raw, incoming_hash = rev["payload"], rev["content_hash"]
    incoming = _map_sources(raw, vmap)
    try:
        keys = {incoming_hash, canon.content_hash(_without_origin(raw)), canon.content_hash(_without_origin(incoming))}
    except canon.CanonError as e:
        raise BundleError(f"{rec.ref}: тело ревизии не приводится к канонической форме: {e}") from e
    key = rec.row.get("key")
    local = conn.execute(f"SELECT status, key FROM {t} WHERE id = %s", (rec.record_id,)).fetchone()
    if local is not None and local[1] and key and local[1] != key:
        collisions.append(f"{rec.ref}: локальный ключ {local[1]}, в подборке {key}")
    if key:
        owner = lookup.by_key(conn, t, key)
        if owner is not None and owner != rec.ref:
            collisions.append(f"{t} {key}: локально {owner}, в подборке {rec.ref}")
    body = dict(incoming)
    if t == "atom" and origin_base != own_base:          # provenance — только у атома (схема сущности его не знает)
        body["provenance"] = {**(incoming.get("provenance") or {}), "origin_base": origin_base,
                              "origin_revision_hash": incoming_hash, "origin_agent": rev.get("agent")}
        body["provenance"] = {k: v for k, v in body["provenance"].items() if v is not None}
    details = {"origin_base": origin_base, "origin_status": rec.row["status"]}
    if local is None:
        rec.action, rec.body = "created", body
        rec.status, reasons, why = _created_status(rec.row, trust, person)
        rec.reasons = [(w, {**details, "action": "created", **({"why": why} if why else {})}) for w in reasons]
        return
    if local[0] in RETIRED:
        rec.action = "skipped"
        warnings.append(f"{rec.ref}: локально {local[0]} — подборка её не меняет: вывод из оборота решается здесь")
        return
    if keys & _local_keys(conn, t, rec.record_id):
        rec.action = "unchanged"
        return
    rec.action, rec.body = "pending", body
    rec.reasons = [("imported", {**details, "action": "pending"})]


def _local_keys(conn, target: Target, record_id: uuid.UUID) -> set[str]:
    """Чем база узнаёт уже виденное содержание записи: у каждой её ревизии — content_hash,
    provenance.origin_revision_hash и хэш тела без полей происхождения (сравнение без них — с обеих сторон: обмен
    A → B → A → B без правок не зависит от того, чьи поля происхождения сейчас в теле)."""
    out: set[str] = set()
    for content_hash, origin_hash, payload in conn.execute(
            f"SELECT content_hash, payload->'provenance'->>'origin_revision_hash', "
            f"CASE WHEN payload ? 'provenance' THEN payload END FROM {target}_revision WHERE {target}_id = %s",
            (record_id,)).fetchall():
        out |= {content_hash, *([origin_hash] if origin_hash else [])}
        if payload is not None:
            out.add(canon.content_hash(_without_origin(payload)))
    return out


def _created_status(row: dict, trust: str, person: bool) -> tuple[str, list[str], list[str]]:
    """Статус новой записи, причины пунктов и почему она на проверке (шаг 7).

    trust=review — needs_review и imported. trust=keep — статус подборки, но модель (не person:) не обходит
    политику записей человека и проверки: запись проверенная или решённая в чужой базе (verified, auto_verified,
    rejected, deprecated, superseded), с basis author или написанная человеком (агент ревизии или
    provenance.origin_agent — person:) — needs_review и imported, а не черновик с проверкой смысла моделью.
    Иначе черновик ждёт проверки смысла (semantic), needs_review — пункта imported, как после submit."""
    status, rev = row["status"], row["revision"]
    payload = rev["payload"]
    why = ["trust=review"] if trust == "review" else []
    if not person:
        if status in (*TRUSTED, "rejected", *RETIRED):
            why.append(f"origin_status {status}")
        if payload.get("basis") == "author":
            why.append("basis author")
        for who in dict.fromkeys([rev.get("agent"), (payload.get("provenance") or {}).get("origin_agent")]):
            if isinstance(who, str) and who.startswith("person:"):
                why.append(f"origin_agent {who}")
    if why:
        return "needs_review", ["imported"], why
    if status == "draft":
        return status, ["semantic"], []
    if status == "needs_review":
        return status, ["imported"], []
    return status, [], []


def _link_ends(conn, link: dict) -> tuple[str, uuid.UUID, uuid.UUID, bool]:
    try:
        rel, src, dst = link["rel"], _ref_uuid(link["src"]), _ref_uuid(link["dst"])
        uuid.UUID(link["id"])
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as e:
        raise BundleError(f"links.jsonl: связь {link.get('id')!r} — неполная строка ({e})") from e
    data = conn.execute("SELECT data FROM concept WHERE scheme = 'rel' AND code = %s", (rel,)).fetchone()
    return rel, src, dst, bool(data and data[0].get("symmetric"))


def _plan_links(conn, rows: list[dict], warnings: list[str],
                collisions: list[str]) -> tuple[list[dict], list[uuid.UUID]]:
    """Связи (шаг 8): какие создать (тело с id подборки) и какие действующие локальные вывести из оборота.

    Своя связь ищется по id — и тогда обязана совпасть по rel и концам (у симметричной — в любую сторону), иначе
    коллизия bundle_key_collision: id занят другой связью. Выведенная в подборке и действующая локально —
    выводится, только если это та же связь (id, rel, концы): связь с теми же rel и концами под другим id — чужая
    локальная запись, и подборка её не выводит (предупреждение). Новая связь не создаётся, если действующая с теми
    же rel и концами уже есть; выведенная локально остаётся выведенной."""
    create, retire = [], []
    for link in rows:
        rel, src, dst, symmetric = _link_ends(conn, link)
        retired = link.get("retired_at") is not None
        ends = [(src, dst)] + ([(dst, src)] if symmetric else [])
        where = f"связь {rel} {link['src']} → {link['dst']}"
        row = conn.execute("SELECT id, retired_at, rel, coalesce(src_atom, src_entity), coalesce(dst_atom, dst_entity) "
                           "FROM link WHERE id = %s", (link["id"],)).fetchone()
        if row is not None and (row[2] != rel or (row[3], row[4]) not in ends):
            collisions.append(f"связь {link['id']}: локально {row[2]} {row[3]} → {row[4]}, в подборке {rel} "
                              f"{src} → {dst}")
            continue
        mine = row[:2] if row is not None else None
        if mine is None:
            same = [r for a, b in ends for r in conn.execute(
                "SELECT id, retired_at FROM link WHERE rel = %s AND coalesce(src_atom, src_entity) = %s "
                "AND coalesce(dst_atom, dst_entity) = %s ORDER BY retired_at NULLS FIRST", (rel, a, b)).fetchall()]
            active = [r for r in same if r[1] is None]
            other = active[0] if active else same[0] if same else None
            if other is not None and retired and other[1] is None:
                warnings.append(f"{where}: в подборке выведена, но локальная связь с теми же rel и концами — под "
                                f"другим id ({other[0]}): не выводится")
                continue
            mine = other
        if mine is None:
            if not retired:
                create.append({"id": link["id"], **{k: link[k] for k in ("rel", "src", "dst", "note", "qualifiers",
                                                                         "confidence") if link.get(k) is not None}})
        elif retired and mine[1] is None:
            retire.append(mine[0])
        elif not retired and mine[1] is not None:
            warnings.append(f"{where}: локально выведена из оборота — остаётся выведенной")
    return create, retire


def _level1(conn, recs: list[_Rec], links: list[dict]):
    """Уровень 1 над телами, которые будут записаны: новые записи — под @именами (их ещё нет в базе), правки —
    по record_id. Правила о том, кто пишет (basis author, confidence), не применяются: их проверила база-источник,
    автор — в provenance.origin_agent. Ответ — отчёт и @имя → ссылка, чтобы назвать запись в отказе."""
    from .check import Proposal, level1
    from .check.report import Report

    names = {r.ref: f"@b{i}" for i, r in enumerate(recs) if r.action == "created"}
    proposals = []
    for r in recs:
        if r.body is None:
            continue
        payload = _swap(r.body, names)
        if r.action == "created":
            proposals.append(Proposal(r.target, {**payload, "ref": names[r.ref]}))
        else:
            proposals.append(Proposal(r.target, payload, record_id=r.record_id))
    report = Report()
    level1.check(conn, proposals, [_swap({k: v for k, v in l.items() if k != "id"}, names) for l in links], report)
    return report, {v: k for k, v in names.items()}


def _report_json(report, names: dict[str, str]) -> dict:
    """Отчёт amem.check/1 уровня 1 с местами по ссылкам записей подборки вместо временных @имён."""
    body = report.as_json(levels={"1": "done"}, records=[], templates=[], degraded=[])
    for issue in body["issues"]:
        issue["where"] = _NAME.sub(lambda m: names.get(m[0], m[0]), issue["where"])
    return body


def _history_rows(conn, recs: list[_Rec], origin_base: str) -> list[tuple]:
    """Ревизии подборки с историей — для import_history: история и текущая, каких там ещё нет (хэши сверены)."""
    out = []
    for r in recs:
        have = {n for (n,) in conn.execute("SELECT n FROM import_history WHERE origin_base = %s AND record_id = %s",
                                           (origin_base, r.record_id))}
        for h in [*(r.row.get("history") or []), r.row["revision"]]:
            if h.get("n") in have:
                continue
            try:
                out.append((r.target, r.record_id, int(h["n"]), h["content_hash"], h["payload"], h["recorded_at"],
                            h.get("agent")))
            except (KeyError, TypeError, ValueError) as e:
                raise BundleError(f"{r.ref}: ревизия истории — неполная строка ({e})") from e
            have.add(h["n"])
    return out


def _own_check(conn, store, rec: _Rec) -> None:
    """Своя сверка источников тела, которое будет записано (шаг 9), — не верой подборке: файл с копией версии в
    хранилище сверяется уровнем 2 (level2.judge_source: место и цитата по тексту копии); файл без копии — no_file,
    пока файл не придёт; страница сайта и переписка — external. Итоги sources.jsonl не переносятся: чужой вердикт —
    утверждение, которое здесь не проверено. Считается до транзакции записи и без блокировки объектов (извлечение
    текста бывает долгим) — по копиям, уже принятым adopt; итоги — в rec.checks и rec.unconfirmed."""
    from .check import level2
    from .check.report import Report

    t = rec.target
    rec.checks, rec.unconfirmed = [], []
    for position, src in enumerate(rec.body.get("sources") or []):
        try:
            object_id, n = _ref_uuid(src["object"]), src["object_version"]
            kind = conn.execute("SELECT kind FROM object WHERE id = %s", (object_id,)).fetchone()[0]
        except (KeyError, TypeError, ValueError, AttributeError, IndexError):
            continue                # источник без объекта или с чужим объектом: тело отвергнет records.commit
        if not isinstance(n, int):
            continue
        if kind == "file" and store.head(object_id) < n:
            verdict, page, anchor = "no_file", None, None
        else:
            got = level2.judge_source(conn, store, t, src, position, Report())
            verdict, page, anchor = got.verdict, got.page, got.anchor
        if verdict is None:
            continue                                      # не сверялся (источник сущности-документа, правило PDF)
        rec.checks.append((position, verdict, page, anchor))
        if t == "atom" and verdict in UNCONFIRMED:
            rec.unconfirmed.append({"position": position, "object": src["object"], "object_version": n,
                                    "verdict": verdict})


def _apply_checks(conn, rec: _Rec, at: datetime, warnings: list[str]) -> None:
    """Итоги своей сверки (_own_check) — в строки source созданной ревизии, в транзакции записи."""
    t = rec.target
    for position, verdict, page, anchor in rec.checks:
        if verdict in SHAKY or verdict == "no_file":
            warnings.append(f"{rec.ref}: sources[{position}]: своя сверка с файлом — {verdict}")
        conn.execute(f"UPDATE source SET verdict = %s, page = %s, anchor = %s, checked_at = %s "
                     f"WHERE {t}_revision_id = %s AND position = %s",
                     (verdict, page, anchor, at, rec.revision.revision_id, position))


def _unconfirmed(conn, rec: _Rec, verdicts: list[dict], *, agent: str, origin_base: str,
                 at: datetime) -> list[tuple[str, dict]]:
    """Атом, чьё место своя сверка не подтвердила (fuzzy, not_found, no_file), не остаётся проверенным или
    черновиком на проверку смысла: проверять смысл без подтверждённого места нельзя, а чужой проверке здесь
    подтверждения нет. Новая запись — needs_review с пунктом imported и итогами в details; у ждущей ревизии
    (pending) статус не трогается — итоги идут в details её пункта imported. Запись, выведенная из оборота или
    отвергнутая в базе-источнике, остаётся такой: вопроса к ней нет."""
    if rec.action == "created" and rec.status not in ("verified", "auto_verified", "draft", "needs_review"):
        return list(rec.reasons)
    if rec.action == "created" and rec.status != "needs_review":
        records.set_status_locked(conn, rec.target, rec.record_id, "needs_review", agent=agent,
                                  reason="import: своя сверка не подтвердила источник", at=at)
    details = {"origin_base": origin_base, "origin_status": rec.row["status"], "action": rec.action,
               "verdicts": verdicts}
    return [("imported", details), *((why, d) for why, d in rec.reasons if why not in ("imported", "semantic"))]


def _concept_problem(concept: dict) -> str | None:
    """Понятие величины из подборки — по схеме Concept и с единицей UCUM; ответ — что не так, или None."""
    from .check import units

    try:
        model_v1.Concept.model_validate_json(json.dumps(concept, ensure_ascii=False), strict=True)
    except ValidationError as e:
        return f"не по схеме Concept ({e.error_count()} ошибок: {e.errors()[0]['msg']})"
    unit = concept.get("unit")
    if unit is not None and not units.is_ucum(unit):
        return f"единица {unit!r} — не код UCUM"
    return None


def _stale_sources(conn, rec: _Rec) -> dict | None:
    """Источники созданной ревизии на не последнюю локальную версию объекта — details пункта source_changed."""
    rows = conn.execute(
        "SELECT s.object_id, array_agg(DISTINCT s.object_version ORDER BY s.object_version), latest.n FROM source s "
        "CROSS JOIN LATERAL (SELECT max(n) AS n FROM object_version v WHERE v.object_id = s.object_id) latest "
        f"WHERE s.{rec.target}_revision_id = %s AND s.object_version < latest.n "
        "GROUP BY s.object_id, latest.n ORDER BY s.object_id", (rec.revision.revision_id,)).fetchall()
    return review.source_changed_details(rows) if rows else None


def import_(conn: psycopg.Connection, store, folder: Path, *, agent: str, trust: str = "keep",
            dry_run: bool = False, tmp_dir: Path | None = None) -> Imported:
    """Влить подборку (папку или zip): id сохраняются, ничего не затирается (спецификация 3c, разд. 4.3).

    Порядок: манифест и sha256 частей → пакеты (bundle_pack_missing) → строки и хэши тел (и истории) → объекты
    (сопоставление с локальными, bundle_object_conflict) и план записей и связей, коллизии ключей и id связей
    (bundle_key_collision) → уровень 1 → объекты с новыми версиями, путями или файлами — каждый своей транзакцией
    objects.adopt (строки и копии файлов) → своя сверка источников по принятым копиям → одна транзакция записи:
    агент, разделяемая блокировка объектов, отметки объектов, понятия агентов (величины), записи и связи одним
    records.commit (keep_ids), итоги сверки, статусы и пункты очереди, вывод связей из оборота, import_history.
    Соединение — с autocommit=True (db.connect), иначе BundleError до любого чтения: приём объектов и запись идут
    своими транзакциями. Отказ до приёма объектов — BundleError (code и details), и в базе ничего не появилось.
    Отказ при приёме объекта (ObjectError, StoreError), в своей сверке (ObjectError, StoreError — например, копии
    версии нет в хранилище) или в транзакции записи — тоже BundleError: записей, связей и пакета изменений нет,
    а принятое до отказа своими транзакциями остаётся, как после ingest: объекты с копиями (копия файла —
    содержимое, а не утверждение), пункты source_changed, которые adopt поставил для новой версии известного
    объекта, кэш текста (object_text) и строка агента. Повторный импорт примет объекты как есть (adopt идемпотентен)
    и запишет остальное. Коды отказа: bundle_damaged (DAMAGED), bundle_pack_missing, bundle_pack_conflict
    (PACK_CONFLICT), bundle_object_conflict, bundle_key_collision, bundle_level1 (LEVEL1); ошибка самих данных строки
    (не JSON, неверный хэш тела) — без кода.

    Свои виды (пакет mine, подпроект 4, разд. 6a.3): с папкой packs/mine/ виды, которых в базе нет, добавляются в
    mine той же транзакцией записи, раньше записей (вливает только человек — иначе MineError(forbidden));
    уровень 1 видит их в пробной транзакции с откатом. Тот же код с другим содержимым или код пакета из файла —
    коллизия в collisions (у dry_run) или отказ bundle_pack_conflict; dry_run показывает добавляемые виды в kinds.

    Блокировка — как у submit и ingest (разд. 7.5 спецификации 3): исключительная блокировка объектов
    (OBJECTS_LOCK) берётся только на время приёма одного объекта — его строк и копий, как у objects.ingest; своя
    сверка (извлечение текста бывает долгим) идёт без неё. Транзакция записи держит разделяемую: submit её не ждёт,
    а ingest, adopt и backup.snapshot ждут только фиксации записи. Новая версия объекта, принятая параллельным
    ingest между приёмом объектов и записью, даёт ревизии со ссылкой на прежнюю версию пункт source_changed: под
    разделяемой блокировкой видна последняя версия. Импорт без нового в объектах (повтор той же подборки)
    исключительную блокировку не берёт — кроме объекта, у которого adopt пропустил копию (в хранилище нет копии
    предыдущей версии): он не известен целиком (_known) и принимается при каждом повторе, пока копии не придут.

    trust=keep — статус записи из подборки; модель (не person:) не сохраняет проверенное и решённое в чужой базе,
    basis author и записи человека — они needs_review с пунктом imported. review — все новые записи needs_review
    с пунктом imported. Расхождение с локальной записью — ревизия pending с пунктом imported, текущая не
    меняется. dry_run — план без записи: счётчики, предупреждения, коллизии (вместо отказа) и отчёт уровня 1.
    zip распаковывается во временную папку в tmp_dir (opened)."""
    if not conn.autocommit:
        raise BundleError("import_: нужно соединение с autocommit=True (db.connect): иначе приём объектов и запись "
                          "не фиксируются")
    if trust not in TRUST:
        raise BundleError(f"trust: {trust!r} — ожидается keep или review")
    folder = Path(folder)
    with opened(folder, tmp_dir=tmp_dir) as root:
        manifest = _manifest(root, folder)
        damaged = _damaged(root, manifest)
        if damaged:
            raise BundleError(f"{folder.name}: повреждены части подборки: {', '.join(damaged)}", code=DAMAGED,
                              damaged=damaged)
        kinds = _check_packs(conn, manifest, root, folder)
        own = conn.execute("SELECT value FROM meta WHERE key = 'base_id'").fetchone()
        if own is None:
            raise BundleError("у базы нет base_id — выполните prepare")
        own_base, origin_base = own[0], manifest["base_id"]
        recs = [_Rec(target, row, _check_row(target, row, part))
                for target, part in (("entity", "entities.jsonl"), ("atom", "atoms.jsonl"))
                for row in _read_jsonl(root, part)]
        link_rows, object_rows = _read_jsonl(root, "links.jsonl"), _read_jsonl(root, "objects.jsonl")
        concepts = _read_jsonl(root, "concepts.jsonl")
        files = {f"sha256:{PurePosixPath(n).name}": root / n for n in manifest["parts"]
                 if n.startswith("objects/sha256/")}
        warnings: list[str] = []
        new_kinds, pack_collisions = mine.compare(conn, kinds) if kinds else ([], [])
        kinds = [k for k in kinds if k[0].code in new_kinds]
        collisions: list[str] = list(pack_collisions)
        adopt, vmap, new_objects = _plan_objects(conn, store, object_rows, _referenced(recs), files, warnings)
        person = agent.startswith("person:")
        for rec in recs:
            _plan_record(conn, rec, vmap, origin_base=origin_base, own_base=own_base, trust=trust, person=person,
                         warnings=warnings, collisions=collisions)
        new_links, retire = _plan_links(conn, link_rows, warnings, collisions)
        counts = {a: sum(r.action == a for r in recs) for a in ("created", "unchanged", "pending", "skipped")}
        counts |= {"links": len(new_links), "objects": new_objects}
        if kinds or pack_collisions:
            counts["kinds"] = len(new_kinds)
        try:
            report, names = _level1_with_kinds(conn, recs, new_links, kinds, agent=agent)
        except BundleError as e:
            if not dry_run or e.code != PACK_CONFLICT:
                raise
            # пробный импорт: вид, который не проходит проверку пакета, — коллизия отчёта, а не отказ
            collisions.extend(e.details.get("collisions") or [str(e)])
            report, names = _level1(conn, recs, new_links)
        if dry_run:
            return Imported(None, counts, warnings=warnings, collisions=collisions, report=_report_json(report, names),
                            complete=not collisions and not report.has_violations(), kinds=new_kinds)
        if pack_collisions:
            raise BundleError("свои виды подборки расходятся с базой: " + "; ".join(pack_collisions),
                              code=PACK_CONFLICT, collisions=pack_collisions)
        if kinds and not person:
            raise mine.MineError(f"свои виды из подборки ({', '.join(new_kinds)}) добавляет только человек (person:), "
                                 f"а не {agent}", code="forbidden")
        if collisions:
            raise BundleError("коллизии ключей и id связей: " + "; ".join(collisions), code="bundle_key_collision",
                              collisions=collisions)
        if report.has_violations():
            text = _NAME.sub(lambda m: names.get(m[0], m[0]), report.summary())
            raise BundleError("подборка не прошла уровень 1:\n" + text, code=LEVEL1,
                              report=_report_json(report, names))
        # история — только у подборки with_history и только чужая: своя история и так в базе
        history = (_history_rows(conn, recs, origin_base) if manifest["with_history"] and origin_base != own_base
                   else [])
        # объекты — каждый своей транзакцией, до записи (как resolve_sources у submit): копия файла — содержимое,
        # а не утверждение, и исключительная блокировка объектов держится только на время одного объекта
        for record in adopt:
            try:
                warnings.extend(objects.adopt(conn, store, record, files=files, agent=agent))
            except (objects.ObjectError, StoreError) as e:
                raise BundleError(f"подборка не принята: {e}") from e
        for rec in recs:
            if rec.body is None:
                continue
            try:
                _own_check(conn, store, rec)
            except (objects.ObjectError, StoreError) as e:
                raise BundleError(f"подборка не записана: {rec.ref}: своя сверка источников не выполнена ({e}); "
                                  "принятые объекты остаются") from e
        try:
            with conn.transaction():
                if kinds:                                    # свои виды — до записей: записи их видов проверяются
                    _adopt_kinds(conn, kinds, agent=agent)
                cs, queued = _write(conn, recs, new_links, retire, object_rows, concepts, history, vmap, warnings,
                                    agent=agent, origin_base=origin_base,
                                    reason=f"import {origin_base} {manifest['created_at']}")
        except objects.ObjectError as e:                     # отметка объекта (objects.mark)
            raise BundleError(f"подборка не принята: {e}") from e
        except RecordError as e:
            # ключ, занятый между планом и записью (records ловит UniqueViolation ключа и называет его)
            taken = isinstance(e.__cause__, psycopg.errors.UniqueViolation)
            raise BundleError(f"подборка не записана: {e}", code="bundle_key_collision" if taken else None) from e
        except psycopg.errors.IntegrityError as e:            # ограничение таблицы, которое план не предвидел
            taken = isinstance(e, psycopg.errors.UniqueViolation)
            raise BundleError(f"подборка не записана: {e.diag.message_primary}",
                              code="bundle_key_collision" if taken else None) from e
    return Imported(cs, counts, queued=queued, warnings=warnings, report=_report_json(report, names),
                    complete=not queued, kinds=new_kinds)


class _Trial(Exception):
    """Откат пробной транзакции: свои виды подборки видны только уровню 1."""


def _adopt_kinds(conn, kinds: list[tuple], *, agent: str, dry_run: bool = False) -> None:
    """Свои виды подборки — в mine (mine.adopt); вид, который не встаёт в эту базу, — bundle_pack_conflict."""
    try:
        mine.adopt(conn, kinds, agent=agent, dry_run=dry_run)
    except mine.MineError as e:
        if e.code == "forbidden":
            raise
        raise BundleError(f"свои виды подборки не встают в базу: {e}", code=PACK_CONFLICT,
                          collisions=[str(e)]) from e


def _level1_with_kinds(conn, recs: list[_Rec], links: list[dict], kinds: list[tuple], *, agent: str):
    """Уровень 1 так, как будто новые свои виды подборки уже в mine: виды добавляются в транзакции, которую
    уровень 1 откатывает, — до записи (и у dry_run) в базе их нет."""
    if not kinds:
        return _level1(conn, recs, links)
    out = None
    try:
        with conn.transaction():
            _adopt_kinds(conn, kinds, agent=agent, dry_run=True)
            out = _level1(conn, recs, links)
            raise _Trial
    except _Trial:
        pass
    return out


def _write(conn, recs: list[_Rec], new_links: list[dict], retire: list[uuid.UUID], object_rows: list[dict],
           concepts: list[dict], history: list[tuple], vmap: dict[SourceKey, SourceKey], warnings: list[str], *,
           agent: str, origin_base: str, reason: str) -> tuple[uuid.UUID | None, list[dict]]:
    """Запись импорта в уже открытой транзакции (функции записи ниже становятся точками сохранения). Порядок
    блокировок — как у submit (разд. 7.5 спецификации 3, шаги 1–2): агент, разделяемая блокировка объектов, записи."""
    conn.execute("INSERT INTO agent (id) VALUES (%s) ON CONFLICT (id) DO NOTHING", (agent,))
    # новая версия объекта, принятая параллельным ingest после приёма объектов подборки, не теряет source_changed:
    # под этой блокировкой _stale_sources видит последнюю версию, и новой до фиксации не появится
    conn.execute("SELECT pg_advisory_xact_lock_shared(%s)", (objects.OBJECTS_LOCK,))
    mapped = {ref for ref, _ in vmap}
    for o in object_rows:
        mark = o.get("status")
        if not isinstance(mark, dict) or f"obj:{o.get('id')}" in mapped:
            continue
        local = lookup.object_status(conn, o["id"])
        if local is None:
            # отметку ставит тот, кто вливает: чужой агент в журнале этой базы не действовал; кто и когда — в note
            origin = f"из подборки: {mark.get('agent') or '?'}, {mark.get('changed_at') or '?'}"
            note = f"{mark['note']} ({origin})" if mark.get("note") else origin
            objects.mark(conn, o["id"], mark.get("status"), agent=agent, note=note)
        elif local["status"] != mark.get("status"):
            warnings.append(f"obj:{o['id']}: отметка {local['status']} локальная, в подборке {mark.get('status')} — "
                            "остаётся локальная")
    for c in concepts:
        scheme, code = c.get("scheme"), c.get("code")
        if not isinstance(scheme, str) or not isinstance(code, str):
            continue
        if scheme not in CONCEPT_SCHEMES:
            # виды, классы, связи — словари пакетов: подборка их не ставит, иначе обошла бы проверку пакетов
            warnings.append(f"понятие {scheme}.{code}: схема {scheme} не принимается из подборки — пропущено")
            continue
        problem = _concept_problem(c)
        if problem:
            warnings.append(f"понятие {scheme}.{code}: {problem} — пропущено")
            continue
        row = conn.execute("SELECT data FROM concept WHERE scheme = %s AND code = %s", (scheme, code)).fetchone()
        if row is None:
            conn.execute("INSERT INTO concept (scheme, code, data, origin, updated_at) VALUES (%s, %s, %s, 'agent', "
                         "now())", (scheme, code, Jsonb(c)))
        elif row[0] != c:
            warnings.append(f"понятие {scheme}.{code} отличается от локального — остаётся локальное")
    writing = [r for r in recs if r.body is not None]
    items = [records.Item(r.target, r.body, record_id=r.record_id, status=r.status if r.action == "created" else None,
                          review_state="none" if r.action == "created" else "pending") for r in writing]
    cs: uuid.UUID | None = None
    queued: list[dict] = []
    if items or new_links:
        done = records.commit(conn, items, new_links, agent=agent, reason=reason, keep_ids=True)
        cs = done.changeset_id
        for r, rev in zip(writing, done.revisions):
            r.revision = rev
    elif history:
        # записи и связи совпали, а истории ещё нет: строки import_history тоже ссылаются на пакет изменений
        cs = records.new_changeset(conn, agent=agent, reason=reason)
    at = conn.execute("SELECT created_at FROM changeset WHERE id = %s", (cs,)).fetchone()[0] if cs else None
    for r in writing:
        if not r.revision.created:
            continue
        _apply_checks(conn, r, at, warnings)
        reasons = (_unconfirmed(conn, r, r.unconfirmed, agent=agent, origin_base=origin_base, at=at)
                   if r.unconfirmed else list(r.reasons))
        stale = _stale_sources(conn, r)
        if stale:
            reasons.append(("source_changed", stale))
        for why, details in reasons:
            item = review.insert_item(conn, r.target, r.record_id, r.revision.revision_id, why, changeset_id=cs,
                                      details=details, agent=agent, at=at)
            if item is not None:
                queued.append({**item, "ref": r.ref})
    for link_id in retire:
        records.retire_link(conn, link_id, agent=agent, reason="импорт: связь выведена из оборота в базе-источнике")
    for target, record_id, n, content_hash, payload, recorded_at, by in history:
        conn.execute("INSERT INTO import_history (id, changeset_id, target, record_id, origin_base, n, content_hash, "
                     "payload, recorded_at, agent) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                     "ON CONFLICT (origin_base, record_id, n) DO NOTHING",
                     (uuid7(), cs, target, record_id, origin_base, n, content_hash, Jsonb(payload),
                      recorded_at, by))
    return cs, queued
