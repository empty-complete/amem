"""Папки записей: порядок одной базы, а не утверждение о мире (спецификация подпроекта 4, разд. 1.1).

Папка — метаданные записи, как статус: столбец folder у atom и entity. Перенос не создаёт ревизию, content_hash
прежний; каждый перенос — строка неизменяемого журнала folder_log (откуда, куда, кто, когда). Пустые папки живут
в реестре folder; путь записи и его родители попадают в реестр при переносе. Переносить вправе и модель.

Путь — сегменты через «/»; каждый сегмент непустой после обрезки пробелов, без «/» и управляющих символов,
не «.» и не «..», в NFC, до 100 знаков; уровней — до 8. Регистр сохраняется, сравнение — как есть. Путь «-» запрещён:
в контракте HTTP он означает «без папки». Префикс в SQL — folder = p OR starts_with(folder, p || '/'), без LIKE:
«_» и «%» в имени папки — обычные знаки.

Блокировки:
1. автор — до блокировок, как во всех функциях записи (amem/records.py);
2. блокировка папок (рекомендательная, на транзакцию): перенос и создание берут её разделяемой и идут
   параллельно, удаление и переименование — исключительной. Иначе запись могла бы лечь в папку, которую в тот же
   миг удаляют (проверка «пусто» прошла до переноса), и остаться вне реестра;
3. записи — FOR NO KEY UPDATE (records._lock), у переименования — все записи папки по возрастанию id;
4. время — после блокировок и не раньше последнего изменения записи: журнал папки идёт по порядку, даже если
   часы ушли назад.
Соединение — только в режиме autocommit (db.connect). Ответы — словари, совместимые с JSON.
"""
from __future__ import annotations

import unicodedata
import uuid
from datetime import datetime, timezone

import psycopg

from . import records
from .ids import uuid7

MAX_DEPTH = 8
MAX_SEGMENT = 100
NO_FOLDER = "-"                     # в контракте HTTP — «без папки», поэтому имя папки такое быть не может
DEFAULTS = ("Проекты", "Области", "Ресурсы", "Архив")
INIT_AGENT = "model:amem-init"      # автор папок новой базы: их создаёт программа, а не человек
FOLDERS_LOCK = 0x616D656D00000003   # ключ pg_advisory_xact_lock папок: «amem» + 3
# управляющие символы, суррогаты, разделители строк и абзацев: в имени папки они невидимы или ломают строку
_FORBIDDEN = {"Cc", "Cs", "Zl", "Zp"}


class FolderError(ValueError):
    """Неверный путь или действие с папкой. code: invalid, exists, not_empty, not_found."""

    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def check(path) -> str:
    """Нормализованный путь папки (NFC, сегменты без пробелов по краям) или FolderError с кодом invalid."""
    if not isinstance(path, str):
        raise FolderError(f"путь папки {path!r}: нужна строка", code="invalid")
    segments = [unicodedata.normalize("NFC", raw.strip()) for raw in path.split("/")]
    if len(segments) > MAX_DEPTH:
        raise FolderError(f"папка {path!r}: {len(segments)} уровней, можно до {MAX_DEPTH}", code="invalid")
    for i, segment in enumerate(segments, 1):
        where = f"папка {path!r}, сегмент {i}"
        if not segment:
            raise FolderError(f"{where}: пустой (лишний «/» или одни пробелы)", code="invalid")
        if segment in (".", ".."):
            raise FolderError(f"{where}: «{segment}» — не имя папки", code="invalid")
        if any(unicodedata.category(ch) in _FORBIDDEN for ch in segment):
            raise FolderError(f"{where}: управляющий символ или перевод строки", code="invalid")
        if len(segment) > MAX_SEGMENT:
            raise FolderError(f"{where}: {len(segment)} знаков, можно до {MAX_SEGMENT}", code="invalid")
    normalized = "/".join(segments)
    if normalized == NO_FOLDER:
        raise FolderError(f"папка {path!r}: «-» означает «без папки» и именем папки быть не может", code="invalid")
    return normalized


def _ancestors(path: str) -> list[str]:
    """Путь и все его родители, от корня: «a/b/c» → a, a/b, a/b/c."""
    parts = path.split("/")
    return ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]


