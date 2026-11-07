"""Подключение к PostgreSQL схемы v1, миграции SQL, загрузка словарей и шаблонов.

  prepare(conn) — то, что делает сервер при старте: миграции → словари и шаблоны → base_id и четыре папки новой
  базы → счётчик id.
  set_base_name(conn, name), base_name(conn) — имя базы для людей (ключ base_name в meta); base_id от него
  не зависит.

Соединение — в режиме autocommit: тогда каждый `with conn.transaction()` — настоящая транзакция и фиксируется
при выходе из блока. Без autocommit первое же чтение открывает неявную транзакцию, все дальнейшие блоки становятся
точками сохранения внутри неё, и ничего не фиксируется до conn.commit() — поэтому функции записи такое
соединение не принимают.

Миграции — amem/sql/NNNN_*.sql, применяются по порядку, каждая в своей транзакции; учёт — schema_migrations
(имя и sha256 файла). Применённый файл менять нельзя: изменения пишутся новой миграцией. Несколько процессов,
стартующих разом, применяют миграции по очереди — под общей рекомендательной блокировкой. База — только в кодировке
UTF8: миграции и данные в UTF-8, имена и пути объектов сравниваются в NFC.
"""
from __future__ import annotations

import hashlib
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from . import canon, folders, ids, packs

SQL_DIR = Path(__file__).with_name("sql")
MIGRATION_LOCK = 0x616D656D00000001          # ключ pg_advisory_lock для миграций: «amem» + 1


BASE_NAME_MAX = 200


class MigrationError(RuntimeError):
    pass


class BaseNameError(ValueError):
    """Неверное имя базы: не строка, пустое, длиннее BASE_NAME_MAX или с невидимыми и управляющими знаками."""


def connect(dsn: str, **kwargs) -> psycopg.Connection:
    kwargs.setdefault("autocommit", True)
    return psycopg.connect(dsn, **kwargs)


def require_autocommit(conn: psycopg.Connection) -> None:
    if not conn.autocommit:
        raise MigrationError("нужно соединение с autocommit=True (db.connect): иначе записи не фиксируются")


def migrate(conn: psycopg.Connection) -> list[str]:
    """Применить новые миграции; вернуть их имена."""
    require_autocommit(conn)
    encoding = conn.info.parameter_status("server_encoding")       # без запроса: сервер сообщает её при входе
    if encoding != "UTF8":
        raise MigrationError(f"нужна база в кодировке UTF8, а не {encoding}: имена и пути объектов хранятся в NFC")
    conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK,))
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations ("
                     "name text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())")
        applied = dict(conn.execute("SELECT name, sha256 FROM schema_migrations").fetchall())
        files = sorted(SQL_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))
        missing = sorted(set(applied) - {p.name for p in files})
        if missing:
            raise MigrationError(f"в базе применены миграции, которых нет в коде: {', '.join(missing)} — код старее базы")
        done = []
        for path in files:
            sql = path.read_text(encoding="utf-8")
            digest = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            if path.name in applied:
                if applied[path.name] != digest:
                    raise MigrationError(f"{path.name}: файл изменён после применения — изменения пишутся новой миграцией")
                continue
            with conn.transaction():
                conn.execute(sql)
                conn.execute("INSERT INTO schema_migrations (name, sha256) VALUES (%s, %s)", (path.name, digest))
            done.append(path.name)
        return done
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK,))


def _upsert_concept(conn, c, origin: str, now: datetime) -> None:
    data = c.model_dump(mode="json", exclude_none=True)
    conn.execute(
        "INSERT INTO concept (scheme, code, data, origin, updated_at) VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (scheme, code) DO UPDATE SET data = EXCLUDED.data, origin = EXCLUDED.origin, "
        "updated_at = EXCLUDED.updated_at "
        "WHERE concept.data IS DISTINCT FROM EXCLUDED.data OR concept.origin IS DISTINCT FROM EXCLUDED.origin",
        (c.scheme, c.code, Jsonb(data), origin, now))


