"""Папки записей: порядок одной базы, а не утверждение о мире (спецификация подпроекта 4, разд. 1.1).

Папка — метаданные записи, как статус: столбец folder у atom и entity. Перенос не создаёт ревизию, content_hash
прежний; каждый перенос — строка неизменяемого журнала folder_log (откуда, куда, кто, когда). Пустые папки живут
в реестре folder; путь записи и его родители попадают в реестр при переносе. Переносить вправе и модель.

Путь — сегменты через «/»; каждый сегмент непустой после обрезки пробелов, без «/», управляющих и невидимых знаков
форматирования (кроме ZWJ и ZWNJ — они нужны письменностям), не «.», «..» и не «-», в NFC, до 100 знаков; уровней —
до 8. Сегмент «-» запрещён в любом месте: путь «-» в контракте HTTP означает «без папки», а папку «-/x» нельзя было бы
ни показать, ни удалить. Регистр сохраняется, сравнение — как есть (столбцы путей — COLLATE "C"). Префикс в SQL —
folder = p OR starts_with(folder, p || '/'), без LIKE: «_» и «%» в имени папки — обычные знаки; при COLLATE "C" он идёт
по индексу.

Блокировки:
1. автор — до блокировок, как во всех функциях записи (amemo/records.py);
2. блокировка папок (рекомендательная, на транзакцию): перенос и создание берут её разделяемой и идут
   параллельно, удаление и переименование — исключительной. Иначе запись могла бы лечь в папку, которую в тот же
   миг удаляют (проверка «пусто» прошла до переноса), и остаться вне реестра;
3. записи — FOR NO KEY UPDATE (records._lock), у переименования — все записи папки по возрастанию id одним
   проходом конвейера (records._lock_many), а перенос записей и журнал — пакетными запросами;
4. время — после блокировок и не раньше последнего изменения записи: журнал папки идёт по порядку, даже если
   часы ушли назад.
Соединение — только в режиме autocommit (db.connect). Ответы — словари, совместимые с JSON.
"""
from __future__ import annotations

import unicodedata
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone

import psycopg

from . import records
from .ids import uuid7

MAX_DEPTH = 8
MAX_SEGMENT = 100
NO_FOLDER = "-"                     # в контракте HTTP — «без папки», поэтому имя папки такое быть не может
DEFAULTS = ("Проекты", "Области", "Ресурсы", "Архив")
INIT_AGENT = "model:amemo-init"      # автор папок новой базы: их создаёт программа, а не человек
FOLDERS_LOCK = 0x616D656D00000003   # ключ pg_advisory_xact_lock папок: «amemo» + 3
# управляющие символы, знаки форматирования, суррогаты, разделители строк и абзацев: в имени папки они невидимы,
# меняют направление письма или ломают строку. ZWNJ и ZWJ (U+200C, U+200D) — часть написания слов и эмодзи
_FORBIDDEN = {"Cc", "Cf", "Cs", "Zl", "Zp"}
_ALLOWED = {"\u200c", "\u200d"}


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
        if segment == NO_FOLDER:
            raise FolderError(f"{where}: «-» означает «без папки» и именем папки быть не может", code="invalid")
        bad = next((ch for ch in segment if ch not in _ALLOWED and unicodedata.category(ch) in _FORBIDDEN), None)
        if bad is not None:
            raise FolderError(f"{where}: невидимый или управляющий знак U+{ord(bad):04X}", code="invalid")
        if len(segment) > MAX_SEGMENT:
            raise FolderError(f"{where}: {len(segment)} знаков, можно до {MAX_SEGMENT}", code="invalid")
    return "/".join(segments)


def _ancestors(path: str) -> list[str]:
    """Путь и все его родители, от корня: «a/b/c» → a, a/b, a/b/c."""
    parts = path.split("/")
    return ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]


