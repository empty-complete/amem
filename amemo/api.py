"""Операции в форме ответов HTTP-контракта v1 (docs/api/http-v1.openapi.yaml) — без Starlette.

Их зовут служба HTTP (amemo/service/http_v1.py), MCP и CLI, поэтому три входа не расходятся. Операция получает
соединение (autocommit, как db.connect), хранилище объектов или каталог бэкапов, агента и простые аргументы — числа
и флаги можно строками, как они приходят в запросе, — и отдаёт словарь, готовый к JSON, в форме схемы контракта.

Параметры проверяются по контракту (пределы, перечисления, формат) до вызова библиотеки: неверный — BadRequest
(400 у службы). Строка со знаком NUL (\\x00) отвергается в любом параметре: PostgreSQL такие строки не хранит
и не сравнивает, а ответ «база не приняла» хуже, чем ответ о самом параметре. Пустой список фильтра (kind, status,
entity_class, rels) — «без фильтра», как параметр, которого в запросе нет; пустой range листа — окно по умолчанию
библиотеки. Текст поиска проходит private.strip до поиска и журнала выдачи.

Подписи записей — lookup.labels одним запросом на ответ (label — подпись показанной ревизии на языке вызова,
amemo.lang.current(), с заменой на другой слот); запись,
которой нет, подписывается своей ссылкой. Записи называются atm:/ent:<UUID>, объекты — голым UUID, как id
в ObjectView: так их и передаёт интерфейс в /objects/{id} и в about=obj:<id>.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import shutil
import time
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from . import __version__, backup, bundle, check, db, folders, forms, lang, lookup, mine, objects, private, profile, \
    recipes, records, review, tasks, usefulness, vocab
from .anthology import export as anthology_export
from .check import level1
from .ids import uuid7
from .model_v1 import Status
from .ocfl_store import ObjectStore, StoreError

STATUSES = tuple(s.value for s in Status)
TARGETS = ("atom", "entity")
WHO = recipes.WHO
REVIEW_OPEN = ("queued", "claimed")
GRAPH_LIMIT_MAX = 1000              # limit у /graph — до 1000 узлов (по умолчанию recipes.GRAPH_LIMIT = 300)
ANCESTORS_DEPTH = 32                # цепочка part_of длиннее — обрывается (циклы обрываются по посещённым)
# файлы версий, которые браузер показывает сам; остальное отдаётся на скачивание (application/octet-stream)
INLINE_TYPES = frozenset({"application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp", "text/plain"})
_REF = re.compile(r"(atm|ent):.+")
VERSION_MAX = 2**31 - 1             # номер версии — integer базы
STORE_MARK = "0=ocfl_1.1"           # отметка корня OCFL (amemo/ocfl_store.py): без неё хранилище не подключено
_INT = re.compile(r"[+-]?[0-9]+")


class BadRequest(ValueError):
    """Параметр операции вне контракта: предел, перечисление, формат. У службы — 400 bad_request."""


class Forbidden(Exception):
    """Действие не по праву агента: структуру папок (создать, удалить, переименовать) меняет только человек.
    У службы — 403 forbidden."""


class CheckRejected(ValueError):
    """Пакет submit отклонён автопроверкой (Submitted.state == "rejected"): записей нет, отказ записан в changeset.
    issues — замечания в форме CheckIssue (ref и path), warnings — предупреждения службы (private_removed,
    secret_like). У службы — 422 check_rejected; CLI — код 5."""

    def __init__(self, message: str, *, changeset_id: str, issues: list[dict], warnings: list[dict]):
        super().__init__(message)
        self.changeset_id, self.issues, self.warnings = changeset_id, issues, warnings


class ReadOnly(Exception):
    """Запись по входу только для чтения (токен без write): настоящий импорт подборки. У службы — 403 read_only."""


class Missing(LookupError):
    """Подборки или загрузки нет: не было, срок хранения истёк или она чужая (чужая неотличима от несуществующей).
    У службы — 404 not_found."""


class Ambiguous(ValueError):
    """Текст вместо ссылки указал не на одну запись: явного лидера нет (pick). candidates — RefLabel со статусом.
    CLI — код 3 со списком кандидатов; у службы такого пути нет (там ссылки), перевод — 409 ambiguous."""

    def __init__(self, message: str, *, candidates: list[dict]):
        super().__init__(message)
        self.candidates = candidates


class QuotaExceeded(Exception):
    """Подборки и загрузки владельца заняли бы в папке состояния больше предела (AMEMO_STATE_QUOTA). У службы —
    507 quota_exceeded."""


class StoreUnavailable(RuntimeError):
    """Хранилище копий не подключено: в его корне нет отметки OCFL (том данных не смонтирован, AMEMO_DATA не тот).
    У службы — 503 store_unavailable; where — место на диске, только для журнала службы."""

    def __init__(self, message: str, *, where: str):
        super().__init__(message)
        self.where = where


class CopyMissing(objects.ObjectError):
    """Корень хранилища на месте, а копии версии нет (файл удалён вручную, инвентарь не сходится). У службы — 404
    not_found и предупреждение в журнал: это порча хранилища, а не ошибка запроса; where — только для журнала."""

    def __init__(self, message: str, *, where: str):
        super().__init__(message, code="not_found")
        self.where = where


# --- разбор параметров ---

def _str(value, name: str) -> str | None:
    """Строковый параметр: None — нет его; не строка или строка с NUL — BadRequest."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise BadRequest(f"{name} {value!r}: нужна строка")
    if "\x00" in value:
        raise BadRequest(f"{name}: знак NUL (\\x00) в строке не допускается")
    return value


def _int(value, name: str, *, low: int, high: int | None = None, default: int | None = None) -> int | None:
    """Целое из аргумента или строки запроса; None — default. Вне [low, high] — BadRequest."""
    if value is None or value == "":
        return default
    if isinstance(value, str) and _INT.fullmatch(_str(value, name).strip()):
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int):
        raise BadRequest(f"{name} {value!r}: нужно целое число")
    if value < low or (high is not None and value > high):
        bounds = f"от {low} до {high}" if high is not None else f"от {low}"
        raise BadRequest(f"{name} {value}: нужно целое число {bounds}")
    return value


