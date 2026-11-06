"""Объекты источников в базе: файлы (копии в хранилище OCFL), страницы сайтов, переписка; их текст и статус.

  ingest(conn, store, docs, path, agent=…) — файл из папки документов → объект и версия:
    - такое содержимое (digest) уже есть — та же версия; путь запоминается за её объектом, если он ещё ничей;
    - путь известен, содержимое новое — следующая версия объекта этого пути; ревизии со ссылкой на прежние
      версии получают пункт source_changed (review.on_new_version) в той же транзакции;
    - иначе — новый объект. Файл копируется в хранилище один раз.
  web(conn, url) / message(conn, title) — объект без файла: одна версия без digest.
  adopt(conn, store, record, files=…, agent=…) — объект из подборки с тем же id, его версии и файлы, какие пришли.
  resolve_sources(conn, store, docs, payload, agent=…) — path источников тела → object, object_version, digest.
  text(conn, store, object_id, n) — текст версии по страницам, в NFC; кэш object_text по digest.
  mark(conn, object_id, status, agent=…) — отметка, что из объекта атомизировано (читает lookup.object_status).
id объекта в этих функциях и в lookup — UUID или ссылка obj:<UUID>, как её отдаёт lookup.object_by_path.

Путь в папке документов — от её корня, как его прислали: «\\» читается как «/», имена сравниваются в NFC (имена
файлов из архивов и macOS бывают в NFD); абсолютный путь и «..» — ошибка. Ключ пути — этот путь в NFC, а не путь,
куда ведёт ссылка; имя объекта — имя самого файла. Путь к файлу без расширения,
к папке или в существующую папку — ошибка с подсказкой, а не переписка: иначе источник остался бы без копии
и без сверки цитаты.

Объекты пишутся отдельной транзакцией, до пакета изменений: копия файла — содержимое, а не утверждение, она
остаётся, даже если пакет потом отклонят. Записи объектов идут по очереди под одной рекомендательной блокировкой:
номер версии и копию в хранилище два процесса не делят. Порядок — строки базы, копия, фиксация: сбой копии
откатывает строки; сбой фиксации оставляет в хранилище версию, которую повтор примет или откатит
(amem/ocfl_store.py). Корень хранилища создаётся первой записью файла; если файлы в базе уже есть, а корня
нет, — ошибка: папка данных не подключена.
"""
from __future__ import annotations

import hashlib
import mimetypes
import os
import posixpath
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

import psycopg

from . import extract, model_v1, review, sources
from .ids import uuid7
from .ocfl_store import ObjectStore, StoreError
from .records import as_uuid

OBJECTS_LOCK = 0x616D656D00000002          # ключ pg_advisory_xact_lock записи объектов: «amem» + 2
# адрес сайта: схема, www. или первый сегмент — домен латиницей («example.org/docs/TS.pdf»)
URL = re.compile(r"^(?:[a-z][a-z0-9+.-]*://|www\.)|^[a-z0-9-]+(?:\.[a-z0-9-]+)+/", re.I)
DOMAIN = re.compile(r"[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}", re.I)     # «example.org» без схемы и пути
AGENT = re.compile(r"^(person|model):[a-z0-9_.-]+$")         # как CHECK таблицы agent
GUESS_SUFFIXES = (".pdf", ".md", ".txt")       # расширения, которые проверяются у пути без расширения
STATUSES = {s.value for s in model_v1.ObjectStatus}


class ObjectError(ValueError):
    """Ошибка данных объекта; code (если есть) — машинный признак для службы: not_found, invalid, too_large."""

    def __init__(self, *args, code: str | None = None):
        super().__init__(*args)
        self.code = code


