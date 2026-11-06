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
import uuid
import zipfile
from dataclasses import dataclass, field, fields
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from . import __version__, canon, lookup, model_v1, objects, packs, records, review
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
        super().__init__(message)
        self.code, self.details = code, details


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
        where = [f"rec.status = ANY(%(statuses)s)", *own]
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

    Версия пакета — последняя загруженная: старые версии остаются в pack навсегда."""
    schemes, values = [c[0] for c in sorted(codes)], [c[1] for c in sorted(codes)]
    rows = conn.execute("SELECT c.origin, c.data FROM concept c JOIN unnest(%s::text[], %s::text[]) AS u(scheme, code) "
                        "ON c.scheme = u.scheme AND c.code = u.code ORDER BY c.scheme, c.code",
                        (schemes, values)).fetchall()
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
                raise BundleError(f"obj:{o['id']} версия {v['n']}: файл не скопирован из хранилища: {e}") from e
            if _sha256(target) != hexdigest:
                raise BundleError(f"obj:{o['id']} версия {v['n']}: копия в хранилище не совпадает с digest базы")


def _copy_packs(pack_rows: list[dict], dst: Path) -> None:
    """Копии папок пакетов (packs.discover); digest папки обязан совпасть с базой. Копируются файлы, по которым
    считается digest (.yaml, .md), — у копии тот же digest."""
    by_name = {p.name: p for p in packs.load_packs()}
    for row in pack_rows:
        loaded = by_name.get(row["name"])
        if loaded is None or loaded.version != row["version"] or loaded.digest != row["digest"]:
            raise BundleError(f"digest пакета {row['name']} {row['version']} в базе не совпадает с папкой пакета "
                              f"(или пакета нет в AMEM_PACKS) — обновите базу (prepare)")
        for file in sorted(p for p in loaded.path.rglob("*") if p.is_file() and p.suffix in (".yaml", ".md")):
            target = dst / row["name"] / file.relative_to(loaded.path)
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(file, target)
            except OSError as e:
                raise BundleError(f"пакет {row['name']}: {file.name} не скопирован: {e}") from e


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
        raise BundleError(f"{folder}: уже есть — подборка пишется в новое место")
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
            _copy_packs(pack_rows, work / "packs")
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
def opened(path: Path):
    """Корень подборки: папка как есть, zip — распакованный во временную папку (удаляется на выходе)."""
    path = Path(path)
    if path.suffix != ".zip":
        yield path
        return
    with tempfile.TemporaryDirectory(prefix="amem-bundle-") as tmp:
        try:
            with zipfile.ZipFile(path) as z:
                _check_zip(path, z.infolist())        # до распаковки: ни байта на диск из вредного архива
                z.extractall(tmp)
        except (OSError, zipfile.BadZipFile) as e:
            raise BundleError(f"{path}: не читается как zip: {e}") from e
        yield Path(tmp)


def _check_zip(path: Path, members: list[zipfile.ZipInfo]) -> None:
    """Имена, ссылки и размеры записей архива: вредное — BundleError, не полагаясь на чистку extractall."""
    if len(members) > MAX_MEMBERS:
        raise BundleError(f"{path}: {len(members)} записей в архиве — больше предела {MAX_MEMBERS}")
    total = 0
    for m in members:
        name = m.filename
        parts = PurePosixPath(name).parts
        if (not name or "\\" in name or "\0" in name or name.startswith("/") or ".." in parts
                or (len(name) > 1 and name[1] == ":")):
            raise BundleError(f"{path}: недопустимое имя в архиве {name!r}")
        if (m.external_attr >> 16) & 0o170000 == 0o120000:
            raise BundleError(f"{path}: {name} — символическая ссылка, в подборке их не бывает")
        total += m.file_size
        if total > MAX_UNPACKED:
            raise BundleError(f"{path}: распакованный размер больше предела {MAX_UNPACKED} байт")
        if m.file_size > RATIO_FROM and m.file_size > MAX_RATIO * max(m.compress_size, 1):
            raise BundleError(f"{path}: {name} сжат больше {MAX_RATIO}:1 — похоже на zip-бомбу")


def _manifest(root: Path, label: Path) -> dict:
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise BundleError(f"{label}: нет manifest.json — это не подборка или она записана не до конца") from None
    except (OSError, ValueError) as e:
        raise BundleError(f"{label}/manifest.json: не читается: {e}") from e
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        got = manifest.get("format") if isinstance(manifest, dict) else None
        raise BundleError(f"{label}: формат {got!r}, ожидается {FORMAT}")
    try:
        model_v1.BundleManifest.model_validate(manifest)
    except ValidationError as e:
        raise BundleError(f"{label}/manifest.json: {e}") from e
    if not isinstance(manifest["parts"], dict):
        raise BundleError(f"{label}/manifest.json: parts — не словарь")
    for name in manifest["parts"]:
        p = PurePosixPath(name)
        if not isinstance(name, str) or p.is_absolute() or ".." in p.parts or name == "manifest.json":
            raise BundleError(f"{label}/manifest.json: недопустимый путь части {name!r}")
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


def inspect(path: Path) -> dict:
    """Манифест и сверка частей без базы: манифест + ok, damaged (части с ошибкой), unexpected (файлы вне parts).

    Неверный формат или манифест — BundleError; повреждённая часть — не исключение, а damaged."""
    path = Path(path)
    with opened(path) as root:
        manifest = _manifest(root, path)
        damaged = _damaged(root, manifest)
        unexpected = [n for n in _files(root) if n != "manifest.json" and n not in manifest["parts"]]
    return {**manifest, "ok": not damaged, "damaged": damaged, "unexpected": unexpected}


# --- импорт (разд. 4.3) ---

TRUST = ("keep", "review")
ORIGIN = ("origin_base", "origin_revision_hash", "origin_agent")       # поля provenance, которые пишет импорт
RETIRED = ("deprecated", "superseded")
_NAME = re.compile(r"@b\d+")


@dataclass
class Imported:
    """Ответ импорта: пакет изменений (None — ничего не записано: dry_run или всё совпало), счётчики по действиям
    (created, unchanged, pending, skipped; links — новые связи; objects — новые объекты), пункты очереди,
    предупреждения, коллизии ключей (только у dry_run: без него коллизия — отказ) и complete — очередь пуста."""
    changeset_id: uuid.UUID | None
    counts: dict[str, int]
    queued: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    collisions: list[str] = field(default_factory=list)
    complete: bool = True


@dataclass
class _Rec:
    """Запись подборки и решение о ней: действие, тело для записи (None — писать нечего), ревизия после commit."""
    target: Target
    row: dict
    record_id: uuid.UUID
    action: str = ""
    body: dict | None = None
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


def _check_packs(conn, manifest: dict, root: Path, folder: Path) -> None:
    """Пакеты подборки загружены с теми же name, version, digest; иначе — отказ со списком и подсказкой."""
    have = {(n, v): d for n, v, d in conn.execute("SELECT name, version, digest FROM pack")}
    latest = dict(conn.execute("SELECT DISTINCT ON (name) name, version FROM pack "
                               "ORDER BY name, loaded_at DESC, version DESC").fetchall())
    missing, names = [], []
    for p in manifest["packs"]:
        if not isinstance(p, dict):
            raise BundleError(f"{folder}/manifest.json: пакет {p!r} — не объект")
        name, version, digest = p.get("name"), p.get("version"), p.get("digest")
        got = have.get((name, version))
        if got is not None and got == digest:
            continue
        why = ("загружен с другим digest" if got is not None else
               f"загружена версия {latest[name]}" if name in latest else "не загружен")
        missing.append(f"{name} {version} ({why})")
        names.append(name)
    if not missing:
        return
    bundled = [n for n in names if isinstance(n, str) and (root / "packs" / n / "pack.yaml").is_file()]
    if bundled and folder.suffix == ".zip":
        hint = "; пакеты лежат в подборке (packs/): распакуйте её, добавьте их папки в AMEM_PACKS и выполните prepare"
    elif bundled:
        hint = (f"; пакеты лежат в подборке: добавьте в AMEM_PACKS "
                f"{os.pathsep.join(str(root / 'packs' / n) for n in bundled)} и выполните prepare")
    else:
        hint = "; добавьте папки пакетов в AMEM_PACKS и выполните prepare"
    raise BundleError("не загружены пакеты подборки: " + "; ".join(missing) + hint, code="bundle_pack_missing",
                      missing=missing)


def _check_row(target: Target, row: dict, part: str) -> uuid.UUID:
    """Строка записи подборки: id, статус, ревизия с телом; хэш тела совпадает с content_hash ревизии."""
    try:
        record_id = uuid.UUID(row["id"])
        rev = row["revision"]
        payload, content_hash = rev["payload"], rev["content_hash"]
        if not isinstance(payload, dict) or not isinstance(content_hash, str) or not isinstance(rev["id"], str):
            raise TypeError("ревизия без тела, хэша или id")
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise BundleError(f"{part}: запись {row.get('id')!r} — неполная строка ({e})") from e
    ref = f"{PREFIX[target]}:{record_id}"
    if row.get("status") not in STATUSES:
        raise BundleError(f"{part}: {ref}: статус {row.get('status')!r} — не из перечня")
    try:
        same = canon.content_hash(payload) == content_hash
    except canon.CanonError as e:
        raise BundleError(f"{part}: {ref}: тело ревизии не приводится к канонической форме: {e}") from e
    if not same:
        raise BundleError(f"{part}: {ref}: content_hash не совпадает с телом ревизии — подборка повреждена или "
                          "изменена после экспорта")
    return record_id


def _swap(value, mapping: dict[str, str]):
    """Тело с заменой ссылок-строк по mapping (obj:/atm:/ent:<UUID> → другая ссылка или @имя)."""
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        return [_swap(v, mapping) for v in value]
    if isinstance(value, dict):
        return {k: _swap(v, mapping) for k, v in value.items()}
    return value


def _without_origin(payload: dict) -> dict:
    """Тело без полей происхождения, которые дописывает импорт: то же содержание, что в базе-источнике."""
    provenance = {k: v for k, v in (payload.get("provenance") or {}).items() if k not in ORIGIN}
    body = {k: v for k, v in payload.items() if k != "provenance"}
    return {**body, "provenance": provenance} if provenance else body


def _hash(payload: dict) -> str:
    return canon.content_hash(payload)


def _plan_objects(conn, rows: list[dict], warnings: list[str]) -> tuple[list[dict], dict[str, str], int]:
    """Объекты подборки: что принимать (adopt), какие ссылки obj: заменить на локальные и сколько объектов новых.

    Страница сайта или переписка, известная базе под другим id (тот же адрес или название), — тот же источник:
    ссылки на неё переводятся на локальный объект (предупреждение), иначе уникальный индекс отверг бы её."""
    adopt, mapping, new = [], {}, 0
    for o in rows:
        try:
            object_id = objects.object_uuid(o.get("id", ""))
        except ValueError as e:
            raise BundleError(f"objects.jsonl: объект {o.get('id')!r}: {e}") from e
        record = {k: v for k, v in o.items() if k != "status"}
        if conn.execute("SELECT 1 FROM object WHERE id = %s", (object_id,)).fetchone() is not None:
            adopt.append(record)
            continue
        kind = o.get("kind")
        column = {"web": "url", "message": "original_name"}.get(kind)
        value = o.get(column) if column else None
        if isinstance(value, str) and value.strip():
            row = conn.execute(f"SELECT id FROM object WHERE kind = %s AND {column} = normalize(%s, NFC)",
                               (kind, value.strip())).fetchone()
            if row is not None:
                mapping[f"obj:{object_id}"] = f"obj:{row[0]}"
                warnings.append(f"obj:{object_id}: {kind} {value!r} уже есть в базе как obj:{row[0]} — источники "
                                "подборки ссылаются на него")
                continue
        adopt.append(record)
        new += 1
    return adopt, mapping, new


def _plan_record(conn, rec: _Rec, mapping: dict[str, str], *, origin_base: str, own_base: str,
                 warnings: list[str], collisions: list[str]) -> None:
    """Действие для записи (разд. 4.3, шаг 6): created / unchanged / pending / skipped — и тело для записи.

    Совпадением считается любая локальная ревизия записи (текущая, ждущая, отклонённая, старая), чей content_hash
    или provenance.origin_revision_hash равен хэшу тела подборки или того же тела без полей происхождения: это
    содержание база уже видела, и повтор подборки ничего не меняет — даже если о нём уже решили."""
    t, rev = rec.target, rec.row["revision"]
    raw, incoming_hash = rev["payload"], rev["content_hash"]
    incoming = _swap(raw, mapping)
    try:
        keys = {incoming_hash, _hash(_without_origin(raw)), _hash(_without_origin(incoming))}
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
    if local is None:
        rec.action, rec.body = "created", body
        return
    if local[0] in RETIRED:
        rec.action = "skipped"
        warnings.append(f"{rec.ref}: локально {local[0]} — подборка её не меняет: вывод из оборота решается здесь")
        return
    seen = conn.execute(f"SELECT 1 FROM {t}_revision WHERE {t}_id = %s AND (content_hash = ANY(%s) "
                        "OR payload->'provenance'->>'origin_revision_hash' = ANY(%s)) LIMIT 1",
                        (rec.record_id, list(keys), list(keys))).fetchone()
    if seen is not None:
        rec.action = "unchanged"
        return
    rec.action, rec.body = "pending", body


def _link_ends(conn, link: dict) -> tuple[str, uuid.UUID, uuid.UUID, bool]:
    try:
        rel, src, dst = link["rel"], _ref_uuid(link["src"]), _ref_uuid(link["dst"])
        uuid.UUID(link["id"])
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as e:
        raise BundleError(f"links.jsonl: связь {link.get('id')!r} — неполная строка ({e})") from e
    data = conn.execute("SELECT data FROM concept WHERE scheme = 'rel' AND code = %s", (rel,)).fetchone()
    return rel, src, dst, bool(data and data[0].get("symmetric"))


def _plan_links(conn, rows: list[dict], warnings: list[str]) -> tuple[list[dict], list[uuid.UUID]]:
    """Связи (шаг 8): какие создать (тело с id подборки) и какие действующие локальные вывести из оборота.

    Своя связь ищется по id, затем — действующая с теми же rel и концами (у симметричной — в любую сторону).
    Выведенная в подборке и действующая локально — выводится; выведенная локально остаётся выведенной."""
    create, retire = [], []
    for link in rows:
        rel, src, dst, symmetric = _link_ends(conn, link)
        retired = link.get("retired_at") is not None
        ends = [(src, dst)] + ([(dst, src)] if symmetric else [])
        mine = conn.execute("SELECT id, retired_at FROM link WHERE id = %s", (link["id"],)).fetchone()
        if mine is None:
            same = [r for a, b in ends for r in conn.execute(
                "SELECT id, retired_at FROM link WHERE rel = %s AND coalesce(src_atom, src_entity) = %s "
                "AND coalesce(dst_atom, dst_entity) = %s ORDER BY retired_at NULLS FIRST", (rel, a, b)).fetchall()]
            active = [r for r in same if r[1] is None]
            mine = active[0] if active else same[0] if same else None
        where = f"связь {rel} {link['src']} → {link['dst']}"
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


def _history_rows(conn, recs: list[_Rec], origin_base: str) -> list[tuple]:
    """Ревизии подборки с историей — для import_history: история и текущая, каких там ещё нет."""
    out = []
    for r in recs:
        have = {n for (n,) in conn.execute("SELECT n FROM import_history WHERE origin_base = %s AND record_id = %s",
                                           (origin_base, r.record_id))}
        for h in [*(r.row.get("history") or []), r.row["revision"]]:
            if not isinstance(h, dict) or h.get("n") in have:
                continue
            try:
                out.append((r.target, r.record_id, int(h["n"]), h["content_hash"], h["payload"], h["recorded_at"],
                            h.get("agent")))
            except (KeyError, TypeError, ValueError) as e:
                raise BundleError(f"{r.ref}: ревизия истории — неполная строка ({e})") from e
            have.add(h["n"])
    return out


def _queue_reasons(rec: _Rec, trust: str) -> list[str]:
    """Пункты созданной ревизии (шаг 7): расхождение и trust=review — imported; при keep — как у submit по статусу."""
    if rec.action == "pending" or trust == "review":
        return ["imported"]
    status = rec.row["status"]
    return ["semantic"] if status == "draft" else ["imported"] if status == "needs_review" else []


def _verdicts(conn, store, rec: _Rec, rows: list[dict], mapping: dict[str, str], at: datetime) -> None:
    """Итоги сверки (шаг 9) в строки source созданной ревизии: есть копия файла той же версии (по digest) — итог
    подборки (тот же файл, то же место); у файла без копии — no_file, пока файл не придёт; страница сайта
    и переписка — итог подборки."""
    t = rec.target
    for s in rows:
        position, version = s.get("position"), s.get("object_version")
        try:
            object_id = _ref_uuid(mapping.get(s.get("object"), s.get("object")))
        except (AttributeError, ValueError, IndexError):
            continue
        kind = conn.execute("SELECT kind FROM object WHERE id = %s", (object_id,)).fetchone()
        if kind is None or not isinstance(version, int):
            continue
        verdict, page, anchor = s.get("verdict"), s.get("page"), s.get("anchor")
        if kind[0] == "file" and store.head(object_id) < version:
            verdict, page, anchor = "no_file", None, None
        if verdict not in review.VERDICTS:
            continue
        page = page if isinstance(page, int) and not isinstance(page, bool) and page >= 1 else None
        conn.execute(f"UPDATE source SET verdict = %s, page = %s, anchor = %s, checked_at = %s "
                     f"WHERE {t}_revision_id = %s AND position = %s",
                     (verdict, page, anchor if isinstance(anchor, str) else None, at, rec.revision.revision_id,
                      position))


def _stale_sources(conn, rec: _Rec) -> dict | None:
    """Источники созданной ревизии на не последнюю локальную версию объекта — details пункта source_changed."""
    rows = conn.execute(
        "SELECT s.object_id, array_agg(DISTINCT s.object_version ORDER BY s.object_version), latest.n FROM source s "
        "CROSS JOIN LATERAL (SELECT max(n) AS n FROM object_version v WHERE v.object_id = s.object_id) latest "
        f"WHERE s.{rec.target}_revision_id = %s AND s.object_version < latest.n "
        "GROUP BY s.object_id, latest.n ORDER BY s.object_id", (rec.revision.revision_id,)).fetchall()
    return review.source_changed_details(rows) if rows else None


def import_(conn: psycopg.Connection, store, folder: Path, *, agent: str, trust: str = "keep",
            dry_run: bool = False) -> Imported:
    """Влить подборку (папку или zip): id сохраняются, ничего не затирается (спецификация 3c, разд. 4.3).

    Порядок: манифест и sha256 частей → пакеты (bundle_pack_missing) → строки и хэши тел → объекты и план записей,
    коллизии ключей (bundle_key_collision) → уровень 1 → одна транзакция: объекты и их отметки, понятия агентов,
    записи и связи одним records.commit (keep_ids), статусы и пункты очереди, итоги сверки, вывод связей из
    оборота, import_history. Отказ — BundleError (code и details), и в базе ничего не появилось; файлы, уже
    скопированные в хранилище до отказа, повторный импорт примет как есть (objects.adopt).

    trust=keep — статус записи из подборки; review — новые записи needs_review с пунктом imported. Расхождение
    с локальной записью — ревизия pending с пунктом imported, текущая не меняется. dry_run — план без записи:
    счётчики, предупреждения и коллизии (вместо отказа)."""
    if trust not in TRUST:
        raise BundleError(f"trust: {trust!r} — ожидается keep или review")
    folder = Path(folder)
    with opened(folder) as root:
        manifest = _manifest(root, folder)
        damaged = _damaged(root, manifest)
        if damaged:
            raise BundleError(f"{folder}: повреждены части подборки: {', '.join(damaged)}")
        _check_packs(conn, manifest, root, folder)
        own = conn.execute("SELECT value FROM meta WHERE key = 'base_id'").fetchone()
        if own is None:
            raise BundleError("у базы нет base_id — выполните prepare")
        own_base, origin_base = own[0], manifest["base_id"]
        recs = [_Rec(target, row, _check_row(target, row, part))
                for target, part in (("entity", "entities.jsonl"), ("atom", "atoms.jsonl"))
                for row in _read_jsonl(root, part)]
        link_rows, object_rows = _read_jsonl(root, "links.jsonl"), _read_jsonl(root, "objects.jsonl")
        source_rows, concepts = _read_jsonl(root, "sources.jsonl"), _read_jsonl(root, "concepts.jsonl")
        files = {f"sha256:{PurePosixPath(n).name}": root / n for n in manifest["parts"]
                 if n.startswith("objects/sha256/")}
        warnings: list[str] = []
        collisions: list[str] = []
        adopt, mapping, new_objects = _plan_objects(conn, object_rows, warnings)
        for rec in recs:
            _plan_record(conn, rec, mapping, origin_base=origin_base, own_base=own_base, warnings=warnings,
                         collisions=collisions)
        new_links, retire = _plan_links(conn, link_rows, warnings)
        counts = {a: sum(r.action == a for r in recs) for a in ("created", "unchanged", "pending", "skipped")}
        counts |= {"links": len(new_links), "objects": new_objects}
        if dry_run:
            return Imported(None, counts, warnings=warnings, collisions=collisions, complete=not collisions)
        if collisions:
            raise BundleError("ключи заняты другими записями: " + "; ".join(collisions), code="bundle_key_collision",
                              collisions=collisions)
        report, names = _level1(conn, recs, new_links)
        if report.has_violations():
            text = _NAME.sub(lambda m: names.get(m[0], m[0]), report.summary())
            raise BundleError("подборка не прошла уровень 1:\n" + text,
                              report=report.as_json(levels={"1": "done"}, records=[], templates=[], degraded=[]))
        # история — только у подборки with_history и только чужая: своя история и так в базе
        history = (_history_rows(conn, recs, origin_base) if manifest["with_history"] and origin_base != own_base
                   else [])
        by_revision: dict[str, list[dict]] = {}
        for s in source_rows:
            by_revision.setdefault(s.get("revision_id"), []).append(s)
        try:
            with conn.transaction():
                cs = _write(conn, store, recs, new_links, retire, adopt, object_rows, concepts, history, files,
                            mapping, by_revision, warnings, agent=agent, trust=trust, origin_base=origin_base,
                            reason=f"import {origin_base} {manifest['created_at']}")
        except objects.ObjectError as e:
            raise BundleError(f"подборка не принята: {e}") from e
        except RecordError as e:
            raise BundleError(f"подборка не записана: {e}") from e
    changeset_id, queued = cs
    return Imported(changeset_id, counts, queued=queued, warnings=warnings, complete=not queued)


def _write(conn, store, recs: list[_Rec], new_links: list[dict], retire: list[uuid.UUID], adopt: list[dict],
           object_rows: list[dict], concepts: list[dict], history: list[tuple], files: dict[str, Path],
           mapping: dict[str, str], by_revision: dict[str, list[dict]], warnings: list[str], *, agent: str,
           trust: str, origin_base: str, reason: str) -> tuple[uuid.UUID | None, list[dict]]:
    """Запись импорта в уже открытой транзакции (функции записи ниже становятся точками сохранения)."""
    for record in adopt:
        warnings.extend(objects.adopt(conn, store, record, files=files, agent=agent))
    for o in object_rows:
        mark = o.get("status")
        if not isinstance(mark, dict) or f"obj:{o.get('id')}" in mapping:
            continue
        local = lookup.object_status(conn, o["id"])
        if local is None:
            by = mark.get("agent")
            objects.mark(conn, o["id"], mark.get("status"), note=mark.get("note"),
                         agent=by if isinstance(by, str) and objects.AGENT.fullmatch(by) else agent)
        elif (local["status"], local.get("note")) != (mark.get("status"), mark.get("note")):
            warnings.append(f"obj:{o['id']}: отметка {local['status']} локальная, в подборке {mark.get('status')} — "
                            "остаётся локальная")
    for c in concepts:
        scheme, code = c.get("scheme"), c.get("code")
        if not isinstance(scheme, str) or not isinstance(code, str):
            continue
        row = conn.execute("SELECT data FROM concept WHERE scheme = %s AND code = %s", (scheme, code)).fetchone()
        if row is None:
            conn.execute("INSERT INTO concept (scheme, code, data, origin, updated_at) VALUES (%s, %s, %s, 'agent', "
                         "now())", (scheme, code, Jsonb(c)))
        elif row[0] != c:
            warnings.append(f"понятие {scheme}.{code} отличается от локального — остаётся локальное")
    writing = [r for r in recs if r.body is not None]
    items = [records.Item(r.target, r.body, record_id=r.record_id,
                          status=("needs_review" if trust == "review" else r.row["status"]) if r.action == "created"
                          else None,
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
        records._ensure_agent(conn, agent)
        cs = records._new_changeset(conn, agent=agent, activity=None, reason=reason, state="approved",
                                    check_report=None, at=datetime.now(timezone.utc))
    at = conn.execute("SELECT created_at FROM changeset WHERE id = %s", (cs,)).fetchone()[0] if cs else None
    for r in writing:
        if not r.revision.created:
            continue
        _verdicts(conn, store, r, by_revision.get(r.row["revision"]["id"], []), mapping, at)
        details = {"origin_base": origin_base, "action": r.action}
        reasons = [(why, details) for why in _queue_reasons(r, trust)]
        stale = _stale_sources(conn, r)
        if stale:
            reasons.append(("source_changed", stale))
        for why, extra in reasons:
            item = review.insert_item(conn, r.target, r.record_id, r.revision.revision_id, why, changeset_id=cs,
                                      details=extra, agent=agent, at=at)
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