def _bool(value, name: str, *, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and _str(value, name).strip().lower() in ("true", "false", "1", "0"):
        return value.strip().lower() in ("true", "1")
    raise BadRequest(f"{name} {value!r}: нужно true или false")


def _enum(value, name: str, allowed, *, default: str | None = None) -> str | None:
    if value is None or value == "":
        return default
    if _str(value, name) not in allowed:
        raise BadRequest(f"{name} {value!r}: допустимы {', '.join(allowed)}")
    return value


def _codes(values, name: str) -> list[str] | None:
    """Набор кодов фильтра: строка — один код; пустой набор — без фильтра (None)."""
    if values is None:
        return None
    if isinstance(values, str):
        values = [values]
    try:
        items = list(values)
    except TypeError:
        raise BadRequest(f"{name}: нужен список кодов") from None
    for item in items:
        if not isinstance(item, str) or not item.strip():
            raise BadRequest(f"{name}: код {item!r} — нужна непустая строка")
        _str(item, name)
    return list(dict.fromkeys(items)) or None


def _statuses(values) -> list[str] | None:
    statuses = _codes(values, "status")
    unknown = sorted(set(statuses or ()) - set(STATUSES))
    if unknown:
        raise BadRequest(f"status: неизвестные статусы {', '.join(unknown)}; допустимы {', '.join(STATUSES)}")
    return statuses


def _ref(value, name: str = "ref") -> str:
    if not isinstance(value, str) or not _REF.fullmatch(_str(value, name)):
        raise BadRequest(f"{name} {value!r}: нужна ссылка atm:<UUID или ключ> или ent:<UUID или ключ>")
    return value


def _moment(value, name: str) -> datetime | None:
    """Время ISO 8601 с часовым поясом; без пояса база прочла бы его в поясе сеанса."""
    if value is None or value == "":
        return None
    moment = value
    if isinstance(value, str):
        _str(value, name)
        # «+03:00» в строке запроса без %2B приходит как « 03:00»: «+» там — пробел
        text = re.sub(r"([Tt ][0-9:.,]+) ([0-9]{2}(?::?[0-9]{2})?)$", r"\1+\2", value.strip())
        try:
            moment = datetime.fromisoformat(text)
        except ValueError:
            raise BadRequest(f"{name} {value!r}: нужно время ISO 8601, например 2026-11-07T09:00:00Z") from None
    if not isinstance(moment, datetime) or moment.tzinfo is None or moment.utcoffset() is None:
        raise BadRequest(f"{name} {value!r}: нужно время с часовым поясом (…Z или …+03:00)")
    return moment


def _text(value) -> str | None:
    """Подпись из LangString на языке вызова (amemo.lang.current()) с заменой на другой слот; строка — как есть."""
    return lang.pick(value, lang.current())


def _iso(value) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else value


def _object_id(value) -> uuid.UUID:
    """id объекта из пути запроса: UUID или obj:<UUID>."""
    if isinstance(value, uuid.UUID):
        return value
    if not isinstance(value, str) or "\x00" in value:
        raise BadRequest(f"id {value!r}: нужен UUID объекта")
    try:
        return uuid.UUID(value[4:] if value.startswith("obj:") else value)
    except ValueError:
        raise BadRequest(f"id {value!r}: нужен UUID объекта (или obj:<UUID>)") from None


# --- подписи ---

def _labels(conn: psycopg.Connection, refs) -> dict[str, dict]:
    """RefLabel для ссылок (atm:/ent:) одним запросом: ref, label, kind или entity_class."""
    refs = list(dict.fromkeys(r for r in refs if isinstance(r, str)))
    found = lookup.labels(conn, refs, lang=lang.current()) if refs else {}
    out = {}
    for ref in refs:
        info = found.get(ref)
        label = {"ref": ref, "label": (info or {}).get("label") or ref}
        for key in ("kind", "entity_class"):
            if info and info.get(key):
                label[key] = info[key]
        out[ref] = label
    return out


def _kind_or_class(label: dict | None) -> str | None:
    return (label or {}).get("kind") or (label or {}).get("entity_class")


# --- сессия ---

def session(conn: psycopg.Connection, *, agent: str, can_write: bool, provider=None) -> dict:
    """Session: кто вошёл, какая база, есть ли смысловой поиск."""
    base = conn.execute("SELECT value FROM meta WHERE key = 'base_id'").fetchone()
    return {"agent": agent, "base": base[0] if base else None, "base_name": db.base_name(conn),
            "amem_version": __version__, "semantic": recipes.availability(conn, provider)["semantic"],
            "can_write": can_write}


# --- поиск ---

def search(conn: psycopg.Connection, q, *, agent: str, kind=None, status=None, entity_class=None, target=None,
           limit=None, provider=None, activity: uuid.UUID | None = None) -> dict:
    """SearchResult рецепта exact_fact; выдача пишется в retrieval от имени agent (activity — задача сессии MCP:
    находки этой выдачи сессия потом отмечает helpful). Если provider не может посчитать вектор запроса, смысловой
    канал пропускается (semantic: unavailable, причина в channels.reasons.vector), а не валит поиск: марки
    и полнотекстовый канал отвечают и так."""
    if _str(q, "q") is None:
        raise BadRequest("q: нужен текст запроса")
    result = recipes.exact_fact(
        conn, private.strip(q), agent=agent, activity=activity,
        limit=_int(limit, "limit", low=1, high=100, default=10),
        target=_enum(target, "target", TARGETS), kind=_codes(kind, "kind"),
        entity_class=_codes(entity_class, "entity_class"), statuses=_statuses(status), provider=provider,
        on_semantic_error="skip", lang=lang.current())
    return _search_result(conn, result)


def similar(conn: psycopg.Connection, *, agent: str, ref=None, q=None, limit=None, provider=None,
            activity: uuid.UUID | None = None) -> dict:
    """SearchResult рецепта similar — по ссылке на запись (ref) или по тексту (q), ровно одно из двух. Без вектора
    запроса похожие по тексту ищет полнотекстовый канал (semantic: unavailable), как у search."""
    if (ref in (None, "")) == (q in (None, "")):
        raise BadRequest("similar: нужен ровно один из параметров ref (atm:/ent:) или q (текст)")
    if ref not in (None, ""):
        query = _ref(ref)
    else:
        query = private.strip(_str(q, "q"))
        if query.startswith(("atm:", "ent:")):
            raise BadRequest("q: похожие на запись ищутся по параметру ref, а не по тексту atm:/ent:")
    result = recipes.similar(conn, query, agent=agent, activity=activity,
                             limit=_int(limit, "limit", low=1, high=100, default=10), provider=provider,
                             on_semantic_error="skip", lang=lang.current())
    return _search_result(conn, result)


def _search_result(conn: psycopg.Connection, result: dict) -> dict:
    items = result["items"]
    labels = _labels(conn, [item["ref"] for item in items])
    about = _current_about(conn, items)
    about_labels = _labels(conn, [ref for refs in about.values() for ref in refs])
    hits = []
    for item in items:
        label = labels[item["ref"]]
        hit = {"ref": item["ref"], "revision": item["revision"], "label": _text(item["label"]) or label["label"],
               "snippet": item["snippet"], "status": item["status"], "review_state": item["review_state"]}
        for key in ("kind", "entity_class"):
            if key in label:
                hit[key] = label[key]
        hit["about"] = [about_labels[ref] for ref in about.get(item["ref"], [])]
        hit["score"] = item["score"]
        hit["matches"] = [{"channel": m["channel"], "rank": m["rank"], "source_rank": m["source_rank"]}
                          for m in item["matches"]]
        hits.append(hit)
    coverage = result["embedding_coverage"]          # {total, covered, …} активной модели → доля; пустая база — 1
    if isinstance(coverage, dict):
        coverage = coverage["covered"] / coverage["total"] if coverage["total"] else 1.0
    return {"recipe": result["recipe"], "ranking_version": result["ranking_version"], "channels": result["channels"],
            "semantic": result["semantic"], "candidate_count": result["candidate_count"],
            "embedding_coverage": coverage, "items": hits,
            "retrieval_id": str(result["retrieval_id"]) if result["retrieval_id"] is not None else None}


def _current_about(conn: psycopg.Connection, items: list[dict]) -> dict[str, list[str]]:
    """about ревизий выдачи (атомы): ref → ссылки ent: по порядку тела."""
    atoms = [(item["ref"].split(":", 1)[1], item["revision"]) for item in items if item["ref"].startswith("atm:")]
    if not atoms:
        return {}
    rows = conn.execute(
        "SELECT r.atom_id, r.payload->'about' FROM atom_revision r "
        "JOIN unnest(%s::uuid[], %s::int[]) AS q(id, n) ON r.atom_id = q.id AND r.n = q.n",
        ([a for a, _ in atoms], [n for _, n in atoms])).fetchall()
    return {f"atm:{atom_id}": [ref for ref in (about or []) if isinstance(ref, str)] for atom_id, about in rows}


HELPFUL_MAX = 100                   # ссылок в одной отметке, не больше: выдача — до 100 находок


def helpful(conn: psycopg.Connection, retrieval_id, refs, *, agent: str, activity: uuid.UUID | None,
            issued_to: str | None = None) -> dict:
    """Отметить атомы выдачи, которые помогли (usefulness.mark_helpful): только выдачи той же задачи сессии —
    находки другой сессии (или выдачи без сессии, как у HTTP и CLI) не отмечаются, чужая выдача — Forbidden.

    issued_to — у клиента без сессии (MCP 2026-07-28): начало метки его задач. Тогда сверяется сама выдача — её агент
    и метка её задачи, — а отметка пишется в задачу выдачи: задача такого клиента режется по простою, а retrieval_id
    доказывает, что выдача его. {retrieval_id, marked}."""
    try:
        rid = uuid.UUID(_str(retrieval_id, "retrieval_id") or "")
    except ValueError:
        raise BadRequest(f"retrieval_id {retrieval_id!r}: нужен UUID выдачи из ответа поиска") from None
    if isinstance(refs, str) or not isinstance(refs, list) or not refs:
        raise BadRequest("refs: нужен непустой список ссылок atm: из этой выдачи")
    if len(refs) > HELPFUL_MAX:
        raise BadRequest(f"refs: не больше {HELPFUL_MAX} ссылок за раз")
    for ref in refs:
        if not isinstance(ref, str) or not ref.startswith("atm:"):
            raise BadRequest(f"refs: {ref!r} — полезность отмечается только у атомов (atm:<UUID>) выдачи")
        _ref(ref, "refs")
    row = conn.execute("SELECT r.activity, r.agent, a.label FROM retrieval r LEFT JOIN activity a ON a.id = r.activity "
                       "WHERE r.id = %s", (rid,)).fetchone()
    if row is None:
        raise BadRequest(f"retrieval_id {rid}: такой выдачи нет — возьмите retrieval_id из ответа поиска")
    found, found_agent, label = row
    if issued_to is not None:
        if found is None or found_agent != agent or not (label or "").startswith(issued_to):
            raise Forbidden(f"retrieval_id {rid}: выдача не из этой сессии — отмечать можно только находки своего "
                            f"поиска (тот же вход и агент)")
        activity = found
    elif activity is None or found != activity:
        raise Forbidden(f"retrieval_id {rid}: выдача не из этой сессии — отмечать можно только находки поиска "
                        f"своей сессии")
    try:
        usefulness.mark_helpful(conn, rid, refs, agent=agent, activity=activity)
    except ValueError as e:                  # атом не из этой выдачи, ссылка не UUID
        raise BadRequest(f"refs: {e}") from None
    return {"retrieval_id": str(rid), "marked": list(dict.fromkeys(refs))}


# --- папки и списки ---

def folder_tree(conn: psycopg.Connection) -> dict:
    """FolderTree: реестр папок со счётчиками по вложенности."""
    return folders.tree(conn)


def record_list(conn: psycopg.Connection, *, folder=None, kind=None, status=None, tag=None, about=None, limit=None,
                cursor=None) -> dict:
    """RecordList: сводки записей под фильтром, страница по курсору; about — ent:… или объект (obj:<UUID>, UUID)."""
    for name, value in (("folder", folder), ("tag", tag), ("about", about), ("cursor", cursor)):
        _str(value, name)
    page = lookup.list_records(conn, folder=folder or None, kinds=_codes(kind, "kind"), statuses=_statuses(status),
                               tag=tag or None, about=about or None,
                               limit=_int(limit, "limit", low=1, high=lookup.LIST_LIMIT, default=50),
                               cursor=cursor or None, lang=lang.current())
    return {"items": _summaries(conn, page["items"]), "next_cursor": page["next_cursor"], "total": page["total"]}


def _summaries(conn: psycopg.Connection, items: list[dict]) -> list[dict]:
    """RecordSummary из сводок lookup: about — RefLabel одним запросом; запись без подписи — своей ссылкой."""
    labels = _labels(conn, [ref for item in items for ref in item["about"]])
    return [{**item, "label": item["label"] or item["ref"],
             "about": [labels[ref] for ref in item["about"] if isinstance(ref, str)]} for item in items]


# --- запись ---

def record(conn: psycopg.Connection, ref, *, revision=None) -> dict:
    """RecordView: показанная ревизия записи (текущая; у записи, чьи ревизии все отклонены, — последняя), источники,
    открытые пункты очереди и полезность. revision — показать эту ревизию (сравнение, «Вернуть эту ревизию»):
    тело, источники, автор и время — её; статус, папка и пункты — записи. Такой ревизии нет — RecordNotFound."""
    n = _int(revision, "revision", low=1)
    target, record_id = records.resolve(conn, _ref(ref))          # нет записи — RecordNotFound (404)
    t = target
    current = lookup.get(conn, target, record_id)
    with conn.cursor(row_factory=dict_row) as cur:
        if n is not None:
            found = [r for r in lookup.history(conn, target, record_id) if r["n"] == n]
            if not found:
                raise records.RecordNotFound(f"{ref}: ревизии {n} нет")
            shown = found[0] | cur.execute(f"SELECT status, folder FROM {t} WHERE id = %s", (record_id,)).fetchone()
            shown["recorded_at"] = shown["recorded_at"].isoformat()
        elif current is not None:
            shown = cur.execute(f"SELECT id, n, payload FROM {t}_revision WHERE {t}_id = %s AND n = %s",
                                (record_id, current["revision"])).fetchone()
            shown |= {"review_state": current["review_state"], "recorded_at": current["recorded_at"],
                      "agent": current["agent"], "status": current["status"], "folder": current["folder"]}
        else:
            # текущей ревизии нет (все отклонены): список записей и подписи показывают последнюю — и здесь она
            shown = lookup.history(conn, target, record_id)[-1]
            shown |= cur.execute(f"SELECT status, folder FROM {t} WHERE id = %s", (record_id,)).fetchone()
            shown["recorded_at"] = shown["recorded_at"].isoformat()
    payload = shown["payload"]
    canonical = f"{records.PREFIX[target]}:{record_id}"
    about = [r for r in payload.get("about") or [] if isinstance(r, str)] if target == "atom" else []
    chain = _ancestors(conn, about[0] if about else (canonical if target == "entity" else None))
    items = [row for state in REVIEW_OPEN for row in review.items(conn, state=state, record=canonical, limit=500)]
    labels = _labels(conn, [canonical, *about, *chain])
    score = None
    if target == "atom":
        try:
            score = usefulness.score(conn, record_id)
        except ValueError:                       # отметка из будущего (часы ушли назад) — польза не считается
            score = None
    return {
        "ref": canonical, "target": target, "revision": shown["n"], "payload": payload, "status": shown["status"],
        "review_state": shown["review_state"], "recorded_at": shown["recorded_at"], "agent": shown["agent"],
        "folder": shown["folder"], "about": [labels[r] for r in about], "ancestors": [labels[r] for r in chain],
        "sources": _sources(conn, target, shown["id"]),
        "open_items": [_review_item(row, labels) for row in sorted(items, key=lambda r: (r["created_at"], r["id"]))],
        "usefulness": score,
    }


def _ancestors(conn: psycopg.Connection, entity_ref: str | None) -> list[str]:
    """Цепочка part_of сущности вверх, от корня, без неё самой; у нескольких родителей — первый по id."""
    if entity_ref is None or not entity_ref.startswith("ent:"):
        return []
    try:
        current = uuid.UUID(entity_ref[4:])
    except ValueError:
        return []
    seen, chain = {current}, []
    for _ in range(ANCESTORS_DEPTH):
        row = conn.execute("SELECT dst_entity FROM link WHERE rel = 'part_of' AND src_entity = %s "
                           "AND dst_entity IS NOT NULL AND retired_at IS NULL ORDER BY dst_entity LIMIT 1",
                           (current,)).fetchone()
        if row is None or row[0] in seen:
            break
        current = row[0]
        seen.add(current)
        chain.append(f"ent:{current}")
    return chain[::-1]


def _sources(conn: psycopg.Connection, target: str, revision_id) -> list[dict]:
    """SourceView источников ревизии: объект (голый UUID), его имя, вид и тип, место, роль, итог сверки (или null)."""
    rows = lookup.revision_sources(conn, target, revision_id)
    ids = list(dict.fromkeys(row["object"].split(":", 1)[1] for row in rows))
    known = {}
    if ids:
        with conn.cursor(row_factory=dict_row) as cur:
            known = {str(o["id"]): o for o in cur.execute(
                "SELECT id, kind, original_name, url, media_type FROM object WHERE id = ANY(%s::uuid[])", (ids,))}
    out = []
    for row in rows:
        object_id = row["object"].split(":", 1)[1]
        obj = known.get(object_id, {})
        view = {"object": object_id}
        if obj.get("original_name") or obj.get("url"):
            view["object_name"] = obj.get("original_name") or obj.get("url")
        if obj.get("kind"):
            view["object_kind"] = obj["kind"]
        if obj.get("media_type"):
            view["media_type"] = obj["media_type"]
        view |= {"object_version": row["object_version"], "selectors": row.get("selectors") or []}
        for key in ("quote", "role", "page", "anchor", "edition", "checked_at"):
            if key in row:
                view[key] = row[key]
        view["verdict"] = row.get("verdict")
        out.append(view)
    return out


def _item_context(conn: psycopg.Connection, rows: list[dict]) -> tuple[dict, dict]:
    """Документ и объекты пунктов очереди пакетом на весь список (часть J веб-UI): id пункта → первый источник ревизии
    {object, object_name} и id пункта → about атома (ссылки ent: по порядку тела). Без запроса на каждый пункт."""
    by_target: dict[str, list] = {}
    for row in rows:
        by_target.setdefault(row["target"], []).append(row["revision_id"])
    first: dict = {}
    for target, revisions in by_target.items():
        for rid, srcs in lookup.revisions_sources(conn, target, revisions).items():
            if srcs:
                first[rid] = srcs[0]["object"].split(":", 1)[1]
    names = {}
    if first:
        names = {str(oid): name for oid, name in conn.execute(
            "SELECT id, coalesce(original_name, url) FROM object WHERE id = ANY(%s::uuid[])",
            (list(set(first.values())),)).fetchall()}
    about = {}
    atoms = by_target.get("atom", [])
    if atoms:
        about = {rid: [r for r in (refs or []) if isinstance(r, str)] for rid, refs in conn.execute(
            "SELECT id, payload->'about' FROM atom_revision WHERE id = ANY(%s::uuid[])", (atoms,)).fetchall()}
    sources, abouts = {}, {}
    for row in rows:
        oid = first.get(row["revision_id"])
        sources[row["id"]] = {"object": oid, "object_name": names.get(oid) or oid} if oid else None
        abouts[row["id"]] = about.get(row["revision_id"], [])
    return sources, abouts


def _review_item(row: dict, labels: dict[str, dict], source: dict | None = None,
                 about: list[str] | None = None) -> dict:
    """ReviewItem из строки review.items: подпись и вид записи, время — ISO 8601; source и about — у списка очереди."""
    label = labels.get(row["ref"])
    item = {"id": str(row["id"]), "ref": row["ref"]}
    if label is not None:
        item["label"] = label["label"]
        if _kind_or_class(label):
            item["kind_or_class"] = _kind_or_class(label)
    item |= {"reason": row["reason"], "state": row["state"], "details": row["details"],
             "created_at": _iso(row["created_at"]), "created_by": row["created_by"], "author": row["author"],
             "claimed_by": row["claimed_by"], "claimed_until": _iso(row["claimed_until"]),
             "closed_at": _iso(row["closed_at"])}
    if about is not None:
        item["source"] = source
        item["about"] = [{"ref": ref, "label": labels.get(ref, {}).get("label", ref)} for ref in about]
    return item


def history(conn: psycopg.Connection, ref) -> dict:
    """ChangesResult по записи: все её события по времени."""
    return _changes(conn, recipes.what_changed(conn, ref=_ref(ref)))


def changes(conn: psycopg.Connection, *, since=None, until=None, who=None, limit=None) -> dict:
    """ChangesResult по базе за [since, until): самые новые limit событий, по времени."""
    since, until = _moment(since, "since"), _moment(until, "until")
    if since is not None and until is not None and since >= until:
        raise BadRequest("since должен быть строго раньше until")
    return _changes(conn, recipes.what_changed(conn, since=since, until=until,
                                               who=_enum(who, "who", WHO, default="all"),
                                               limit=_int(limit, "limit", low=1, high=500, default=100)))


HIDDEN_EVENT_FIELDS = ("content_hash", "previous_content_hash")      # служебные хэши тела — не для экрана


def _changes(conn: psycopg.Connection, result: dict) -> dict:
    """События what_changed с подписью записи. У событий связи ref — запись истории (по базе — начало связи)."""
    events = []
    for event in result["events"]:
        event = {k: v for k, v in event.items() if k not in HIDDEN_EVENT_FIELDS}
        if "ref" not in event and "src" in event:
            event["ref"] = result["ref"] or event["src"]
        events.append(event)
    labels = _labels(conn, [event["ref"] for event in events if "ref" in event])
    for event in events:
        if event.get("ref") in labels:
            event["label"] = labels[event["ref"]]["label"]
    return {"ref": result["ref"], "since": result["since"], "until": result["until"], "events": events}


def links(conn: psycopg.Connection, ref) -> list[dict]:
    """LinkView[]: действующие связи записи с подписью другого конца."""
    target, record_id = records.resolve(conn, _ref(ref))
    own = f"{records.PREFIX[target]}:{record_id}"
    rows = lookup.links(conn, record_id)
    labels = _labels(conn, [row["dst"] if row["src"] == own else row["src"] for row in rows])
    out = []
    for row in rows:
        out_going = row["src"] == own
        out.append({"id": row["id"], "rel": row["rel"], "direction": "out" if out_going else "in",
                    "other": labels[row["dst"] if out_going else row["src"]], "note": row.get("note"),
                    "confidence": row.get("confidence"), "agent": row["agent"], "created_at": row["created_at"]})
    return out


TIMELINE_EVENTS = 10                # событий истории в timeline по умолчанию (последние)


def timeline(conn: psycopg.Connection, ref, *, limit=None) -> dict:
    """Timeline — шаг 2 поиска «что вокруг находки»: запись (RefLabel, статус, папка), последние limit событий её
    истории (по времени, как в ChangesResult) и действующие связи с подписью другого конца (LinkView)."""
    limit = _int(limit, "limit", low=1, high=500, default=TIMELINE_EVENTS)
    target, record_id = records.resolve(conn, _ref(ref))
    own = f"{records.PREFIX[target]}:{record_id}"
    status, folder = conn.execute(f"SELECT status, folder FROM {target} WHERE id = %s", (record_id,)).fetchone()
    events = history(conn, own)["events"]
    return {"record": {**_labels(conn, [own])[own], "status": status, "folder": folder},
            "events": events[-limit:], "total_events": len(events), "links": links(conn, own)}


PICK_CANDIDATES = 10                # кандидатов в ответе неоднозначного pick


def pick(conn: psycopg.Connection, text, *, target=None) -> str:
    """Одна запись по ссылке или по тексту: ссылка atm:/ent: — каноническая ссылка (нет записи — RecordNotFound);
    текст — лексические каналы без записи выдачи (марка целиком, начало марки, полнотекстовый). Явный лидер —
    единственное совпадение марки целиком, а без него — единственная находка канала (сначала полнотекстового,
    затем начала марки). Иначе Ambiguous с кандидатами; ничего — RecordNotFound с подсказкой найти запись."""
    from . import search as search_

    text = _str(text, "ref")
    if not text or not text.strip():
        raise BadRequest("ref: нужна ссылка atm:/ent: или текст для поиска записи")
    if _REF.fullmatch(text):
        found_target, record_id = records.resolve(conn, text)
        return f"{records.PREFIX[found_target]}:{record_id}"
    query = private.strip(text).strip()
    filters = {"target": _enum(target, "target", TARGETS), "kind": None, "entity_class": None, "statuses": None}
    channels = [search_._code_exact(conn, query, **filters), search_._fts(conn, query, **filters),
                search_._code_prefix(conn, query, **filters)]
    refs = [list(dict.fromkeys(row["ref"] for row in rows)) for rows in channels]
    exact, fts, prefix = refs
    if len(exact) == 1:
        return exact[0]
    if not exact:
        for found in (fts, prefix):
            if len(found) == 1 and not (found is prefix and fts):
                return found[0]
    candidates = list(dict.fromkeys(exact + fts + prefix))
    if not candidates:
        raise records.RecordNotFound(f"по тексту {query[:80]!r} записей нет — найдите запись поиском "
                                     f"(amemo search, amemo_search) и передайте её ссылку atm:/ent:")
    labels = lookup.labels(conn, candidates[:PICK_CANDIDATES], lang=lang.current())
    shown = []
    for ref in candidates[:PICK_CANDIDATES]:
        info = labels.get(ref) or {}
        shown.append({"ref": ref, "label": info.get("label") or ref,
                      **{key: info[key] for key in ("kind", "entity_class", "status") if info.get(key)}})
    # канал отдаёт не больше search._CHANNEL_LIMIT строк: на пределе настоящих совпадений может быть больше
    at_limit = any(len(rows) >= search_._CHANNEL_LIMIT for rows in channels)
    count = f"не меньше {len(candidates)}" if at_limit else str(len(candidates))
    raise Ambiguous(f"по тексту {query[:80]!r} нашлось записей: {count}, явного лидера нет — выберите ссылку",
                    candidates=shown)


# --- карточка и граф ---

def card(conn: psycopg.Connection, ref, *, ancestors=None) -> dict:
    """Card (amem.card/1): поля профиля с подписями величин; предки свёрнуты в RefLabel, от корня."""
    full = profile.card(conn, _ref(ref), ancestors=_bool(ancestors, "ancestors", default=True))
    properties = {code: _text(data.get("label")) for code, data in conn.execute(
        "SELECT code, data FROM concept WHERE scheme = 'property' AND code = ANY(%s)",
        ([f["property"] for f in full["fields"]],)).fetchall()}
    fields = []
    for field in full["fields"]:
        field = {**field, **{key: _text(field.get(key)) for key in ("ask", "hint", "when")}}
        if properties.get(field["property"]):
            field["label"] = properties[field["property"]]
        fields.append(field)

    def entity(view: dict) -> dict:
        return {"ref": view["ref"], "label": _text(view["label"]) or view["ref"],
                "entity_class": view["entity_class"]}

    return {**full, "entity": entity(full["entity"]), "fields": fields,
            "ancestors": [entity(parent["entity"]) for parent in reversed(full["ancestors"])]}


def graph(conn: psycopg.Connection, ref=None, *, depth=None, limit=None, project=None, rels=None,
          status=None) -> dict:
    """GraphResult. С ref — recipes.around_entity: кратчайшие пути от записи до depth шагов, не больше limit узлов
    (ближние раньше дальних). Без ref — recipes.overview: обзор базы по degree, project — атомы проекта и связанные
    с ними сущности. total — узлов без предела, truncated — total > limit; у узла degree и pending.

    project — только для обзора: с ref он проверяется, но окрестность не сужает (небо шлёт его и при выбранном
    центре); depth без ref — так же."""
    depth = _int(depth, "depth", low=1, high=3, default=1)
    limit = _int(limit, "limit", low=1, high=GRAPH_LIMIT_MAX, default=recipes.GRAPH_LIMIT)
    project = _ref(project, "project") if project not in (None, "") else None
    rels, statuses = _codes(rels, "rels"), _statuses(status)
    if ref is None or ref == "":
        # предел — в самом запросе: степень, порядок и обрезка считаются в базе
        found = recipes.overview(conn, limit=limit, project=project, statuses=statuses, rels=rels)
        start = None
    else:
        # предел — в самом обходе: граф глубины 3 не обходится целиком ради ближних узлов
        found = recipes.around_entity(conn, _ref(ref), depth=depth, rels=rels, statuses=statuses, limit=limit)
        start = found["start"]
    nodes = found["nodes"]
    kept = {node["ref"] for node in nodes}
    labels = _labels(conn, kept)
    families = vocab.families(conn)
    out_nodes = []
    for node in nodes:
        code = node.get("kind") or node.get("entity_class")
        family = families.get(code, vocab.DEFAULT_FAMILY) if node["target"] == "atom" else "object"
        out_nodes.append({"ref": node["ref"], "label": labels[node["ref"]]["label"], "kind_or_class": code,
                          "family": family, "status": node["status"],
                          **({"depth": node["depth"]} if "depth" in node else {}),
                          "pending": node["pending"], "degree": node["degree"]})
    edges = [{"src": edge["src"], "dst": edge["dst"], "rel": edge["rel"], "confidence": edge["confidence"]}
             for edge in found["edges"] if edge["src"] in kept and edge["dst"] in kept]
    return {"ref": start, "nodes": out_nodes, "edges": edges, "truncated": found["truncated"],
            "total": found["total"]}


# --- объекты ---

def object_view(conn: psycopg.Connection, object_id) -> dict:
    """ObjectView: объект, версии с числом цитат, отметка, цитаты текущих ревизий, страницы и листы."""
    oid = _object_id(object_id)
    view = lookup.object_view(conn, oid)
    if view is None:
        raise objects.ObjectError(f"obj:{oid}: такого объекта нет", code="not_found")
    return _object_card(conn, view)


def _object_card(conn: psycopg.Connection, view: dict) -> dict:
    """lookup.object_view → ObjectView контракта: подписи цитирующих записей, число цитат у версий."""
    labels = _labels(conn, [c["record"] for c in view["cited_by"]])
    citations = [{**c, "record": labels[c["record"]]} for c in view["cited_by"]]
    counts: dict[int, int] = {}
    for c in citations:
        counts[c["version"]] = counts.get(c["version"], 0) + 1
    versions = [{"n": v["n"], "digest": v.get("digest"), "size": v.get("size"), "recorded_at": v["recorded_at"],
                 "cited_by": counts.get(v["n"], 0)} for v in view["versions"]]
    return {**view, "media_type": view.get("media_type"), "url": view.get("url"),
            "logical_paths": view.get("logical_paths", []), "versions": versions, "cited_by": citations}


@dataclass(frozen=True)
class Content:
    """Файл версии для раздачи: путь копии в хранилище, тип, имя и как отдавать."""
    path: Path
    media_type: str
    filename: str | None
    inline: bool          # тип из белого списка — как есть; иначе application/octet-stream на скачивание


def _store_failure(store: ObjectStore, oid: uuid.UUID, n: int, error) -> Exception:
    """Почему копии нет: корня хранилища нет — StoreUnavailable (503), корень есть — CopyMissing (404)."""
    root = Path(store.root)
    if not (root / STORE_MARK).is_file():
        return StoreUnavailable("хранилище копий не подключено: в AMEMO_DATA нет корня OCFL — проверьте, что том "
                                "с данными смонтирован", where=f"{root}: нет {STORE_MARK}")
    return CopyMissing(f"obj:{oid}: копии версии {n} нет в хранилище — восстановите хранилище из снимка "
                       f"или добавьте файл заново", where=str(error))


def _copy(store: ObjectStore, oid: uuid.UUID, n: int) -> Path:
    """Путь копии версии в хранилище: обычный файл внутри папки объекта (инвентарь не уводит наружу)."""
    try:
        path = store.content(oid, n)
    except StoreError as e:
        raise _store_failure(store, oid, n, e) from e
    resolved = path.resolve()
    if not resolved.is_relative_to(store.object_dir(oid).resolve()) or not resolved.is_file():
        raise _store_failure(store, oid, n, f"{path}: нет обычного файла копии внутри папки объекта")
    return resolved


def object_content(conn: psycopg.Connection, store: ObjectStore, object_id, n) -> Content:
    """Копия файла версии n из хранилища. Нет объекта, версии или копии (сайт, переписка) — ObjectError not_found;
    копии нет в хранилище — CopyMissing (404) или StoreUnavailable (503)."""
    oid = _object_id(object_id)
    n = _int(n, "n", low=1, high=VERSION_MAX)
    row = conn.execute("SELECT o.original_name, o.media_type, v.digest FROM object o "
                       "JOIN object_version v ON v.object_id = o.id WHERE o.id = %s AND v.n = %s", (oid, n)).fetchone()
    if row is None:
        raise objects.ObjectError(f"obj:{oid}: нет объекта или версии {n}", code="not_found")
    name, media_type, digest = row
    if digest is None:
        raise objects.ObjectError(f"obj:{oid}: у версии {n} нет файла (страница сайта или переписка)",
                                  code="not_found")
    path = _copy(store, oid, n)
    media = (media_type or "").partition(";")[0].strip().lower()
    inline = media in INLINE_TYPES
    return Content(path, media if inline else "application/octet-stream", name, inline)


def object_text(conn: psycopg.Connection, store: ObjectStore, object_id, n, *, page=None) -> dict:
    """Текст версии по страницам ({pages}); у файла без текста и у версии без файла — пустой список.
    page — одна страница (с 1); нет такой — ObjectError not_found. Текст из кэша отдаётся и без копии в хранилище."""
    oid, n = _object_id(object_id), _int(n, "n", low=1, high=VERSION_MAX)
    page = _int(page, "page", low=1)
    try:
        pages = objects.text(conn, store, oid, n) or []
    except (StoreError, OSError) as e:          # копии нет или она не читается — не кэшируем и не 500
        raise _store_failure(store, oid, n, e) from e
    if page is not None:
        if page > len(pages):
            raise objects.ObjectError(f"obj:{oid}: у версии {n} нет страницы {page} (страниц {len(pages)})",
                                      code="not_found")
        pages = [pages[page - 1]]
    return {"pages": pages}


def object_sheet(conn: psycopg.Connection, store: ObjectStore, object_id, n, *, name, cell_range=None) -> dict:
    """Ячейки листа xlsx: {name, range, rows}; пустой range — окно по умолчанию (A1:L40 по данным)."""
    oid, n = _object_id(object_id), _int(n, "n", low=1, high=VERSION_MAX)
    if not _str(name, "name"):
        raise BadRequest("name: нужно имя листа")
    _str(cell_range, "range")
    try:
        return objects.sheet(conn, store, oid, n, name, cell_range or None)
    except (StoreError, OSError) as e:
        raise _store_failure(store, oid, n, e) from e


def _document(conn: psycopg.Connection, path) -> tuple[str, str | None]:
    """Путь в папке документов или ссылка obj:<UUID> → (как спросили, obj:<UUID> или None — объекта ещё нет)."""
    path = _str(path, "path")
    if not path or not path.strip():
        raise BadRequest("path: нужен путь документа от корня папки документов (или obj:<UUID>)")
    if path.startswith("obj:"):
        oid = _object_id(path)
        found = conn.execute("SELECT 1 FROM object WHERE id = %s", (oid,)).fetchone()
        return path, f"obj:{oid}" if found else None
    return path, lookup.object_by_path(conn, path)


def object_status(conn: psycopg.Connection, path) -> dict:
    """Что из документа атомизировано: {path, object, status, note?, agent?, changed_at?, cited_by}. Документа нет
    в базе (его ещё не цитировали и не отмечали) — object и status null: это ответ, а не ошибка."""
    path, ref = _document(conn, path)
    out = {"path": path, "object": ref, "status": None, "cited_by": 0}
    if ref is not None:
        mark = lookup.object_status(conn, ref)
        if mark is not None:
            out |= {**mark, "changed_at": _iso(mark["changed_at"])}
        view = lookup.object_view(conn, ref)
        out["cited_by"] = len(view["cited_by"]) if view else 0
    return out


OBJECT_SEARCH_LIMIT = 20               # объектов на страницу поиска по умолчанию (контракт: 1–100)


def object_search(conn: psycopg.Connection, *, q=None, limit=None, cursor=None) -> dict:
    """{items: ObjectView[], next_cursor}: объекты по части имени или пути без учёта регистра (lookup.object_search);
    пустой q — последние объекты."""
    page = lookup.object_search(conn, _str(q, "q"), cursor=_str(cursor, "cursor"),
                                limit=_int(limit, "limit", low=1, high=lookup.OBJECT_LIMIT,
                                           default=OBJECT_SEARCH_LIMIT))
    return {"items": [_object_card(conn, v) for v in page["items"]], "next_cursor": page["next_cursor"]}


def object_upload_begin(docs: Path | None) -> Path:
    """Временный файл загрузки в корне папки документов (.amemo-upload-<id>.part): служба пишет туда тело потоком,
    затем object_upload кладёт его по пути — в той же файловой системе. Нет папки документов — ObjectError
    docs_unavailable (503) до чтения тела."""
    return objects.docs_root(docs) / f".amemo-upload-{uuid7()}.part"


PART_STALE = 3600.0      # с; временный файл загрузки без записи дольше часа — брошен (служба упала посреди загрузки)


def object_upload_sweep(docs: Path | None, *, older_than: float = PART_STALE) -> int:
    """Убрать брошенные временные файлы загрузки (.amemo-upload-*.part) в корне папки документов: их оставляет
    служба, упавшая посреди загрузки. Файл, в который пишут сейчас, свежий (mtime) — его не трогаем. Вернуть число
    удалённых; нет папки документов — 0."""
    if docs is None or not Path(docs).is_dir():
        return 0
    edge = time.time() - older_than
    removed = 0
    for part in Path(docs).glob(".amemo-upload-*.part"):
        try:
            if part.is_file() and not part.is_symlink() and part.stat().st_mtime < edge:
                part.unlink()
                removed += 1
        except FileNotFoundError:
            continue
    return removed


def object_upload(conn: psycopg.Connection, store: ObjectStore, docs: Path | None, part: Path, *, filename=None,
                  path=None, agent: str) -> tuple[dict, bool]:
    """Загруженный файл (part) — в папку документов по path или Загрузки/<filename> и в базу (objects.upload):
    (ObjectView, True — файл записан сейчас: 201; False — тот же файл уже лежал: 200). Другой файл по пути —
    ObjectError path_taken (409); путь с «..», абсолютный — 400. part удаляется в любом случае."""
    try:
        key = objects.upload_path(_str(path, "path"), _str(filename, "filename"))
    except BaseException:
        Path(part).unlink(missing_ok=True)
        raise
    version, created = objects.upload(conn, store, docs, part, key, agent=agent)
    return object_view(conn, version.object_id), created


def object_mark(conn: psycopg.Connection, store: ObjectStore, docs: Path | None, path, status, *, agent: str,
                note=None) -> dict:
    """Отметить, что из документа атомизировано (objects.mark: parsed, partial, skipped). Документа ещё нет в базе —
    он принимается из папки документов (objects.ingest: копия в хранилище), как источник при submit. Ответ —
    object_status после отметки."""
    statuses = tuple(sorted(objects.STATUSES))
    status = _enum(status, "status", statuses)
    if status is None:
        raise BadRequest(f"status: нужен один из {', '.join(statuses)}")
    path, ref = _document(conn, path)
    if ref is None:
        if path.startswith("obj:"):
            raise objects.ObjectError(f"{path}: такого объекта нет", code="not_found")
        if docs is None:
            raise BadRequest(f"{path}: документа нет в базе, а папка документов не настроена (AMEMO_DOCS)")
        ref = f"obj:{objects.ingest(conn, store, docs, path, agent=agent).object_id}"
    objects.mark(conn, ref, status, agent=agent, note=_note(note))
    return object_status(conn, ref) | {"path": path}


# --- словарь, база, бэкапы ---

def vocab_entries(conn: psycopg.Connection, scheme) -> list[dict]:
    """VocabEntry[] схемы словаря (kind, entity_class, property, rel, …); неизвестная схема — пустой список."""
    if not _str(scheme, "scheme"):
        raise BadRequest("scheme: нужно имя схемы словаря")
    return vocab.entries(conn, scheme)


TAGS_LIMIT = 50


def tag_counts(conn: psycopg.Connection, *, q=None, limit=None) -> list[dict]:
    """TagCount[] — теги, которые стоят на текущих ревизиях атомов, с числом атомов: для подсказок в окне записи
    и в поле тегов. q — начало тега без учёта регистра; сначала частые, затем по алфавиту."""
    q = _str(q, "q")
    limit = _int(limit, "limit", low=1, high=200, default=TAGS_LIMIT)
    prefix = unicodedata.normalize("NFC", q.strip().lstrip("#")) if q else ""
    like = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = conn.execute(
        "SELECT t, count(*) FROM atom_current c, jsonb_array_elements_text(coalesce(c.payload->'tags', '[]')) t "
        "WHERE lower(t) LIKE lower(%s) GROUP BY t ORDER BY count(*) DESC, t LIMIT %s", (like, limit)).fetchall()
    return [{"tag": t, "count": n} for t, n in rows]


def templates(conn: psycopg.Connection, *, target=None) -> list[dict]:
    """TemplateView[] — форма каждого вида атома и класса сущности (amemo/forms.py); target — atom или entity."""
    return forms.views(conn, target=_enum(target, "target", TARGETS))


def template_put(conn: psycopg.Connection, code, draft, *, agent: str) -> dict:
    """TemplateView своего вида после правки по черновику (TemplateDraft); правит только человек (403 forbidden).
    Занятый пакетом из файла код — MineError exists (409), черновик не по проверке — invalid (422 с issues)."""
    _person_only(agent, "свои виды правит")
    code = _str(code, "code")
    if not isinstance(draft, dict):
        raise BadRequest("тело: ожидается объект TemplateDraft")
    return mine.put(conn, code, draft, agent=agent)


def template_delete(conn: psycopg.Connection, code, *, agent: str) -> None:
    """Удалить свой вид; есть записи этого вида — MineError in_use (409), своего вида нет — not_found (404)."""
    _person_only(agent, "свои виды удаляет")
    mine.delete(conn, _str(code, "code"), agent=agent)


def base(conn: psycopg.Connection) -> dict:
    """Base: id и имя базы, загруженные пакеты (последняя версия каждого), счётчики и открытые пункты очереди."""
    row = conn.execute("SELECT value FROM meta WHERE key = 'base_id'").fetchone()
    with conn.cursor(row_factory=dict_row) as cur:
        packs = cur.execute("SELECT DISTINCT ON (name) name, version, digest FROM pack "
                            "ORDER BY name, loaded_at DESC, version DESC").fetchall()
        counts = cur.execute(
            "SELECT (SELECT count(*) FROM atom) AS atoms, (SELECT count(*) FROM entity) AS entities, "
            "(SELECT count(*) FROM object) AS objects, (SELECT count(*) FROM link WHERE retired_at IS NULL) AS links, "
            "(SELECT count(*) FROM review_item WHERE state = ANY(%s)) AS review_open", (list(REVIEW_OPEN),)).fetchone()
    review_open = counts.pop("review_open")
    return {"base_id": row[0] if row else None, "name": db.base_name(conn), "amem_version": __version__,
            "packs": packs, "counts": counts, "review_open": review_open}


def base_rename(conn: psycopg.Connection, name, *, agent: str) -> dict:
    """Base после смены имени базы (db.set_base_name); имя меняет только человек, как и структуру папок."""
    if not isinstance(agent, str) or not agent.startswith("person:"):
        raise Forbidden(f"имя базы меняет только человек (person:), а не {agent}: имя видят все, кто работает "
                        f"с базой")
    db.set_base_name(conn, _str(name, "name"))
    return base(conn)


def backup_list(backup_dir: Path) -> list[dict]:
    """Backup[]: готовые копии по времени — имя, время, размер; пути на диске наружу не отдаются."""
    return [{"name": b["name"], "created_at": b["created_at"], "size": b["size"]}
            for b in backup.backups(Path(backup_dir))]


# --- запись: кто вправе ---

def _person_only(agent: str, what: str) -> None:
    """Структуру папок меняет человек; модель раскладывает записи (перенос записи — порядок, а не утверждение)."""
    if not isinstance(agent, str) or not agent.startswith("person:"):
        raise Forbidden(f"{what} только человек (person:), а не {agent}: модель переносит записи по папкам "
                        f"(PATCH /records/{{ref}}/folder, amemo_move)")


# --- папки ---

def _folder_path(value, name: str) -> str:
    """Путь папки из тела или пути запроса: строка без NUL; правила пути проверяет folders.check (422)."""
    if value is None:
        raise BadRequest(f"{name}: нужен путь папки")
    return _str(value, name)


def folder_create(conn: psycopg.Connection, path, *, agent: str) -> dict:
    """Folder: новая пустая папка в реестре (с родителями); уже есть — FolderError exists (409)."""
    _person_only(agent, "папки создаёт")
    made = folders.create(conn, _folder_path(path, "path"), agent=agent)
    return {"path": made["path"], "name": made["name"], "count": 0, "children": []}


def folder_delete(conn: psycopg.Connection, path, *, agent: str) -> None:
    """Удалить пустую папку; с записями или вложенными — FolderError not_empty (409), нет такой — not_found (404)."""
    _person_only(agent, "папки удаляет")
    folders.delete(conn, _folder_path(path, "path"))


def folder_rename(conn: psycopg.Connection, path, new_path, *, agent: str) -> dict:
    """FolderRenamed: папка с вложенными и записями — на новый путь; занятый путь — FolderError exists (409)."""
    _person_only(agent, "папки переименовывает")
    return folders.rename(conn, _folder_path(path, "path"), _folder_path(new_path, "path (новый путь)"),
                          agent=agent)


def record_folder(conn: psycopg.Connection, ref, folder, *, agent: str) -> dict:
    """RecordSummary записи после переноса в папку folder (None — без папки); ревизии перенос не создаёт.
    Переносить вправе и модель: это порядок одной базы (спецификация 4, разд. 1.1), — но только в уже
    существующую папку: новые папки (move добавляет путь и родителей в реестр) создаёт человек."""
    ref, folder = _ref(ref), _str(folder, "folder")
    if folder is not None and not (isinstance(agent, str) and agent.startswith("person:")) \
            and not folders.exists(conn, folder):
        raise folders.FolderError(f"папки {folders.check(folder)!r} нет: модель переносит записи только в "
                                  f"существующие папки, новую создаёт человек", code="not_found")
    moved = folders.move(conn, ref, folder, agent=agent)
    return _summaries(conn, [lookup.summary(conn, moved["ref"], lang=lang.current())])[0]


# --- очередь проверки ---

REVIEW_LIMIT = 500                  # пунктов в ответе списка, не больше
STATS_DAYS = 36500                  # окно метрик, дней: дальше начало окна уходит за пределы дат
OUTCOMES = tuple(sorted(review.HUMAN_OUTCOMES | review.MODEL_OUTCOMES))
COMPARED = ("edit", "imported")     # у пункта этих причин — текущая и предложенная ревизии


def _item_id(value) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(_str(value, "id") or "")
    except ValueError:
        raise BadRequest(f"id {value!r}: нужен UUID пункта очереди") from None


def review_items(conn: psycopg.Connection, *, state=None, reason=None, record=None, limit=None) -> list[dict]:
    """ReviewItem[] по времени постановки: фильтры state, reason и record (atm:/ent: с UUID или ключом, UUID)."""
    record = _str(record, "record") or None
    if record is not None and not _REF.fullmatch(record):
        try:
            uuid.UUID(record)
        except ValueError:
            raise BadRequest(f"record {record!r}: нужна ссылка atm:/ent: (UUID или ключ) или UUID записи") from None
    rows = review.items(conn, state=_enum(state, "state", review.STATES),
                        reason=_enum(reason, "reason", review.REASONS), record=record,
                        limit=_int(limit, "limit", low=1, high=REVIEW_LIMIT, default=100))
    sources, abouts = _item_context(conn, rows)
    labels = _labels(conn, [row["ref"] for row in rows] + [ref for refs in abouts.values() for ref in refs])
    return [_review_item(row, labels, sources[row["id"]], abouts[row["id"]]) for row in rows]


def review_claim(conn: psycopg.Connection, *, agent: str, reasons=None, limit=None) -> list[dict]:
    """Захватить самые старые пункты, которые агент вправе решать (review.claim; модель — только semantic и не свой
    пакет): ReviewItem и то, что нужно для решения, — revision (номер ревизии пункта), payload и sources с итогами
    сверки. Пусто — решать нечего."""
    rows = review.claim(conn, agent=agent, reasons=_codes(reasons, "reason"),
                        limit=_int(limit, "limit", low=1, high=REVIEW_LIMIT, default=1))
    labels = _labels(conn, [row["ref"] for row in rows])
    return [{**_review_item(row, labels), "revision": row["n"], "payload": row["payload"],
             "sources": _jsonable(row["sources"])} for row in rows]


def review_release(conn: psycopg.Connection, item_id, *, agent: str) -> dict:
    """Вернуть захваченный пункт в очередь (review.release): вернуть может только тот, кто его держит; {id, state}."""
    iid = _item_id(item_id)
    review.release(conn, iid, agent=agent)
    return {"id": str(iid), "state": "queued"}


def _revision(conn: psycopg.Connection, target: str, revision_id) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(f"SELECT r.n, r.payload, r.review_state, r.recorded_at, cs.agent FROM {target}_revision r "
                          f"JOIN changeset cs ON cs.id = r.changeset_id WHERE r.id = %s", (revision_id,)).fetchone()
    return {"revision": row["n"], "payload": row["payload"], "review_state": row["review_state"],
            "recorded_at": row["recorded_at"].isoformat(), "agent": row["agent"]}


def review_item(conn: psycopg.Connection, item_id) -> dict:
    """ReviewItemView: пункт, его запись (RecordView) и что сравнивать. У edit и imported — current (текущая ревизия
    записи, null — текущей нет) и proposed (ревизия пункта, с changes — отличиями от текущей, пути RFC 6901);
    у source_changed — versions: объекты с прежними версиями (from) и новой (to)."""
    row = review.item(conn, _item_id(item_id))
    t = row["target"]
    view = {"item": _review_item(row, _labels(conn, [row["ref"]])), "record": record(conn, row["ref"]),
            "current": None, "proposed": None, "versions": None}
    if row["reason"] in COMPARED:
        current = conn.execute(f"SELECT id FROM {t}_current WHERE {t}_id = %s", (row["record_id"],)).fetchone()
        view["current"] = _revision(conn, t, current[0]) if current else None
        view["proposed"] = _revision(conn, t, row["revision_id"])
        if view["current"] is not None:
            view["proposed"]["changes"] = recipes.diff(view["current"]["payload"], view["proposed"]["payload"])
    elif row["reason"] == "source_changed":
        changed = [o for o in (row["details"] or {}).get("objects", []) if isinstance(o, dict)]
        ids = [str(o["object"]).removeprefix("obj:") for o in changed if o.get("object")]
        names = dict(conn.execute("SELECT id::text, coalesce(original_name, url) FROM object "
                                  "WHERE id = ANY(%s::uuid[])", (ids,)).fetchall()) if ids else {}
        objects_ = []
        for o in changed:
            object_id = str(o.get("object", "")).removeprefix("obj:")
            entry = {"object": object_id}
            if names.get(object_id):
                entry["object_name"] = names[object_id]
            objects_.append({**entry, "from": o.get("from", []), "to": o.get("to")})
        view["versions"] = {"objects": objects_}
    return view


def _number(value, name: str, *, low: float, high: float) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise BadRequest(f"{name} {value!r}: нужно число от {low:g} до {high:g}")
    return float(value)


def _note(note) -> str | None:
    """Пояснение решения или пункта: скрытое в <private> вырезается (в ответе предупреждений нет — так и в
    контракте); пустое — None."""
    note = _str(note, "note")
    return (private.strip(note) or None) if note is not None else None


def review_resolve(conn: psycopg.Connection, item_id, *, agent: str, outcome, note=None, confidence=None) -> dict:
    """Решить пункт: verification_id, статус записи после решения и id новых пунктов (queued). Права — библиотека:
    человек решает всё (confirmed, refuted), модель — только semantic, не свой пакет и с уверенностью confidence."""
    iid = _item_id(item_id)
    if outcome in (None, ""):
        raise BadRequest(f"outcome: нужен исход — {', '.join(OUTCOMES)}")
    result = review.resolve(conn, iid, _enum(outcome, "outcome", OUTCOMES), agent=agent,
                            confidence=_number(confidence, "confidence", low=0, high=1),
                            note=_note(note))
    return {"verification_id": str(result["verification_id"]), "status": result["status"],
            "queued": [str(q["id"]) for q in result["queued"]]}


def review_enqueue(conn: psycopg.Connection, *, agent: str, ref, reason, note=None) -> dict:
    """Поставить пункт audit или calibration на текущую ревизию записи (только человек); {item_id}."""
    if reason in (None, ""):
        raise BadRequest(f"reason: нужна причина — {', '.join(review.MANUAL_REASONS)}")
    item_id = review.enqueue(conn, _ref(ref), _enum(reason, "reason", review.MANUAL_REASONS), agent=agent,
                             note=_note(note))
    return {"item_id": str(item_id)}


def review_stats(conn: psycopg.Connection, *, days=None) -> dict:
    """ReviewStats: review.stats за days дней; итоги сверки источников — verdicts (sources библиотеки)."""
    stats = review.stats(conn, days=_int(days, "days", low=1, high=STATS_DAYS, default=7))
    return {"now": stats["now"], "days": stats["days"], "queue": stats["queue"], "done": stats["done"],
            "changesets": stats["changesets"], "records": stats["records"], "verdicts": stats["sources"],
            "audit": stats["audit"]}


# --- задачи агентам ---

TASK_LIMIT = tasks.LIST_MAX         # задач в ответе списка по умолчанию: у GET /tasks нет limit
TASK_NOTE_MAX = 4000                # знаков в заметке задачи (столбец task.note — тот же предел)
TASK_RESULT_MAX = 64 << 10          # байт итога задачи в JSON: ссылки записей и короткая заметка


def task_view(task: dict, *, full: bool = False) -> dict:
    """TaskView контракта; full — ещё когда поставлена и закрыта и итог (ответы MCP: агенту они нужны, вебу
    контракт их не обещает)."""
    view = {"id": str(task["id"]), "kind": task["kind"], "object": str(task["object_id"]),
            "version": task["version"], "note": task["note"], "state": task["state"],
            "created_by": task["created_by"], "claimed_by": task["claimed_by"],
            "claimed_until": _iso(task["claimed_until"])}
    if full:
        view.update(created_at=_iso(task["created_at"]), done_at=_iso(task["done_at"]), result=task["result"])
    return view


def _task_id(value) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(_str(value, "task_id") or "")
    except ValueError:
        raise BadRequest(f"task_id {value!r}: нужен UUID задачи") from None


def task_create(conn: psycopg.Connection, *, agent: str, kind, object, version, note=None) -> tuple[dict, bool]:
    """Поставить задачу ({task_id}, создана ли): незакрытая задача на ту же версию уже есть — её id. Ставят человек
    и модель; объект — UUID или obj:<UUID>, версия — её номер."""
    if kind in (None, ""):
        raise BadRequest(f"kind: нужен вид задачи — {', '.join(tasks.KINDS)}")
    kind = _enum(kind, "kind", tasks.KINDS)
    if object in (None, ""):
        raise BadRequest("object: нужен id объекта")
    if version is None:
        raise BadRequest("version: нужен номер версии объекта")
    note = _note(note)
    if note is not None and len(note) > TASK_NOTE_MAX:
        raise BadRequest(f"note: больше {TASK_NOTE_MAX} знаков")
    task, created = tasks.create(conn, kind, _object_id(object), _int(version, "version", low=1, high=VERSION_MAX),
                                 agent=agent, note=note)
    return {"task_id": str(task["id"])}, created


def task_list(conn: psycopg.Connection, *, state=None, object=None, limit=None, agent: str | None = None,
              full: bool = False) -> list[dict]:
    """TaskView[] от новых к старым: фильтры state (без него — только незакрытые) и object; agent — свободные и
    взятые им (amemo_tasks)."""
    object = _str(object, "object") or None
    rows = tasks.list_(conn, state=_enum(state, "state", tasks.STATES),
                       object_id=_object_id(object) if object is not None else None, agent=agent,
                       limit=_int(limit, "limit", low=1, high=tasks.LIST_MAX, default=TASK_LIMIT))
    return [task_view(row, full=full) for row in rows]


def task_claim(conn: psycopg.Connection, task_id=None, *, agent: str, kind=None) -> dict | None:
    """Взять задачу (только модель): названную или самую старую свободную; None — свободных нет."""
    task = tasks.claim(conn, None if task_id in (None, "") else _task_id(task_id), agent=agent,
                       kind=_enum(kind, "kind", tasks.KINDS))
    return task_view(task, full=True) if task is not None else None


def task_release(conn: psycopg.Connection, task_id, *, agent: str) -> dict:
    """Вернуть взятую задачу (только тот, кто держит)."""
    return task_view(tasks.release(conn, _task_id(task_id), agent=agent), full=True)


def task_done(conn: psycopg.Connection, task_id, *, agent: str, result=None) -> dict:
    """Закрыть взятую задачу с итогом result (объект JSON): {task, warnings}. <private> вырезается
    (private_removed), строка, похожая на секрет, записывается как есть с предупреждением secret_like — как у submit."""
    warnings: list[dict] = []
    if result is not None:
        if not isinstance(result, dict):
            raise BadRequest("result: нужен объект JSON, например {\"refs\": [\"atm:…\"], \"note\": \"…\"}")
        removed: list[str] = []
        found: list[tuple[str, list[str]]] = []
        result = _scrub(result, "result", removed, strip=True, secrets=found)
        if len(json.dumps(result, ensure_ascii=False).encode()) > TASK_RESULT_MAX:
            raise BadRequest(f"result: больше {TASK_RESULT_MAX // 1024} КиБ — оставьте ссылки записей и короткую "
                             f"заметку")
        warnings = _private_removed("result", removed) + _secret_like("result", found)
    task = task_view(tasks.done(conn, _task_id(task_id), agent=agent, result=result), full=True)
    return {"task": task, "warnings": warnings}


def task_cancel(conn: psycopg.Connection, task_id, *, agent: str) -> dict:
    """Отменить незакрытую задачу: тот, кто поставил, или человек."""
    return task_view(tasks.cancel(conn, _task_id(task_id), agent=agent), full=True)


# --- submit ---

BODY_DEPTH = 64                     # вложенность тела записи, не больше: тело атома — единицы уровней
PRIVATE_REMOVED = "private_removed"
SECRET_LIKE = "secret_like"           # строка похожа на секрет (private.secret_like): предупреждение, не отказ


def _scrub(value, where: str, removed: list[str], *, strip: bool, path: str = "", depth: int = 0,
           secrets: list[tuple[str, list[str]]] | None = None):
    """Копия значения JSON: строки — после private.strip (strip), путь изменённой — в removed; путь строки, похожей
    на секрет (private.secret_like по оставшемуся тексту), и виды — в secrets. NUL в строке или ключе, метка <private>
    в ключе и вложенность глубже BODY_DEPTH — BadRequest (до проверки и базы)."""
    if depth > BODY_DEPTH:
        raise BadRequest(f"{where}: вложенность глубже {BODY_DEPTH} уровней")
    place = f"{where}.{path}" if path else where
    if isinstance(value, str):
        out = private.strip(value) if strip else value
        if out != value:
            removed.append(path)
        if "\x00" in out:
            raise BadRequest(f"{place}: знак NUL (\\x00) в строке не допускается")
        if secrets is not None and (kinds := private.secret_like(out)):
            secrets.append((path, kinds))
        return out
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if "\x00" in key:
                raise BadRequest(f"{place}: знак NUL (\\x00) в имени поля не допускается")
            if private.marked(key):              # сам ключ в ответ не попадает: в нём и есть скрытое
                raise BadRequest(f"{place}: имя поля с меткой <private> не допускается — скрытое в имени поля "
                                 f"не вырезать; уберите метку из имени")
            out[key] = _scrub(item, where, removed, strip=strip, path=f"{path}.{key}" if path else key,
                              depth=depth + 1, secrets=secrets)
        return out
    if isinstance(value, list):
        return [_scrub(item, where, removed, strip=strip, path=f"{path}[{i}]", depth=depth + 1, secrets=secrets)
                for i, item in enumerate(value)]
    return value


def _private_removed(ref: str, paths: list[str]) -> list[dict]:
    return [{"code": PRIVATE_REMOVED, "severity": "warning", "ref": ref, "path": path,
             "message": "Скрытое в <private>…</private> вырезано: в ревизию оно не попало"} for path in paths]


SECRET_KINDS = {"aws_access_key": "ключ AWS", "github_token": "токен GitHub", "api_key": "ключ API (sk-…)",
                "slack_token": "токен Slack", "google_api_key": "ключ Google API", "stripe_key": "ключ Stripe",
                "amemo_token": "токен amemo", "private_key": "приватный ключ PEM", "jwt": "токен JWT",
                "url_password": "пароль в строке подключения", "password": "пароль"}


def _secret_like(ref: str, found: list[tuple[str, list[str]]]) -> list[dict]:
    """Предупреждения secret_like: поле, похожее на секрет, и вид; самого значения в ответе нет."""
    return [{"code": SECRET_LIKE, "severity": "warning", "ref": ref, "path": path,
             "message": f"Похоже на секрет ({', '.join(SECRET_KINDS.get(k, k) for k in kinds)}): значение записано "
                        f"как есть — если это секрет, исправьте запись; скрыть при записи можно меткой "
                        f"<private>…</private>"} for path, kinds in found]


def _proposal_label(label: str) -> str:
    """Метка предложения для ответа службы: @имя как есть; items[i] проверки — proposals[i], как в теле /submit."""
    return "proposals" + label.removeprefix("items") if re.fullmatch(r"items\[[0-9]+\]", label) else label


def _issue(issue: dict) -> dict:
    """CheckIssue из замечания отчёта amem.check/1: where «@a: sources[0].quote» → ref «@a» и path
    «sources[0].quote»; у замечания о записи целиком path — пустая строка; items[i] — proposals[i]."""
    ref, _, path = issue["where"].partition(": ")
    return {"code": issue["code"], "severity": issue["severity"], "message": issue["message"],
            "ref": _proposal_label(ref), "path": path}


def submit(conn: psycopg.Connection, store: ObjectStore, docs: Path | None, *, agent: str, proposals, links=None,
           reason=None, activity: uuid.UUID | None = None, provider=None) -> dict:
    """Submitted: check.submit пакета от агента сессии (агент в теле не принимается — его здесь и нет).

    proposals — [{target, payload, record_id?}], links — тела связей, reason — причина пакета. Строки тел и reason
    проходят private.strip до проверки: вырезанное не попадает в ревизию, о каждом поле — предупреждение
    private_removed в warnings (ref — @имя записи или proposals[i], links[i]; path — путь поля). Строка, похожая
    на секрет (private.secret_like), записывается как есть, с предупреждением secret_like без значения. Отказ
    проверки — CheckRejected (422) с issues; ошибка провайдера эмбеддингов только ослабляет уровень 4 (degraded
    отчёта)."""
    if not isinstance(proposals, list) or not proposals:
        raise BadRequest("proposals: нужен непустой список предложений [{target, payload, record_id?}]")
    links = [] if links is None else links
    if not isinstance(links, list):
        raise BadRequest("links: нужен список тел связей")
    warnings: list[dict] = []
    names: set[str] = set()
    items = []
    for i, proposal in enumerate(proposals):
        where = f"proposals[{i}]"
        if not isinstance(proposal, dict):
            raise BadRequest(f"{where}: нужен объект {{target, payload, record_id?}}")
        payload, target = proposal.get("payload"), _str(proposal.get("target"), f"{where}.target")
        ref = payload.get("ref") if isinstance(payload, dict) else None
        named = isinstance(ref, str) and level1.NAME.fullmatch(ref) is not None
        label = ref if named and ref not in names else f"proposals[{i}]"   # @имя — по правилу уровня 1 проверки
        if named and target in TARGETS:
            names.add(ref)
        removed: list[str] = []
        found: list[tuple[str, list[str]]] = []
        payload = _scrub(payload, f"{where}.payload", removed, strip=True, secrets=found)
        warnings += _private_removed(label, removed) + _secret_like(label, found)
        record_id = _scrub(proposal.get("record_id"), f"{where}.record_id", [], strip=False)
        items.append(check.Proposal(target=target, payload=payload, record_id=record_id))
    bodies = []
    for i, link in enumerate(links):
        removed, found = [], []
        bodies.append(_scrub(link, f"links[{i}]", removed, strip=True, secrets=found))
        warnings += _private_removed(f"links[{i}]", removed) + _secret_like(f"links[{i}]", found)
    if _str(reason, "reason") is not None:
        cleaned = private.strip(reason)
        if cleaned != reason:
            warnings += _private_removed("", ["reason"])
        if kinds := private.secret_like(cleaned):
            warnings += _secret_like("", [("reason", kinds)])
        reason = cleaned or None
    result = check.submit(conn, store, docs, items, bodies, agent=agent, activity=activity, reason=reason,
                          provider=provider, on_semantic_error="skip")
    if result.state == "rejected":
        issues = [_issue(issue) for issue in result.report["issues"]]
        errors = [issue for issue in issues if issue["severity"] == "violation"]
        first = errors[0] if errors else None
        message = f"пакет отклонён автопроверкой: ошибок {len(errors)}"
        if first is not None:
            message += f"; первая — {first['ref']}{': ' + first['path'] if first['path'] else ''}: {first['message']}"
        raise CheckRejected(message, changeset_id=str(result.changeset_id), issues=issues, warnings=warnings)
    written = []
    targets = {}
    for rec in result.records:
        ref = f"{records.PREFIX[rec['target']]}:{rec['record_id']}"
        targets[rec["record_id"]] = rec["target"]
        written.append({"label": _proposal_label(rec["label"]), "ref": ref, "target": rec["target"],
                        "record_id": str(rec["record_id"]), "revision_id": str(rec["revision_id"]),
                        "created": rec["created"], "status": rec["status"], "review_state": rec["review_state"]})
    queued = [{"id": str(q["id"]), "reason": q["reason"], "label": _proposal_label(q["label"]),
               "ref": f"{records.PREFIX[targets[q['record_id']]]}:{q['record_id']}",
               "record_id": str(q["record_id"])} for q in result.queued]
    return {"changeset_id": str(result.changeset_id), "complete": result.complete, "records": written,
            "queued": queued, "report": _report(result.report), "warnings": warnings}


def _report(report: dict) -> dict:
    """Отчёт amem.check/1 для ответа: метки items[i] в where замечаний и в label записей — proposals[i], как в
    records, queued и 422 (в changeset.check_report отчёт остаётся как записан)."""
    def where(text: str) -> str:
        head, sep, rest = text.partition(": ")
        return _proposal_label(head) + sep + rest
    out = dict(report)
    out["issues"] = [{**issue, "where": where(issue["where"])} for issue in report.get("issues", [])]
    if "records" in report:
        out["records"] = [{**rec, "label": _proposal_label(rec["label"])} for rec in report["records"]]
    return out


# --- подборки (AMEMO_STATE/bundles, AMEMO_STATE/uploads) ---
#
# Экспорт и загрузка лежат в папке состояния службы: <state>/bundles/<id>/ (bundle.zip, у антологии report.html)
# и <state>/uploads/<id>/bundle (распакованная один раз загрузка); id — UUIDv7, по нему ищется только своя
# папка. meta.json пишется последним: папка без него — недописанная и не видна. В meta.json — владелец (кто сделал или загрузил: агент локальной
# службы или токен общей), время создания и имя файла для скачивания. Чужая подборка отвечает так же, как
# несуществующая (Missing, 404), — о чужом не сообщается даже то, что оно есть.
#
# Срок хранения — BUNDLE_TTL (24 часа) от создания. Старое удаляет sweep: служба зовёт его при запуске и раз в час,
# а обращение к просроченной подборке удаляет её сразу (Missing) — срок не зависит от того, успел ли пройти sweep.
# Часы — _now(): время создания пишется по ним же, и тесты подменяют их. Отрицательный возраст (часы ушли назад)
# не считается просрочкой.
#
# Предел места (quota, AMEMO_STATE_QUOTA) — на владельца: его живые подборки и загрузки вместе (state_usage). Экспорт
# и загрузка, после которых занятое превысило бы предел, удаляют сделанное и отвечают QuotaExceeded (507); служба
# ещё и обрывает приём загрузки, как только файл перерос остаток (upload_room). Одновременные запросы одного
# владельца могут вместе ненадолго перешагнуть предел — он защищает диск от накопления, а не от гонки.

BUNDLE_TTL = 24 * 3600              # с; подборка и загрузка живут сутки
BUNDLES, UPLOADS = "bundles", "uploads"
BUNDLE_FILE, REPORT_FILE, META_FILE = "bundle.zip", "report.html", "meta.json"
UPLOAD_DIR = "bundle"               # распакованная загрузка: inspect и import_ читают её без второй распаковки
TITLE_MAX = 200                     # знаков в заголовке антологии
FILENAME_MAX = 100                  # знаков в имени файла для скачивания (без .zip)
SELECTION_FIELDS = ("tags", "project", "kinds", "entity_classes", "refs", "statuses", "since", "include_private")
_PART = re.compile(r"\.[0-9a-f-]{36}\.part")       # недокачанная загрузка: .<id>.part


def _now() -> float:
    return time.time()


def _jsonable(value):
    """Выдача библиотеки (UUID, datetime в глубине) — в типы JSON."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _state_id(value) -> str | None:
    """Канонический id подборки или загрузки; не UUID — None (ответ «нет такой», а не разбор чужого пути)."""
    if not isinstance(value, str) or "\x00" in value:
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


def _read_meta(folder: Path) -> dict | None:
    try:
        meta = json.loads((folder / META_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return meta if isinstance(meta, dict) else None


def _write_meta(folder: Path, meta: dict) -> None:
    """meta.json — последним и целиком (через временный файл): папка без него не видна."""
    part = folder / f".{META_FILE}.part"
    part.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    part.replace(folder / META_FILE)


def _expired(created, now: float) -> bool:
    return isinstance(created, (int, float)) and now - created > BUNDLE_TTL


def _remove(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        path.unlink(missing_ok=True)
    else:
        shutil.rmtree(path, ignore_errors=True)


def _stored(state: Path, kind: str, value, owner: str) -> tuple[Path, dict]:
    """Папка своей подборки (kind=BUNDLES) или загрузки (UPLOADS) и её meta; нет, чужая, просрочена — Missing."""
    what = "подборки" if kind == BUNDLES else "загрузки"
    missing = Missing(f"{what} {str(value)[:80]!r} нет: срок хранения — сутки, после него сделайте заново")
    bid = _state_id(value)
    if bid is None:
        raise missing
    folder = Path(state) / kind / bid
    if folder.is_symlink() or not folder.is_dir():
        raise missing
    meta = _read_meta(folder)
    if meta is None or not isinstance(meta.get("owner"), str) \
            or not hmac.compare_digest(meta["owner"].encode(), owner.encode()):
        raise missing
    if _expired(meta.get("created_at"), _now()):
        _remove(folder)
        raise missing
    return folder, meta


def _size(path: Path) -> int:
    """Байт в обычных файлах папки (без перехода по ссылкам); исчезнувшее по ходу — не считается."""
    total = 0
    for top, _, files in os.walk(path, followlinks=False):
        for name in files:
            try:
                total += os.lstat(os.path.join(top, name)).st_size
            except OSError:
                pass
    return total


def state_usage(state: Path, owner: str) -> int:
    """Сколько байт заняли живые подборки и загрузки владельца в <state>/bundles и <state>/uploads."""
    now, total = _now(), 0
    for kind in (BUNDLES, UPLOADS):
        try:
            entries = list((Path(state) / kind).iterdir())
        except OSError:
            continue
        for entry in entries:
            if _state_id(entry.name) != entry.name or entry.is_symlink() or not entry.is_dir():
                continue
            meta = _read_meta(entry)
            if meta is None or meta.get("owner") != owner or _expired(meta.get("created_at"), now):
                continue
            total += _size(entry)
    return total


def _mib(size: int) -> str:
    return f"{size / (1 << 30):.1f} ГиБ" if size >= 1 << 30 else f"{size / (1 << 20):.1f} МиБ"


def quota_exceeded(used: int, quota: int, what: str) -> QuotaExceeded:
    return QuotaExceeded(f"{what}: подборки и загрузки этого входа заняли бы больше предела {_mib(quota)} "
                         f"(уже занято {_mib(used)}); старые удаляются через сутки — подождите, сузьте отбор "
                         f"или увеличьте AMEMO_STATE_QUOTA")


def upload_room(state: Path, owner: str, quota: int | None) -> int | None:
    """Сколько байт ещё можно загрузить владельцу (None — предела нет); места нет — QuotaExceeded."""
    if quota is None:
        return None
    used = state_usage(state, owner)
    if used >= quota:
        raise quota_exceeded(used, quota, "загрузка подборки")
    return quota - used


def _within_quota(state: Path, owner: str, quota: int | None, folder: Path, what: str) -> None:
    """Новая папка folder (ещё без meta, в state_usage не входит) вместе с прочими — в пределе, иначе
    QuotaExceeded (папку удаляет вызывающий)."""
    if quota is None:
        return
    used = state_usage(state, owner)
    if used + _size(folder) > quota:
        raise quota_exceeded(used, quota, what)


def bundle_sweep(state: Path) -> int:
    """Удалить подборки и загрузки старше BUNDLE_TTL (и недописанные — по времени изменения); сколько удалено.
    Удаляются только свои имена (UUID, .<UUID>.part): чужие файлы в папке состояния не трогаются."""
    now, removed = _now(), 0
    for kind in (BUNDLES, UPLOADS):
        root = Path(state) / kind
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for entry in entries:
            if _state_id(entry.name) != entry.name and not _PART.fullmatch(entry.name):
                continue
            meta = None if entry.is_symlink() or not entry.is_dir() else _read_meta(entry)
            created = (meta or {}).get("created_at")
            if not isinstance(created, (int, float)):
                try:
                    created = entry.lstat().st_mtime
                except OSError:
                    continue
            if _expired(created, now):
                _remove(entry)
                removed += 1
    return removed


def _selection(value) -> bundle.Selection:
    """bundle.Selection из тела запроса (схема Selection): {} — вся база; неизвестное поле — BadRequest (опечатка
    в условии иначе тихо выгрузила бы всё)."""
    if value is None:
        raise BadRequest("selection: нужен объект отбора ({} — вся база)")
    if not isinstance(value, dict):
        raise BadRequest(f"selection: нужен объект, а не {type(value).__name__}")
    unknown = sorted(set(value) - set(SELECTION_FIELDS))
    if unknown:
        raise BadRequest(f"selection: неизвестные поля {', '.join(map(str, unknown))}; допустимы "
                         f"{', '.join(SELECTION_FIELDS)}")
    project = _str(value.get("project"), "selection.project")
    if project is not None and not _ref(project, "selection.project").startswith("ent:"):
        raise BadRequest(f"selection.project {project!r}: нужна сущность ent:<UUID или ключ>")
    lists = {name: tuple(_codes(value.get(name), f"selection.{name}") or ())
             for name in ("tags", "kinds", "entity_classes", "refs")}
    for ref in lists["refs"]:
        _ref(ref, "selection.refs")
    statuses = _codes(value.get("statuses"), "selection.statuses")
    unknown = sorted(set(statuses or ()) - set(STATUSES))
    if unknown:
        raise BadRequest(f"selection.statuses: неизвестные статусы {', '.join(unknown)}")
    return bundle.Selection(**lists, project=project, statuses=tuple(statuses or bundle.DEFAULT_STATUSES),
                            since=_moment(value.get("since"), "selection.since"),
                            include_private=_bool(value.get("include_private"), "selection.include_private",
                                                  default=False))


def _filename(title: str | None, bid: str) -> str:
    """Имя zip для скачивания: заголовок антологии без знаков, опасных в имени файла, иначе amemo-<id>."""
    name = unicodedata.normalize("NFC", title or "")
    name = "".join(ch if ch.isalnum() or ch in " -_.()" else "_" for ch in name)
    name = re.sub(r"_+", "_", re.sub(r"\s+", " ", name)).strip(" ._")[:FILENAME_MAX].strip(" ._")
    return f"{name or 'amemo-' + bid}.zip"


def bundle_export(conn: psycopg.Connection, store: ObjectStore, state: Path, *, agent: str, owner: str,
                  selection, with_files=None, with_packs=None, anthology=None, title=None,
                  quota: int | None = None) -> dict:
    """Подборка в <state>/bundles/<id>: bundle.export по selection или, с anthology, антология (anthology.export,
    title — заголовок отчёта). Ответ — id, summary (counts, packs по именам, with_files, with_packs, selection,
    created_at) и has_report; ссылки на скачивание и отчёт добавляет служба. Отказ библиотеки — BundleError.
    quota — предел места владельца (байт): подборка сверх него удаляется, QuotaExceeded."""
    sel = _selection(selection)
    files = _bool(with_files, "with_files", default=False)
    packs_ = _bool(with_packs, "with_packs", default=False)
    is_anthology = _bool(anthology, "anthology", default=False)
    title = _str(title, "title")
    if title is not None and len(title) > TITLE_MAX:
        raise BadRequest(f"title: длиннее {TITLE_MAX} знаков")
    if is_anthology and packs_:
        raise BadRequest("with_packs: антология пакеты не копирует — у получателя нужны те же пакеты")
    if quota is not None and (used := state_usage(state, owner)) >= quota:
        raise quota_exceeded(used, quota, "экспорт подборки")
    bid = str(uuid7())
    folder = Path(state) / BUNDLES / bid
    folder.mkdir(parents=True)
    try:
        if is_anthology:
            made = anthology_export(conn, store=store, folder=folder / BUNDLE_FILE, agent=agent, selection=sel,
                                    with_files=files, title=title or "Антология")
            manifest = made["manifest"]
            (folder / REPORT_FILE).write_text(made["report"], encoding="utf-8")
        else:
            manifest = bundle.export(conn, store=store, folder=folder / BUNDLE_FILE, selection=sel, agent=agent,
                                     with_files=files, with_packs=packs_)
        summary = _jsonable({"format": manifest["format"], "created_at": manifest["created_at"],
                             "counts": manifest["counts"], "packs": [p["name"] for p in manifest["packs"]],
                             "with_files": manifest["with_files"], "with_packs": manifest["with_packs"],
                             "selection": manifest["selection"], "anthology": is_anthology})
        _within_quota(state, owner, quota, folder, "экспорт подборки")
        _write_meta(folder, {"owner": owner, "created_at": _now(), "anthology": is_anthology,
                             "filename": _filename(title or ("Антология" if is_anthology else None), bid)})
    except BaseException:
        _remove(folder)
        raise
    return {"id": bid, "summary": summary, "has_report": is_anthology}


@dataclass(frozen=True)
class BundleFile:
    """Файл своей подборки для раздачи: путь и имя для скачивания."""
    path: Path
    filename: str


def bundle_download(state: Path, bundle_id, *, owner: str) -> BundleFile:
    """zip своей подборки; нет, чужая, просрочена — Missing (404)."""
    folder, meta = _stored(state, BUNDLES, bundle_id, owner)
    return BundleFile(folder / BUNDLE_FILE, meta.get("filename") or f"amemo-{folder.name}.zip")


def bundle_report(state: Path, bundle_id, *, owner: str) -> Path:
    """HTML-отчёт своей антологии; у обычной подборки отчёта нет — Missing (404)."""
    folder, _ = _stored(state, BUNDLES, bundle_id, owner)
    report = folder / REPORT_FILE
    if report.is_symlink() or not report.is_file():
        raise Missing(f"у подборки {folder.name} нет отчёта: он есть только у антологии (anthology: true)")
    return report


def upload_begin(state: Path) -> tuple[str, Path]:
    """id новой загрузки и временный файл для неё в <state>/uploads (.<id>.part): служба пишет туда тело потоком."""
    bid = str(uuid7())
    root = Path(state) / UPLOADS
    root.mkdir(parents=True, exist_ok=True)
    return bid, root / f".{bid}.part"


def upload_finish(state: Path, upload_id: str, part: Path, *, owner: str, quota: int | None = None) -> dict:
    """Принять докачанный файл загрузки: распаковать один раз в <state>/uploads/<id>/bundle (bundle.unpack — те же
    проверки архива), zip удалить, bundle.inspect по папке и записать владельца; import_ потом идёт по той же папке.
    Не подборка (не zip, нет манифеста, вредный архив) — BundleError (422), и загрузка удаляется. Распакованная
    загрузка сверх предела места владельца (quota) — QuotaExceeded, и она тоже удаляется."""
    folder = Path(state) / UPLOADS / upload_id
    try:
        folder.mkdir()
        root = bundle.unpack(part, folder / UPLOAD_DIR)
        Path(part).unlink()
        _within_quota(state, owner, quota, folder, "загрузка подборки")
        report = bundle.inspect(root)
        _write_meta(folder, {"owner": owner, "created_at": _now()})
    except BaseException:
        _remove(folder)
        Path(part).unlink(missing_ok=True)
        raise
    return {"upload_id": upload_id, "report": _jsonable(report)}


def bundle_import(conn: psycopg.Connection, store: ObjectStore, state: Path, upload_id, *, agent: str, owner: str,
                  trust=None, dry_run=None, can_write: bool = True) -> dict:
    """Imported: bundle.import_ своей загрузки. dry_run по умолчанию — да (план без записи). Настоящий импорт
    вливает только человек: он решает, чему из чужой базы верить; модель смотрит план (dry_run) — Forbidden (403).
    Вход только для чтения (can_write=False) смотрит план, настоящий импорт — ReadOnly (403 read_only)."""
    dry = _bool(dry_run, "dry_run", default=True)
    trust = _enum(trust, "trust", bundle.TRUST, default="keep")
    if not dry and not can_write:
        raise ReadOnly(f"вход {agent} — только для чтения: доступен пробный импорт (dry_run: true)")
    if not dry and not (isinstance(agent, str) and agent.startswith("person:")):
        raise Forbidden(f"подборку в базу вливает только человек (person:), а не {agent}: модели доступен "
                        f"пробный импорт (dry_run: true)")
    folder, _ = _stored(state, UPLOADS, upload_id, owner)
    result = bundle.import_(conn, store, folder / UPLOAD_DIR, agent=agent, trust=trust, dry_run=dry)
    out = {"changeset_id": str(result.changeset_id) if result.changeset_id is not None else None,
           "counts": result.counts, "queued": result.queued, "warnings": result.warnings,
           "collisions": result.collisions, "complete": result.complete}
    if result.report is not None:                 # отчёта уровня 1 нет — поля нет (в контракте он объект)
        out["report"] = result.report
    return _jsonable(out)