@dataclass
class Version:
    object_id: uuid.UUID
    n: int
    digest: str | None
    kind: str
    created: bool          # False — такая версия уже была

    @property
    def ref(self) -> str:
        return f"obj:{self.object_id}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def object_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """id объекта из вызова: UUID или ссылка obj:<UUID>; иначе RecordError."""
    if isinstance(value, str) and value.startswith("obj:"):
        value = value[4:]
    return as_uuid(value, "object_id")


def _clean(path: str) -> str:
    return path.strip().replace("\\", "/")


def _is(check, path: Path | None) -> bool:
    """is_file / is_dir без исключения: слишком длинное имя или нет прав — «нет такого»."""
    try:
        return path is not None and check(path)
    except OSError:
        return False


def _locate(docs: Path, path: str, check=Path.is_file) -> Path | None:
    """Файл (или папка, check=Path.is_dir) по пути внутри папки документов или None. Не нашёлся как есть — ищется
    по частям пути с именами в NFC."""
    file = sources.safe_join(docs, path)
    if _is(check, file):
        return file
    current = docs
    for part in PurePosixPath(path).parts:
        if part == "..":
            return None
        try:
            current = next((c for c in current.iterdir() if _nfc(c.name) == _nfc(part)), None)
        except OSError:
            return None
        if current is None:
            return None
    file = sources.safe_join(docs, current.relative_to(docs).as_posix())
    return file if _is(check, file) else None


def _check_relative(path: str) -> None:
    """Путь — от корня папки документов и вниз: ключ пути неизменен, выход выше корня дал бы чужой ключ."""
    if PurePosixPath(path).is_absolute():
        raise ObjectError(f"{path}: нужен путь от корня папки документов, а не абсолютный")
    if ".." in PurePosixPath(path).parts:
        raise ObjectError(f"{path}: «..» в пути не допускается — нужен путь от корня папки документов вниз")


def _check_agent(agent: str) -> None:
    """Агент пишется в базу (ingest записывает его до блокировки объектов): неверный — ObjectError, а не сбой
    ограничения таблицы agent."""
    if not isinstance(agent, str) or not AGENT.fullmatch(agent):
        raise ObjectError(f"агент {agent!r}: нужен person:<имя> или model:<имя> (строчные латинские буквы, цифры, "
                          "«_», «.», «-»)")


def _require_autocommit(conn: psycopg.Connection) -> None:
    if not conn.autocommit:
        raise ObjectError("нужно соединение с autocommit=True (db.connect): иначе запись не фиксируется")


def _lock(conn: psycopg.Connection) -> datetime:
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (OBJECTS_LOCK,))
    return _now()


def _add_path(conn, path: str, object_id: uuid.UUID, at: datetime) -> None:
    conn.execute("INSERT INTO object_path (path, object_id, added_at) VALUES (%s, %s, %s) "
                 "ON CONFLICT (path) DO NOTHING", (path, object_id, at))


def ingest(conn: psycopg.Connection, store: ObjectStore, docs: Path, path: str, *, agent: str) -> Version:
    """Файл из папки документов → объект и версия (правила — в описании модуля)."""
    _require_autocommit(conn)
    _check_agent(agent)
    docs = Path(docs).resolve()
    path = _clean(path)
    _check_relative(path)
    file = _locate(docs, path)
    if file is None:
        raise ObjectError(f"{path}: файла нет в папке документов")
    key = _nfc(posixpath.normpath(path))
    name = _nfc(file.name)          # имя самого файла: у ссылки без расширения текст извлекался бы как у «без текста»
    try:
        with open(file, "rb") as f:
            digest = "sha256:" + hashlib.file_digest(f, "sha256").hexdigest()
            size = os.fstat(f.fileno()).st_size
    except OSError as e:
        raise ObjectError(f"{path}: файл не читается ({e.strerror or e})") from e
    with conn.transaction():
        # агент — до блокировки объектов, как в submit (разд. 7.5, шаг 1): пункты новой версии пишутся от его имени
        conn.execute("INSERT INTO agent (id) VALUES (%s) ON CONFLICT (id) DO NOTHING", (agent,))
        at = _lock(conn)
        # под блокировкой: корень создаёт и чинит после сбоя один процесс. Создаётся он, только пока в базе нет
        # файлов: пустая папка при файлах в базе — неподключённый том, а не новое хранилище
        has_files = conn.execute("SELECT EXISTS (SELECT 1 FROM object_version WHERE digest IS NOT NULL)").fetchone()[0]
        store.init(create=not has_files)
        row = conn.execute("SELECT object_id, n FROM object_version WHERE digest = %s", (digest,)).fetchone()
        if row is not None:
            _add_path(conn, key, row[0], at)
            return Version(row[0], row[1], digest, "file", created=False)
        row = conn.execute("SELECT object_id FROM object_path WHERE path = %s", (key,)).fetchone()
        if row is not None:
            object_id = row[0]
            n = conn.execute("SELECT max(n) + 1 FROM object_version WHERE object_id = %s", (object_id,)).fetchone()[0]
        else:
            object_id, n = uuid7(), 1
            conn.execute("INSERT INTO object (id, kind, original_name, media_type, created_at) "
                         "VALUES (%s, 'file', %s, %s, %s)", (object_id, name, mimetypes.guess_type(name)[0], at))
            _add_path(conn, key, object_id, at)
        conn.execute("INSERT INTO object_version (object_id, kind, n, digest, size, recorded_at) "
                     "VALUES (%s, 'file', %s, %s, %s, %s)", (object_id, n, digest, size, at))
        if n > 1:
            # в той же транзакции: версия и пункты пересмотра фиксируются вместе (разд. 8.8)
            review.on_new_version(conn, object_id, n, agent=agent, at=at)
        store.add_version(object_id, n, file, name, digest, user=agent, message=f"amem: {key}")
    return Version(object_id, n, digest, "file", created=True)


def adopt(conn: psycopg.Connection, store: ObjectStore, record: dict, *, files: dict[str, Path],
          agent: str) -> list[str]:
    """Принять объект из подборки (запись objects.jsonl, как её отдаёт lookup.get_object): строка object с тем же id,
    пути, версии по номеру; файлы версий (files: digest → путь к файлу) — в хранилище. Вернуть предупреждения.

    Существующие версии сверяются по digest: расхождение, другой вид объекта или digest у другого объекта —
    ObjectError, и ничего не записано. Версия без файла остаётся без копии: её источники получат вердикт no_file,
    пока файл не придёт (повторный adopt с файлом). Копии в хранилище идут подряд: файл версии, перед которой
    копии нет, не копируется — предупреждение; копия версии, которой база до вызова не знала (сбой прошлой
    попытки), сверяется заново. Путь — от корня папки документов вниз, как у ingest; занятый другим объектом
    остаётся за ним, а original_name, media_type, url существующего объекта — локальные (оба — предупреждение).
    Неверный id объекта или номер версии — ObjectError.
    Новая версия известного объекта ставит пункты source_changed, как у ingest. Блокировка и порядок — как у
    ingest: строки, копия, фиксация."""
    _require_autocommit(conn)
    _check_agent(agent)
    try:
        object_id = object_uuid(record.get("id", ""))
    except ValueError as e:                      # RecordError — для записей; здесь ошибка объекта
        raise ObjectError(f"объект подборки: {e}") from e
    kind = record.get("kind")
    label = f"obj:{object_id}"
    for v in record.get("versions") or []:
        n = v.get("n") if isinstance(v, dict) else None
        if not isinstance(n, int) or isinstance(n, bool) or n < 1:
            raise ObjectError(f"{label}: номер версии {n!r} — нужно целое от 1")
    versions = sorted(record.get("versions") or [], key=lambda v: v["n"])
    paths = [_nfc(path) for path in record.get("logical_paths") or []]
    for path in paths:
        _check_relative(path)                    # путь из чужой базы — тоже от корня папки документов вниз
    warnings: list[str] = []
    try:
        with conn.transaction():
            conn.execute("INSERT INTO agent (id) VALUES (%s) ON CONFLICT (id) DO NOTHING", (agent,))
            at = _lock(conn)
            if kind == "file":
                # под блокировкой, как у ingest, и даже без файлов в подборке: версии с digest в базе означают
                # корень хранилища — иначе следующая копия (ingest, adopt с файлом) сочла бы его неподключённым
                has_files = conn.execute(
                    "SELECT EXISTS (SELECT 1 FROM object_version WHERE digest IS NOT NULL)").fetchone()[0]
                store.init(create=not has_files)
            row = conn.execute("SELECT kind, original_name, media_type, url FROM object WHERE id = %s",
                               (object_id,)).fetchone()
            if row is None:
                name = record.get("original_name")
                conn.execute("INSERT INTO object (id, kind, original_name, media_type, format_puid, url, "
                             "retrieved_at, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                             (object_id, kind, _nfc(name) if name else None, record.get("media_type"),
                              record.get("format_puid"), record.get("url"), record.get("retrieved_at"), at))
            elif row[0] != kind:
                raise ObjectError(f"{label}: вид {row[0]}, в подборке {kind}")
            else:
                for column, local in zip(("original_name", "media_type", "url"), row[1:]):
                    theirs = record.get(column)
                    if column == "original_name" and theirs:
                        theirs = _nfc(theirs)
                    if theirs is not None and theirs != local:
                        warnings.append(f"{label}: {column} {local!r}, в подборке {theirs!r} — остаётся локальное")
            for key in paths:
                owner = conn.execute("SELECT object_id FROM object_path WHERE path = %s", (key,)).fetchone()
                if owner is None:
                    _add_path(conn, key, object_id, at)
                elif owner[0] != object_id:
                    warnings.append(f"{label}: путь {key} уже у объекта obj:{owner[0]} — остаётся за ним")
            have = dict(conn.execute("SELECT n, digest FROM object_version WHERE object_id = %s", (object_id,)))
            copies: list[tuple[int, Path, str]] = []
            for v in versions:
                n, digest = v.get("n"), v.get("digest")
                if n in have:
                    if have[n] != digest:
                        raise ObjectError(f"{label}: digest версии {n} не совпадает с локальным")
                else:
                    if digest is not None:
                        owner = conn.execute("SELECT object_id, n FROM object_version WHERE digest = %s",
                                             (digest,)).fetchone()
                        if owner is not None:
                            raise ObjectError(f"{label}: digest версии {n} уже у объекта obj:{owner[0]} "
                                              f"(версия {owner[1]})")
                    conn.execute("INSERT INTO object_version (object_id, kind, n, digest, size, recorded_at) "
                                 "VALUES (%s, %s, %s, %s, %s, %s)",
                                 (object_id, kind, n, digest, v.get("size"), v.get("recorded_at") or at))
                    if isinstance(n, int) and n > 1:
                        review.on_new_version(conn, object_id, n, agent=agent, at=at)
                file = files.get(digest) if digest is not None else None
                if file is not None and kind == "file":
                    copies.append((n, Path(file), digest))
            for n, file, digest in copies:
                head = store.head(object_id)
                if n in have and head >= n:
                    continue                             # версию и её копию база знала до вызова
                # версия новая для базы, а копия уже есть (сбой прошлой попытки после копии): add_version сам
                # примет то же содержимое или откатит иное — как у ingest
                if head < n - 1:
                    warnings.append(f"{label}: файл версии {n} не скопирован — в хранилище нет копии версии "
                                    f"{head + 1}; источники этой версии останутся без файла")
                    continue
                store.add_version(object_id, n, file, record.get("original_name") or file.name, digest,
                                  user=agent, message=f"amem: adopt {label}")
    except (psycopg.errors.IntegrityError, psycopg.errors.DataError) as e:      # ограничения таблиц, неверные даты
        raise ObjectError(f"{label}: запись объекта не принята: {e.diag.message_primary}") from e
    return warnings


def _without_file(conn, kind: str, value: str, retrieved_at: date | None) -> Version:
    _require_autocommit(conn)
    column = "url" if kind == "web" else "original_name"
    value = _nfc(value.strip())
    if not value:
        raise ObjectError("пустой адрес или название источника")
    if "\x00" in value:
        raise ObjectError(f"{value!r}: в адресе или названии источника — символ NUL")
    with conn.transaction():
        at = _lock(conn)
        row = conn.execute(f"SELECT id FROM object WHERE kind = %s AND {column} = %s", (kind, value)).fetchone()
        if row is not None:
            return Version(row[0], 1, None, kind, created=False)
        object_id = uuid7()
        conn.execute(f"INSERT INTO object (id, kind, {column}, retrieved_at, created_at) VALUES (%s, %s, %s, %s, %s)",
                     (object_id, kind, value, (retrieved_at or date.today()) if kind == "web" else None, at))
        conn.execute("INSERT INTO object_version (object_id, kind, n, recorded_at) VALUES (%s, %s, 1, %s)",
                     (object_id, kind, at))
    return Version(object_id, 1, None, kind, created=True)


def web(conn: psycopg.Connection, url: str, *, retrieved_at: date | None = None) -> Version:
    """Страница сайта: одна на адрес; дата обращения — первая (по умолчанию сегодня по часам сервера)."""
    return _without_file(conn, "web", url, retrieved_at)


def message(conn: psycopg.Connection, title: str) -> Version:
    """Письмо или переписка: одна на название («Письмо ООО «Ромашка» от 12.03.2024»)."""
    return _without_file(conn, "message", title, None)


def _resolve_path(conn, store, docs, path: str, agent: str) -> Version:
    """Существующий файл или путь, похожий на файл, — файл (нет файла — ошибка); адрес — сайт; иначе — переписка.

    Не переписка, а ошибка с подсказкой: путь к файлу без расширения, папка, путь в существующую папку (по первой
    части пути, имена в NFC), домен без схемы. Проверки папок — раньше адреса: папка «example.org» — это папка."""
    docs, raw, path = Path(docs).resolve(), path.strip(), _clean(path)
    _check_relative(path)
    if _locate(docs, path) is not None or sources.looks_like_file(path):
        return ingest(conn, store, docs, path, agent=agent)
    for suffix in GUESS_SUFFIXES:
        if _locate(docs, path + suffix) is not None:
            raise ObjectError(f"{path}: файла нет в папке документов — возможно, «{path}{suffix}»?")
    if _locate(docs, path, Path.is_dir) is not None:
        raise ObjectError(f"{path}: это папка, а не файл")
    if "/" in path and _locate(docs, PurePosixPath(path).parts[0], Path.is_dir) is not None:
        raise ObjectError(f"{path}: файла нет в папке документов")
    if URL.search(raw):
        return web(conn, raw)
    if DOMAIN.fullmatch(raw):
        raise ObjectError(f"{raw}: похоже на адрес сайта — укажите его со схемой: https://{raw}")
    return message(conn, raw)


def resolve_sources(conn: psycopg.Connection, store: ObjectStore, docs: Path, payload: dict, *, agent: str) -> dict:
    """Тело атома или сущности, где у источников с path появились object, object_version и digest.

    Источник, у которого уже есть object, не трогается — его версию и digest проверяет запись (records.commit).
    Входное тело не меняется; ошибка — ObjectError с местом (sources[i])."""
    _check_agent(agent)
    if not payload.get("sources"):
        return payload
    out = []
    for i, source in enumerate(payload["sources"]):
        if source.get("object") or not source.get("path"):
            out.append(source)
            continue
        try:
            version = _resolve_path(conn, store, docs, source["path"], agent)
        except ObjectError as e:
            raise ObjectError(f"sources[{i}]: {e}") from e
        except StoreError as e:                  # сбой хранилища на сервере, а не ошибка в данных агента
            raise StoreError(f"sources[{i}]: {e}") from e
        resolved = {k: v for k, v in source.items() if k != "digest"}
        resolved |= {"object": version.ref, "object_version": version.n}
        if version.digest:
            resolved["digest"] = version.digest
        out.append(resolved)
    return {**payload, "sources": out}


def text(conn: psycopg.Connection, store: ObjectStore, object_id: uuid.UUID | str, n: int) -> list[str] | None:
    """Текст версии по страницам (у .md и .txt — одна страница), в NFC; None — у файла нет текста или объект
    без файла. Извлекается один раз на содержимое: кэш object_text по digest."""
    _require_autocommit(conn)
    object_id = object_uuid(object_id)
    row = conn.execute("SELECT digest FROM object_version WHERE object_id = %s AND n = %s", (object_id, n)).fetchone()
    if row is None:
        raise ObjectError(f"obj:{object_id}: нет версии {n}")
    digest = row[0]
    if digest is None:
        return None
    cached = conn.execute("SELECT page, text FROM object_text WHERE digest = %s ORDER BY page", (digest,)).fetchall()
    if cached:
        return None if cached[0][0] == 0 else [t for _, t in cached]
    pages = sources.extract_pages(store.content(object_id, n))
    if pages is not None:
        pages = [_nfc(p.replace("\x00", "")) for p in pages]      # NUL в тексте PostgreSQL не хранит; NFC — после
    rows = [(digest, i + 1, t) for i, t in enumerate(pages)] if pages else [(digest, 0, "")]
    with conn.transaction(), conn.cursor() as cur:
        cur.executemany("INSERT INTO object_text (digest, page, text) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", rows)
    return pages


def mark(conn: psycopg.Connection, object_id: uuid.UUID | str, status: str, *, agent: str,
         note: str | None = None) -> None:
    """Отметить, что из объекта атомизировано: parsed / partial / skipped и заметка. Прежние отметки остаются.

    Отметки одного объекта идут по очереди (блокировка строки объекта), и новая позже прежних, даже если часы ушли
    назад: последняя по времени — последняя записанная."""
    _require_autocommit(conn)
    object_id = object_uuid(object_id)
    if status not in STATUSES:
        raise ObjectError(f"статус {status!r}: нужен один из {', '.join(sorted(STATUSES))}")
    with conn.transaction():
        conn.execute("INSERT INTO agent (id) VALUES (%s) ON CONFLICT (id) DO NOTHING", (agent,))
        if conn.execute("SELECT 1 FROM object WHERE id = %s FOR NO KEY UPDATE", (object_id,)).fetchone() is None:
            raise ObjectError(f"obj:{object_id}: такого объекта нет")
        last = conn.execute("SELECT max(changed_at) FROM object_status WHERE object_id = %s", (object_id,)).fetchone()[0]
        conn.execute("INSERT INTO object_status (id, object_id, status, note, agent, changed_at) "
                     "VALUES (%s, %s, %s, %s, %s, %s)",
                     (uuid7(), object_id, status, note, agent,
                      max(_now(), last + timedelta(microseconds=1)) if last else _now()))


SHEET_MAX_CELLS = 10_000                  # лист отдаётся окном: больше ячеек за раз не читаем
_RANGE = re.compile(r"^([A-Z]{1,3})([0-9]{1,7})(?::([A-Z]{1,3})([0-9]{1,7}))?$")


def _a1(cell_range: str) -> tuple[int, int, int, int]:
    """Диапазон A1 («B2:D10», «C3») → (первая строка, первый столбец, последняя строка, последний столбец)."""
    from openpyxl.utils import column_index_from_string

    m = _RANGE.match(cell_range.strip().replace("$", "").upper())
    if m is None:
        raise ObjectError(f"диапазон {cell_range!r}: нужна запись A1, например B2:D10", code="invalid")
    c1, r1, c2, r2 = m.group(1), int(m.group(2)), m.group(3) or m.group(1), int(m.group(4) or m.group(2))
    c1, c2 = column_index_from_string(c1), column_index_from_string(c2)
    if min(r1, r2) < 1 or max(r1, r2) > 1_048_576 or max(c1, c2) > 16_384 or r1 > r2 or c1 > c2:
        raise ObjectError(f"диапазон {cell_range!r}: ячейки вне листа или начало правее и ниже конца", code="invalid")
    return r1, c1, r2, c2


def sheet(conn: psycopg.Connection, store: ObjectStore, object_id: uuid.UUID | str, n: int, name: str,
          cell_range: str | None = None) -> dict:
    """Ячейки листа xlsx версии n: {name, range, rows}; значения — как в тексте для сверки (extract._cell_text).

    cell_range в нотации A1; без него — весь лист. Больше SHEET_MAX_CELLS ячеек — ObjectError(code="too_large");
    нет версии или листа — "not_found"; не книга xlsx или неверный диапазон — "invalid"."""
    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter
    from openpyxl.utils.exceptions import InvalidFileException

    object_id = object_uuid(object_id)
    box = _a1(cell_range) if cell_range else None
    if box and (box[2] - box[0] + 1) * (box[3] - box[1] + 1) > SHEET_MAX_CELLS:
        raise ObjectError(f"диапазон {cell_range!r}: больше {SHEET_MAX_CELLS} ячеек", code="too_large")
    row = conn.execute("SELECT digest FROM object_version WHERE object_id = %s AND n = %s", (object_id, n)).fetchone()
    if row is None:
        raise ObjectError(f"obj:{object_id}: нет версии {n}", code="not_found")
    if row[0] is None:
        raise ObjectError(f"obj:{object_id}: у версии {n} нет файла", code="invalid")
    try:
        wb = load_workbook(store.content(object_id, n), read_only=True, data_only=True)
    except (InvalidFileException, *extract._BAD_FILE) as e:
        raise ObjectError(f"obj:{object_id}: версия {n} не книга xlsx", code="invalid") from e
    try:
        wanted = _nfc(name).casefold()
        found = [ws for ws in wb.worksheets if ws.title == name] or \
                [ws for ws in wb.worksheets if _nfc(ws.title).casefold() == wanted]
        if not found:
            raise ObjectError(f"obj:{object_id}: в версии {n} нет листа {name!r}", code="not_found")
        ws = found[0]
        ws.reset_dimensions()                       # заявленный размер листа в файле бывает неверным
        rows: list[list[str]] = []
        cells = 0
        try:
            if box:
                r1, c1, r2, c2 = box
                grid = ws.iter_rows(min_row=r1, max_row=r2, min_col=c1, max_col=c2)
            else:
                r1, c1, r2, c2 = 1, 1, 0, 0
                grid = ws.iter_rows()
            for line in grid:
                cells += len(line)
                if cells > SHEET_MAX_CELLS:
                    raise ObjectError(f"лист {name!r}: больше {SHEET_MAX_CELLS} ячеек, нужен диапазон", code="too_large")
                rows.append([extract._cell_text(c.value, getattr(c, "number_format", "")) for c in line])
        except (InvalidFileException, *extract._BAD_FILE) as e:
            raise ObjectError(f"obj:{object_id}: версия {n} не читается как xlsx", code="invalid") from e
    finally:
        wb.close()
    if box:                                         # окно целиком, даже за краем данных: пустые ячейки — ""
        width, height = c2 - c1 + 1, r2 - r1 + 1
        rows = [(r + [""] * width)[:width] for r in rows[:height]] + [[""] * width] * max(0, height - len(rows))
        shown = f"{get_column_letter(c1)}{r1}:{get_column_letter(c2)}{r2}"
    else:
        width = max((len(r) for r in rows), default=1)
        rows = [r + [""] * (width - len(r)) for r in rows]
        shown = f"A1:{get_column_letter(width)}{max(len(rows), 1)}"
    return {"name": ws.title, "range": shown, "rows": rows}
