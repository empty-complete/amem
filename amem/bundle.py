"""Подборки amem.bundle/1: отбор записей, экспорт в папку или zip, проверка без базы (спецификация 3c, разд. 4).

Подборка — папка (или zip той же структуры): manifest.json и части JSON Lines — entities, atoms, links, objects,
sources, concepts; по выбору — файлы объектов objects/sha256/<hex> и копии пакетов packs/<name>/. Записи идут
как есть: id, key, статус и текущая ревизия с каноническим телом и content_hash — получатель узнаёт то же
содержание по хэшу. Манифест пишется последним и даёт sha256 каждого файла: inspect сверяет их без базы.

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
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, fields
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath

import psycopg
from psycopg.rows import dict_row
from pydantic import ValidationError

from . import __version__, canon, lookup, model_v1, packs
from .ids import uuid7
from .ocfl_store import StoreError
from .records import PREFIX, Target

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
    """Неверный отбор, подборка, которую нельзя записать, или повреждённая подборка."""


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