def _name(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _lock_folders(conn: psycopg.Connection, *, exclusive: bool) -> None:
    sql = "SELECT pg_advisory_xact_lock(%s)" if exclusive else "SELECT pg_advisory_xact_lock_shared(%s)"
    conn.execute(sql, (FOLDERS_LOCK,))


def _register(conn: psycopg.Connection, paths: Iterable[str], agent: str, at: datetime) -> set[str]:
    """Пути и их родители — в реестр одним запросом; уже известные не трогаются. Вернуть пути, которые появились.

    Каждый путь и каждый родитель проходят check: в реестр в обход него не попадёт ни «-», ни невидимый знак."""
    wanted = set()
    for path in paths:
        for p in _ancestors(path):
            if check(p) != p:
                raise FolderError(f"папка {p!r}: путь не нормализован — сначала check", code="invalid")
            wanted.add(p)
    # от корня и в одном порядке для всех: два переноса с общим началом пути не встают в тупик
    ordered = sorted(wanted, key=lambda p: (p.count("/"), p))
    rows = conn.execute(
        "INSERT INTO folder (path, created_at, created_by) SELECT u.path, %s, %s "
        "FROM unnest(%s::text[]) WITH ORDINALITY AS u(path, n) ORDER BY u.n "
        "ON CONFLICT (path) DO NOTHING RETURNING path", (at, agent, ordered)).fetchall()
    return {row[0] for row in rows}


def seed_defaults(conn: psycopg.Connection, at: datetime | None = None) -> None:
    """Четыре папки новой базы — в транзакции вызывающего (db.prepare: там же, где впервые ставится base_id)."""
    records._ensure_agent(conn, INIT_AGENT)
    _register(conn, DEFAULTS, INIT_AGENT, at or _now())


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


def exists(conn: psycopg.Connection, path: str) -> bool:
    """Видна ли папка в дереве (реестр или записи в ней); path — через check (неверный — FolderError invalid)."""
    return _known(conn, check(path))


def _known(conn: psycopg.Connection, path: str) -> bool:
    """Папка видна в дереве: она в реестре, или в ней (во вложенных) лежат записи."""
    return _registered(conn, path) or _has_content(conn, path)


def _log(conn, target: str, record_id: uuid.UUID, before: str | None, after: str | None, agent: str,
         at: datetime) -> None:
    """Перенос одной записи: столбец folder и строка журнала (у переименования — те же два шага пакетно)."""
    conn.execute(f"UPDATE {target} SET folder = %s WHERE id = %s", (after, record_id))
    conn.execute("INSERT INTO folder_log (id, target, record_id, folder_from, folder_to, agent, changed_at) "
                 "VALUES (%s, %s, %s, %s, %s, %s, %s)", (uuid7(), target, record_id, before, after, agent, at))


def move(conn: psycopg.Connection, ref: str, folder: str | None, *, agent: str) -> dict:
    """Переложить запись в папку (None — «без папки») без новой ревизии; та же папка — ничего не меняется."""
    records._require_autocommit(conn)
    path = check(folder) if folder is not None else None
    target, record_id = records.resolve(conn, ref)     # нет записи — RecordNotFound
    with conn.transaction():
        records._ensure_agent(conn, agent)
        _lock_folders(conn, exclusive=False)
        last = records._lock(conn, target, record_id)
        at = max(_now(), last)
        before = conn.execute(f"SELECT folder FROM {target} WHERE id = %s", (record_id,)).fetchone()[0]
        if before != path:
            if path is not None:
                _register(conn, [path], agent, at)
            _log(conn, target, record_id, before, path, agent, at)
    return {"ref": f"{records.PREFIX[target]}:{record_id}", "from": before, "to": path, "moved": before != path}


def move_many(conn: psycopg.Connection, refs: list[str], folder: str | None, *, agent: str) -> list[dict]:
    """Переложить записи в папку одной транзакцией (выбор в списке): как move для каждой, но разом — все или
    ни одной. Повторы ссылок не мешают; ответ — по записи на ссылку, в порядке refs, с прежней папкой (отмена)."""
    records._require_autocommit(conn)
    path = check(folder) if folder is not None else None
    resolved = [records.resolve(conn, ref) for ref in refs]          # нет записи — RecordNotFound
    unique = sorted(set(resolved), key=lambda pair: pair[1])          # по id, как в commit: без тупиков
    with conn.transaction():
        records._ensure_agent(conn, agent)
        _lock_folders(conn, exclusive=False)
        last = records._lock_many(conn, unique)
        at = max(_now(), last) if last else _now()
        if path is not None:
            _register(conn, [path], agent, at)
        before = {}
        for target, record_id in unique:
            before[record_id] = conn.execute(f"SELECT folder FROM {target} WHERE id = %s",
                                             (record_id,)).fetchone()[0]
            if before[record_id] != path:
                _log(conn, target, record_id, before[record_id], path, agent, at)
    return [{"ref": f"{records.PREFIX[target]}:{record_id}", "from": before[record_id], "to": path,
             "moved": before[record_id] != path} for target, record_id in dict.fromkeys(resolved)]


def create(conn: psycopg.Connection, path: str, *, agent: str) -> dict:
    """Папка в реестре (с родителями). Уже есть — FolderError с кодом exists."""
    records._require_autocommit(conn)
    path = check(path)
    with conn.transaction():
        records._ensure_agent(conn, agent)
        _lock_folders(conn, exclusive=False)
        at = _now()
        # RETURNING ловит и папку, которую в этот миг создал соседний create
        if _known(conn, path) or path not in _register(conn, [path], agent, at):
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
        last = records._lock_many(conn, [(target, record_id) for target, record_id, _ in found])
        at = max(_now(), last) if last is not None else _now()
        if listed:
            # новые пути не пересекаются ни с прежними, ни с занятыми (проверено выше): уникальность не мешает
            conn.execute("UPDATE folder AS f SET path = u.new FROM unnest(%s::text[], %s::text[]) AS u(old, new) "
                         "WHERE f.path = u.old", (listed, [renamed[p] for p in listed]))
        _register(conn, [new, *renamed.values()], agent, at)   # родители нового пути; пути записей вне реестра
        for target in records.PREFIX:
            rows = [(record_id, before) for t, record_id, before in found if t == target]
            if rows:
                conn.execute(f"UPDATE {target} AS r SET folder = u.folder "
                             f"FROM unnest(%s::uuid[], %s::text[]) AS u(id, folder) WHERE r.id = u.id",
                             ([record_id for record_id, _ in rows], [renamed[before] for _, before in rows]))
        if found:
            conn.execute(
                "INSERT INTO folder_log (id, target, record_id, folder_from, folder_to, agent, changed_at) "
                "SELECT u.id, u.target, u.record_id, u.f, u.t, %s, %s "
                "FROM unnest(%s::uuid[], %s::text[], %s::uuid[], %s::text[], %s::text[]) "
                "AS u(id, target, record_id, f, t)",
                (agent, at, [uuid7() for _ in found], [target for target, _, _ in found],
                 [record_id for _, record_id, _ in found], [before for _, _, before in found],
                 [renamed[before] for _, _, before in found]))
    return {"from": old, "to": new, "folders": len(listed), "records": len(found)}


def _order(path: str) -> tuple:
    """Порядок по имени: без учёта регистра и ё как е (как в поиске, amemo/sources.py), при равенстве — как есть;
    родитель раньше детей."""
    return tuple((segment.casefold().replace("ё", "е"), segment) for segment in path.split("/"))


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