def _name(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _lock_folders(conn: psycopg.Connection, *, exclusive: bool) -> None:
    sql = "SELECT pg_advisory_xact_lock(%s)" if exclusive else "SELECT pg_advisory_xact_lock_shared(%s)"
    conn.execute(sql, (FOLDERS_LOCK,))


def _register(conn: psycopg.Connection, path: str, agent: str, at: datetime) -> bool:
    """Путь и его родители — в реестр; уже известные не трогаются. True — если появился сам путь."""
    *parents, leaf = _ancestors(path)
    for parent in parents:                  # от корня: два переноса с общим началом пути не встают в тупик
        conn.execute("INSERT INTO folder (path, created_at, created_by) VALUES (%s, %s, %s) "
                     "ON CONFLICT (path) DO NOTHING", (parent, at, agent))
    return conn.execute("INSERT INTO folder (path, created_at, created_by) VALUES (%s, %s, %s) "
                        "ON CONFLICT (path) DO NOTHING RETURNING path", (leaf, at, agent)).fetchone() is not None


def seed_defaults(conn: psycopg.Connection, at: datetime | None = None) -> None:
    """Четыре папки новой базы — в транзакции вызывающего (db.prepare: там же, где впервые ставится base_id)."""
    records._ensure_agent(conn, INIT_AGENT)
    at = at or _now()
    for path in DEFAULTS:
        _register(conn, path, INIT_AGENT, at)


def _records_in(conn: psycopg.Connection, path: str) -> list[tuple[str, uuid.UUID, str]]:
    """Записи папки и вложенных: (вид, id, папка), по возрастанию id."""
    found = []
    for target in ("atom", "entity"):
        found += [(target, rid, folder) for rid, folder in conn.execute(
            f"SELECT id, folder FROM {target} WHERE folder = %(p)s OR starts_with(folder, %(p)s || '/')",
            {"p": path})]
    return sorted(found, key=lambda row: row[1])


def _has_content(conn: psycopg.Connection, path: str) -> bool:
    """Есть ли в папке вложенные папки реестра или записи (и во вложенных)."""
    return conn.execute(
        "SELECT EXISTS (SELECT 1 FROM folder WHERE starts_with(path, %(p)s || '/')) "
        "OR EXISTS (SELECT 1 FROM atom WHERE folder = %(p)s OR starts_with(folder, %(p)s || '/')) "
        "OR EXISTS (SELECT 1 FROM entity WHERE folder = %(p)s OR starts_with(folder, %(p)s || '/'))",
        {"p": path}).fetchone()[0]


def _registered(conn: psycopg.Connection, path: str) -> bool:
    return conn.execute("SELECT EXISTS (SELECT 1 FROM folder WHERE path = %s)", (path,)).fetchone()[0]


def _known(conn: psycopg.Connection, path: str) -> bool:
    """Папка видна в дереве: она в реестре, или в ней (во вложенных) лежат записи."""
    return _registered(conn, path) or _has_content(conn, path)


def _record(conn: psycopg.Connection, ref) -> tuple[str, uuid.UUID]:
    """atm:/ent: с UUID или ключом → (вид, id); нет записи или не та ссылка — RecordError."""
    if not isinstance(ref, str) or ":" not in ref or ref.split(":", 1)[0] not in records.TARGET:
        raise records.RecordError(f"ref {ref!r}: нужна ссылка atm:<UUID или ключ> или ent:<UUID или ключ>")
    prefix, value = records.resolve_ref(conn, ref, {}).split(":", 1)
    return records.TARGET[prefix], uuid.UUID(value)


def _log(conn, target: str, record_id: uuid.UUID, before: str | None, after: str | None, agent: str,
         at: datetime) -> None:
    conn.execute(f"UPDATE {target} SET folder = %s WHERE id = %s", (after, record_id))
    conn.execute("INSERT INTO folder_log (id, target, record_id, folder_from, folder_to, agent, changed_at) "
                 "VALUES (%s, %s, %s, %s, %s, %s, %s)", (uuid7(), target, record_id, before, after, agent, at))


def move(conn: psycopg.Connection, ref: str, folder: str | None, *, agent: str) -> dict:
    """Переложить запись в папку (None — «без папки») без новой ревизии; та же папка — ничего не меняется."""
    records._require_autocommit(conn)
    path = check(folder) if folder is not None else None
    target, record_id = _record(conn, ref)
    with conn.transaction():
        records._ensure_agent(conn, agent)
        _lock_folders(conn, exclusive=False)
        last = records._lock(conn, target, record_id)
        at = max(_now(), last)
        before = conn.execute(f"SELECT folder FROM {target} WHERE id = %s", (record_id,)).fetchone()[0]
        if before != path:
            if path is not None:
                _register(conn, path, agent, at)
            _log(conn, target, record_id, before, path, agent, at)
    return {"ref": f"{records.PREFIX[target]}:{record_id}", "from": before, "to": path, "moved": before != path}


def create(conn: psycopg.Connection, path: str, *, agent: str) -> dict:
    """Папка в реестре (с родителями). Уже есть — FolderError с кодом exists."""
    records._require_autocommit(conn)
    path = check(path)
    with conn.transaction():
        records._ensure_agent(conn, agent)
        _lock_folders(conn, exclusive=False)
        at = _now()
        # RETURNING ловит и папку, которую в этот миг создал соседний create
        if _known(conn, path) or not _register(conn, path, agent, at):
            raise FolderError(f"папка {path!r} уже есть", code="exists")
    return {"path": path, "name": _name(path), "created_at": at.isoformat(), "created_by": agent}


def delete(conn: psycopg.Connection, path: str) -> dict:
    """Удалить пустую папку: без вложенных папок и без записей, иначе FolderError с кодом not_empty."""
    records._require_autocommit(conn)
    path = check(path)
    with conn.transaction():
        _lock_folders(conn, exclusive=True)
        if _has_content(conn, path):
            raise FolderError(f"папка {path!r} не пуста: в ней есть записи или вложенные папки", code="not_empty")
        if conn.execute("DELETE FROM folder WHERE path = %s RETURNING path", (path,)).fetchone() is None:
            raise FolderError(f"папки {path!r} нет", code="not_found")
    return {"path": path}


def rename(conn: psycopg.Connection, path: str, new_path: str, *, agent: str) -> dict:
    """Переименовать (перенести) папку вместе с вложенными и записями; по строке folder_log на запись.

    Занятый новый путь (и сам прежний) — exists; перенос в собственного потомка или путь глубже 8 уровней
    у вложенной папки — invalid; нет такой папки — not_found. Папки реестра сохраняют автора и время создания."""
    records._require_autocommit(conn)
    old, new = check(path), check(new_path)
    if new.startswith(old + "/"):
        raise FolderError(f"папку {old!r} нельзя перенести в её же вложенную {new!r}", code="invalid")
    with conn.transaction():
        records._ensure_agent(conn, agent)
        _lock_folders(conn, exclusive=True)
        if not _known(conn, old):
            raise FolderError(f"папки {old!r} нет", code="not_found")
        if _known(conn, new):
            raise FolderError(f"папка {new!r} уже есть", code="exists")
        listed = [row[0] for row in conn.execute(
            "SELECT path FROM folder WHERE path = %(p)s OR starts_with(path, %(p)s || '/') ORDER BY path", {"p": old})]
        found = _records_in(conn, old)
        renamed = {}
        for before in {*listed, *(folder for _, _, folder in found)}:
            after = new + before[len(old):]
            try:
                renamed[before] = check(after)
            except FolderError as e:
                raise FolderError(f"переименование {old!r} → {new!r}: папка {before!r} стала бы {after!r} — {e}",
                                  code="invalid") from e
        # записи — по возрастанию id, как в records.commit: с пакетами по тем же записям тупика нет
        marks = [records._lock(conn, target, record_id) for target, record_id, _ in found]
        at = max([_now(), *marks])
        for before in listed:
            conn.execute("UPDATE folder SET path = %s WHERE path = %s", (renamed[before], before))
        for after in sorted({new, *renamed.values()}, key=_order):
            _register(conn, after, agent, at)    # родители нового пути и пути записей, которых не было в реестре
        for target, record_id, before in found:
            _log(conn, target, record_id, before, renamed[before], agent, at)
    return {"from": old, "to": new, "folders": len(listed), "records": len(found)}


def _order(path: str) -> tuple:
    """Порядок по имени: без учёта регистра, при равенстве — как есть; родитель раньше детей."""
    return tuple((segment.casefold(), segment) for segment in path.split("/"))


def tree(conn: psycopg.Connection) -> dict:
    """Дерево папок: реестр вместе с путями записей. count — по вложенности (запись в a/b учтена и в a).

    Ответ: folders (path, name, count, children — по имени), unfiled — записи без папки, total — все записи."""
    # одним запросом — один снимок: реестр и счётчики не расходятся
    rows = conn.execute(
        "SELECT path, 0::bigint FROM folder UNION ALL "
        "SELECT folder, count(*) FROM (SELECT folder FROM atom UNION ALL SELECT folder FROM entity) r GROUP BY folder"
    ).fetchall()
    counts: dict[str, int] = {}
    unfiled = total = 0
    for path, n in rows:
        total += n
        if path is None:
            unfiled += n
            continue
        for p in _ancestors(path):
            counts[p] = counts.get(p, 0) + n
    nodes = {p: {"path": p, "name": _name(p), "count": counts[p], "children": []} for p in sorted(counts, key=_order)}
    roots = []
    for p, node in nodes.items():
        parent = p.rpartition("/")[0]
        (nodes[parent]["children"] if parent else roots).append(node)
    return {"folders": roots, "unfiled": unfiled, "total": total}