def load_vocab(conn: psycopg.Connection) -> None:
    """Пакеты домена — в таблицы pack, concept и template; служебные перечни схемы — в concept.

    Понятия из пакетов главнее: обновляют запись, даже если её добавил агент (так величина из словаря
    становится постоянной). Ошибки загрузки (всё откатывается):
    - пакет с тем же именем и версией уже загружен с другим содержимым — поднимите версию;
    - шаблон с той же code и version, но другим содержимым — поднимите version;
    - из пакета исчез код, которым пользуются записи, — внешний ключ не даёт удалить понятие.
    """
    require_autocommit(conn)
    now = datetime.now(timezone.utc)
    with conn.transaction():
        for c in packs.service_concepts():
            _upsert_concept(conn, c, "schema", now)
        loaded = packs.load_packs()
        for p in loaded:
            row = conn.execute("SELECT digest FROM pack WHERE name = %s AND version = %s",
                               (p.name, p.version)).fetchone()
            if row is not None and row[0] != p.digest:
                raise MigrationError(f"пакет {p.name} {p.version}: уже загружен с другим содержимым — поднимите версию")
            # requires обновляется и у уже загруженного пакета: базы до 0007 получили столбец пустым
            conn.execute("INSERT INTO pack (name, version, digest, requires, loaded_at) VALUES (%s, %s, %s, %s, %s) "
                         "ON CONFLICT (name, version) DO UPDATE SET requires = EXCLUDED.requires",
                         (p.name, p.version, p.digest, Jsonb(p.requires), now))
            for c in p.concepts:
                _upsert_concept(conn, c, p.name, now)
            for t in p.templates:
                body = t.model_dump(mode="json", exclude_none=True)
                body_hash = canon.content_hash(body)      # хэш JSON по RFC 8785, как у тела ревизии
                row = conn.execute("SELECT body_hash FROM template WHERE code = %s AND version = %s",
                                   (t.code, t.version)).fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO template (code, version, target, applies_to, body, body_hash, loaded_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (t.code, t.version, t.target, t.applies_to, Jsonb(body), body_hash, now))
                elif row[0] != body_hash:
                    raise MigrationError(f"шаблон {t.code} {t.version}: уже загружен с другим содержимым — поднимите version")
        # действующие версии шаблонов — те, что принесли загруженные сейчас пакеты; старые версии остаются в template
        conn.execute("DELETE FROM template_active")
        for p in loaded:
            for t in p.templates:
                conn.execute("INSERT INTO template_active (code, version) VALUES (%s, %s)", (t.code, t.version))
        # осиротевшие понятия: код исчез из пакета или пакет больше не загружается;
        # используемые записями удалить нельзя — внешний ключ, ошибка называет пакет и код
        keep = {(c.scheme, c.code) for p in loaded for c in p.concepts}
        names = {p.name for p in loaded}
        gone = conn.execute("SELECT scheme, code, origin FROM concept WHERE origin NOT IN ('schema', 'agent') "
                            "ORDER BY scheme, code").fetchall()
        for scheme, code, origin in gone:
            if origin in names and (scheme, code) in keep:
                continue
            try:
                conn.execute("DELETE FROM concept WHERE scheme = %s AND code = %s", (scheme, code))
            except psycopg.errors.ForeignKeyViolation as e:
                raise MigrationError(f"пакет {origin}: {scheme}.{code} — исчез код, которым пользуются записи; "
                                     f"верните его в словарь ({e.diag.constraint_name})") from e


def seed_ids(conn: psycopg.Connection) -> None:
    """Продолжить счётчик UUIDv7 после самого позднего id в базе: новые id будут больше уже выданных.

    Таблицы с id берутся из схемы базы (столбец id типа uuid), чтобы новые таблицы не выпали из списка."""
    tables = [r[0] for r in conn.execute(
        "SELECT c.table_name FROM information_schema.columns c JOIN information_schema.tables t "
        "ON t.table_schema = c.table_schema AND t.table_name = c.table_name "
        "WHERE c.table_schema = current_schema() AND c.column_name = 'id' AND c.data_type = 'uuid' "
        "AND t.table_type = 'BASE TABLE' ORDER BY c.table_name")]
    if not tables:
        return
    # у uuid нет агрегата max в PostgreSQL 16 — берём первый id по убыванию
    union = " UNION ALL ".join(f"(SELECT id FROM {t} ORDER BY id DESC LIMIT 1)" for t in tables)
    row = conn.execute(f"SELECT id FROM ({union}) AS ids ORDER BY id DESC LIMIT 1").fetchone()
    if row is not None:
        ids.seed(row[0])


def prepare(conn: psycopg.Connection) -> list[str]:
    applied = migrate(conn)
    load_vocab(conn)
    # идентичность базы — один раз и навсегда: дамп и экспорт несут её с собой (задел под хаб).
    # Четыре папки новой базы — в той же транзакции: база с base_id их больше не получает — ни после миграции 0008,
    # ни после того, как пользователь удалил папку
    with conn.transaction():
        born = conn.execute("INSERT INTO meta (key, value) VALUES ('base_id', %s) ON CONFLICT (key) DO NOTHING "
                            "RETURNING key", (Jsonb(str(ids.uuid7())),)).fetchone()
        if born is not None:
            folders.seed_defaults(conn)
    seed_ids(conn)
    return applied


def set_base_name(conn: psycopg.Connection, name: str) -> str:
    """Задать имя базы — ключ base_name в meta; вернуть сохранённое имя. Имя — в NFC, без пробелов по краям,
    1–BASE_NAME_MAX знаков, без управляющих и невидимых знаков (правило то же, что у сегмента папки)."""
    require_autocommit(conn)
    if not isinstance(name, str):
        raise BaseNameError(f"имя базы {name!r}: нужна строка")
    value = unicodedata.normalize("NFC", name).strip()
    if not value:
        raise BaseNameError("имя базы: пустое")
    if len(value) > BASE_NAME_MAX:
        raise BaseNameError(f"имя базы: {len(value)} знаков, можно до {BASE_NAME_MAX}")
    bad = next((ch for ch in value if ch not in folders._ALLOWED and unicodedata.category(ch) in folders._FORBIDDEN),
               None)
    if bad is not None:
        raise BaseNameError(f"имя базы: невидимый или управляющий знак U+{ord(bad):04X}")
    with conn.transaction():
        conn.execute("INSERT INTO meta (key, value) VALUES ('base_name', %s) "
                     "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (Jsonb(value),))
    return value


def base_name(conn: psycopg.Connection) -> str | None:
    """Имя базы или None, если его не задавали."""
    row = conn.execute("SELECT value FROM meta WHERE key = 'base_name'").fetchone()
    return row[0] if row is not None else None
