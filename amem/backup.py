"""Бэкап и восстановление: дамп PostgreSQL с манифестом, полный снимок с копией OCFL, проверенное восстановление.

  create(dsn, backup_dir) — pg_dump -Fc в backup_dir/ГГГГ-ММ-ДДTЧЧ-ММ-ССZ.dump и манифест .json рядом;
    после проверки новой пары — ротация: остаются последние keep (14) полных пар.
  snapshot(dsn, objects_root, snapshot_dir) — полный снимок: дамп с манифестом, копия хранилища объектов
    и корневой манифест, связывающий их по base_id и SHA-256; каталог появляется одним переименованием.
  restore(source, dsn, objects_root=None) — восстановление дампа или снимка в пустую базу (и пустую папку объектов);
    всё проверяется до записи, после — base_id, миграции, числа записей и версии файлов.
  verify(source, dsn) — настоящее пробное восстановление во временную базу того же сервера и поиск; база удаляется.

Дамп и числа записей в манифесте берутся из одного снимка транзакции (pg_export_snapshot → pg_dump --snapshot):
манифест описывает ровно то, что лежит в дампе; таймауты простоя в этой транзакции отключены — долгий pg_dump её
не обрывает. pg_dump и pg_restore запускаются без shell, параметры — списком;
пароль из DSN передаётся через окружение процесса (PGPASSWORD) и не попадает ни в argv, ни в манифест, ни в ошибку.
Нужен клиент PostgreSQL 18: каталог с pg_dump и pg_restore — в AMEM_PG_BIN или в PATH.

Готовая копия — это пара «дамп + манифест», у которой манифест читается и размер дампа сходится. Пишется она так:
временный файл занимается атомарно (O_EXCL — два процесса в одну секунду его не делят), pg_dump пишет в него →
fsync → переименование; затем манифест так же; новая пара проверяется по SHA-256, не прошла — удаляется. Сбой
по дороге оставляет .tmp или дамп без манифеста — ни то, ни другое копией не считается и последнюю хорошую копию
не вытесняет; такие остатки сами не удаляются. Существующая копия не перезаписывается, ротация не трогает новую.

Снимок берёт блокировку записи объектов, затем снимок транзакции; в нём читает список версий файлов и копирует
хранилище, отпускает блокировку и только потом запускает pg_dump с тем же снимком: в копии ровно версии, известные
дампу, — это проверяется по digest. В снимок входят только дамп, его манифест и корень OCFL: настройки, .env, кэш
моделей и журналы — нет.

Восстановление снимка сверяет копию хранилища и список версий файлов из манифеста до записи в базу. Если сверка
после pg_restore (base_id, миграции, числа записей, версии) не сошлась, восстановление останавливается, но
восстановленная база остаётся: её нужно пересоздать вручную.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from .objects import OBJECTS_LOCK
from .ocfl_store import ObjectStore, StoreError
from .search import SEARCH_TEXT_VERSION

FORMAT = 1
KEEP = 14
PG_MAJOR = 18                    # клиент не старше сервера: 18 читает и пишет и 16, и 18
NAME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z$")
COUNTED = ("atom", "atom_revision", "entity", "entity_revision", "link", "source", "object", "object_version",
           "atom_use", "changeset", "review_item", "verification", "atom_property", "import_history", "folder",
           "folder_log")
VERIFY_AGENT = "model:amem-backup-verify"
CHUNK = 1 << 20
HEADER_LINES = 50               # SET в заголовке SQL от pg_restore — в первых строках, до данных


class BackupError(RuntimeError):
    pass


# Клиент PostgreSQL


def _tool(name: str) -> str:
    """pg_dump / pg_restore версии не ниже 18: из AMEM_PG_BIN или PATH; иначе — понятная ошибка, а не пропуск."""
    folder = os.environ.get("AMEM_PG_BIN")
    path = str(Path(folder) / name) if folder else shutil.which(name)
    if not path or not os.access(path, os.X_OK):
        raise BackupError(f"нет {name}: нужен клиент PostgreSQL {PG_MAJOR} — каталог с ним в AMEM_PG_BIN или в PATH")
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True, check=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError) as e:
        raise BackupError(f"{name} не запускается: {e}") from e
    match = re.search(r"\(PostgreSQL\) (\d+)", out)
    if not match or int(match.group(1)) < PG_MAJOR:
        raise BackupError(f"{name}: нужна версия {PG_MAJOR} и новее, а не {out.strip() or 'неизвестная'}")
    return path


def _version(path: str) -> str:
    return subprocess.run([path, "--version"], capture_output=True, text=True, check=True, timeout=30).stdout.strip()


def _client(dsn: str) -> tuple[str, dict, str | None]:
    """conninfo без пароля для --dbname, окружение с PGPASSWORD и сам пароль — чтобы вычистить его из ошибок."""
    params = conninfo_to_dict(dsn)
    password = params.pop("password", None)
    env = dict(os.environ)
    if password:
        env["PGPASSWORD"] = password
    return make_conninfo(**params), env, password


def _run(argv: list[str], env: dict, password: str | None, stage: str) -> None:
    try:
        result = subprocess.run(argv, env=env, capture_output=True, text=True, check=False)
    except OSError as e:
        raise BackupError(f"{stage}: {argv[0]} не запускается: {e}") from None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-2000:]
        if password:
            detail = detail.replace(password, "***")
        raise BackupError(f"{stage}: {Path(argv[0]).name} завершился с кодом {result.returncode}: {detail}")


def _close(stream) -> None:
    try:
        stream.close()
    except OSError:
        pass


def _restore_via_sql(pg_restore: str, psql: str, dump: Path, conninfo: str, env: dict, password: str | None) -> None:
    """pg_restore 18 начинает восстановление с SET transaction_timeout — такого параметра нет у серверов до 17.
    Поэтому для них: pg_restore -1 пишет SQL одной транзакцией, из его заголовка эта строка убирается, psql выполняет
    его и останавливается на первой ошибке. Все COMMIT вне данных COPY придерживаются, и один COMMIT пишется в конце,
    только когда pg_restore завершился успешно: оборванный на середине pg_restore оставляет psql без COMMIT, и сервер
    откатывает всё."""
    with tempfile.TemporaryFile() as restore_err, tempfile.TemporaryFile() as psql_err:
        producer = subprocess.Popen([pg_restore, "--single-transaction", "--file=-", "--no-owner",
                                     "--no-privileges", str(dump)], stdout=subprocess.PIPE, stderr=restore_err, env=env)
        consumer = subprocess.Popen([psql, "--no-psqlrc", "--quiet", "--no-password", "--set=ON_ERROR_STOP=1",
                                     f"--dbname={conninfo}"],
                                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=psql_err, env=env)
        psql_stopped, in_copy = False, False
        try:
            try:
                consumer.stdin.write(b"BEGIN;\n")
                for number, line in enumerate(producer.stdout):
                    stripped = line.strip()
                    if in_copy:
                        in_copy = stripped != b"\\."              # данные COPY — до строки «\.»
                    elif stripped.startswith(b"COPY ") and stripped.endswith(b"FROM stdin;"):
                        in_copy = True
                    elif stripped == b"COMMIT;":
                        continue                                  # фиксирует только наш COMMIT в конце
                    elif number < HEADER_LINES and stripped == b"SET transaction_timeout = 0;":
                        continue
                    consumer.stdin.write(line)
                if producer.wait() == 0:
                    consumer.stdin.write(b"COMMIT;\n")
            except BrokenPipeError:
                psql_stopped = True                       # psql остановился на ошибке — она в его stderr
        except BaseException:                             # прерывание: оба процесса — сразу, без COMMIT
            producer.kill()
            consumer.kill()
            raise
        finally:
            _close(producer.stdout)
            _close(consumer.stdin)
            produced, consumed = producer.wait(), consumer.wait()
        # причина — первой: psql перестал читать — его ошибка; иначе упавший pg_restore
        failed = [(name, code, err) for name, code, err in
                  (("psql", consumed, psql_err), ("pg_restore", produced, restore_err)) if code != 0]
        if not psql_stopped and produced != 0:
            failed.sort(key=lambda item: item[0] != "pg_restore")
        parts = []
        for name, code, err in failed:
            err.seek(0)
            detail = err.read().decode("utf-8", "replace").strip()[-2000:]
            if password:
                detail = detail.replace(password, "***")
            parts.append(f"{name} завершился с кодом {code}: {detail}")
        if parts:
            raise BackupError("pg_restore: " + "; ".join(parts))


def _with_db(dsn: str, dbname: str) -> str:
    params = conninfo_to_dict(dsn)
    params["dbname"] = dbname
    return make_conninfo(**params)


# Файлы


def _stamp(now: datetime | None) -> tuple[str, str]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise BackupError("now: нужно время с часовым поясом")
    now = now.astimezone(timezone.utc)
    return now.strftime("%Y-%m-%dT%H-%M-%SZ"), now.isoformat()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _fsync(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _place(tmp: Path, final: Path) -> None:
    """Готовый файл — на место без перезаписи: жёсткая ссылка не заменяет существующий файл (копию, только что
    сделанную другим процессом в ту же секунду). На файловой системе без жёстких ссылок — переименование."""
    try:
        os.link(tmp, final)
    except FileExistsError:
        tmp.unlink(missing_ok=True)
        raise BackupError(f"{final.name} уже есть — существующая копия не перезаписывается") from None
    except OSError:
        if final.exists():
            tmp.unlink(missing_ok=True)
            raise BackupError(f"{final.name} уже есть — существующая копия не перезаписывается") from None
        os.replace(tmp, final)
    else:
        tmp.unlink()
    _fsync(final.parent)


def _write_json(path: Path, data: dict, *, exclusive: bool = False) -> None:
    """JSON атомарно: временный файл, fsync, переименование (exclusive — без перезаписи), fsync папки."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _fsync(tmp)
    if exclusive:
        _place(tmp, path)
        return
    os.replace(tmp, path)
    _fsync(path.parent)


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise BackupError(f"{path}: манифест не читается: {e}") from None
    if not isinstance(data, dict):
        raise BackupError(f"{path}: манифест — не объект JSON")
    return data


def _inside(root: Path, rel: str, what: str) -> Path:
    """Путь из манифеста — относительный, без «..», внутри root и не через ссылку."""
    if not isinstance(rel, str) or not rel or "\\" in rel or "\x00" in rel:
        raise BackupError(f"{what}: недопустимый путь {rel!r}")
    pure = PurePosixPath(rel)
    if pure.is_absolute() or ".." in pure.parts or pure.parts[0] in ("", "."):
        raise BackupError(f"{what}: путь {rel!r} выходит за корень")
    path = root.joinpath(*pure.parts)
    current = root
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise BackupError(f"{what}: {rel!r} — символическая ссылка")
    if root.resolve() not in path.resolve().parents:
        raise BackupError(f"{what}: путь {rel!r} выходит за корень")
    return path


# Дамп и манифест


def _facts(conn: psycopg.Connection) -> dict:
    """base_id, миграции, числа записей и пробный запрос — в той же транзакции, что снимок дампа."""
    row = conn.execute("SELECT value FROM meta WHERE key = 'base_id'").fetchone()
    if row is None:
        raise BackupError("в базе нет base_id — это не база amem или db.prepare ещё не выполнялся")
    migrations = [{"name": name, "sha256": digest} for name, digest in
                  conn.execute("SELECT name, sha256 FROM schema_migrations ORDER BY name")]
    counts = {table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in COUNTED}
    # пробный атом — тот, чья подпись даёт непустой полнотекстовый запрос и находит его поисковый документ
    probe = conn.execute(
        "SELECT r.atom_id, r.payload->'label'->>'ru' FROM atom_current r JOIN atom a ON a.id = r.atom_id "
        "JOIN search_document d ON d.target = 'atom' AND d.record_id = r.atom_id "
        "WHERE a.status IN ('draft', 'needs_review', 'auto_verified', 'verified') "
        "AND coalesce(r.payload->'label'->>'ru', '') <> '' "
        "AND numnode(websearch_to_tsquery('russian', r.payload->'label'->>'ru')) > 0 "
        "AND d.search_vector @@ websearch_to_tsquery('russian', r.payload->'label'->>'ru') "
        "ORDER BY r.recorded_at DESC, r.atom_id LIMIT 1").fetchone()
    return {
        "base_id": row[0], "migrations": migrations, "counts": counts,
        "server_version": conn.execute("SHOW server_version").fetchone()[0],
        "probe": {"ref": f"atm:{probe[0]}", "query": probe[1]} if probe else None,
    }


def _dump(dsn: str, backup_dir: Path, name: str, created_at: str, *, during=None) -> dict:
    """Пара дамп + манифест; during(conn) вызывается в транзакции снимка до pg_dump (так снимок копирует объекты)."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    dump, manifest = backup_dir / f"{name}.dump", backup_dir / f"{name}.json"
    tmp = backup_dir / f"{name}.dump.tmp"
    if dump.exists() or manifest.exists() or manifest.with_name(manifest.name + ".tmp").exists():
        raise BackupError(f"копия {name} уже есть — существующая копия не перезаписывается")
    pg_dump = _tool("pg_dump")
    conninfo, env, password = _client(dsn)
    try:
        os.close(os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))     # временный файл — только наш
    except FileExistsError:
        raise BackupError(f"копия {name} уже пишется или осталась от сбоя ({tmp.name})") from None
    try:
        with psycopg.connect(dsn) as conn:                   # не autocommit: снимок живёт, пока жива транзакция
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            conn.execute("SET LOCAL idle_in_transaction_session_timeout = 0")       # pg_dump может идти долго
            if conn.info.server_version >= 170000:
                conn.execute("SET LOCAL transaction_timeout = 0")
            snapshot = conn.execute("SELECT pg_export_snapshot()").fetchone()[0]
            if during is not None:
                during(conn)                                 # первым: снимок держит блокировку объектов как можно короче
            facts = _facts(conn)
            _run([pg_dump, "--format=custom", f"--snapshot={snapshot}", "--no-password", f"--file={tmp}",
                  f"--dbname={conninfo}"], env, password, "pg_dump")
            try:
                conn.rollback()
            except psycopg.Error:
                pass                                         # pg_dump уже прочитал снимок — дамп цел
    except psycopg.Error as e:
        tmp.unlink(missing_ok=True)
        raise BackupError(f"база: {type(e).__name__}: {str(e).replace(password, '***') if password else e}") from None
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    _fsync(tmp)
    size, digest = tmp.stat().st_size, _sha256(tmp)
    _place(tmp, dump)
    data = {"format": FORMAT, "kind": "amem.pg_dump", "file": dump.name, "size": size, "sha256": digest,
            "created_at": created_at, "pg_dump_version": _version(pg_dump),
            "search_text_version": SEARCH_TEXT_VERSION, **facts}
    try:
        _write_json(manifest, data, exclusive=True)
    except BaseException:
        dump.unlink(missing_ok=True)                     # дамп наш: манифест на место не встал
        raise
    try:
        check(manifest)                                  # новая пара проверена; не прошла — это не копия
    except BackupError:
        manifest.unlink(missing_ok=True)
        dump.unlink(missing_ok=True)
        raise
    return {**data, "dump": str(dump), "manifest": str(manifest)}


def create(dsn: str, backup_dir: Path, *, keep: int | None = KEEP, now: datetime | None = None) -> dict:
    """Дамп с манифестом; после проверки новой пары — ротация до keep полных пар (None — без ротации).
    Новая копия ротацией не удаляется, даже если часы ушли назад и её имя — не самое позднее."""
    if keep is not None and (isinstance(keep, bool) or not isinstance(keep, int) or keep < 1):
        raise BackupError("keep: нужно целое от 1 или None")
    name, created_at = _stamp(now)
    made = _dump(dsn, Path(backup_dir), name, created_at)
    if keep is not None:
        rotate(backup_dir, keep, protect=name)
    return made


def check(manifest: Path) -> dict:
    """Манифест дампа читается, его файл лежит рядом (не через ссылку), размер и SHA-256 сходятся."""
    manifest = Path(manifest)
    data = _read_json(manifest)
    if data.get("format") != FORMAT or data.get("kind") != "amem.pg_dump":
        raise BackupError(f"{manifest}: неизвестный формат манифеста ({data.get('kind')!r}, {data.get('format')!r})")
    file = data.get("file")
    if not isinstance(file, str) or PurePosixPath(file).name != file:
        raise BackupError(f"{manifest}: файл дампа {file!r} — не имя файла в той же папке")
    dump = _inside(manifest.parent, file, str(manifest))
    if not dump.is_file():
        raise BackupError(f"{manifest}: нет дампа {file}")
    if dump.stat().st_size != data.get("size") or _sha256(dump) != data.get("sha256"):
        raise BackupError(f"{manifest}: дамп {file} не совпадает с манифестом (размер или SHA-256)")
    for key in ("base_id", "migrations", "counts"):
        if key not in data:
            raise BackupError(f"{manifest}: в манифесте нет {key}")
    return data


def backups(backup_dir: Path) -> list[dict]:
    """Готовые копии по возрастанию времени: манифест читается, дамп рядом и его размер сходится.

    SHA-256 здесь не пересчитывается — его проверяют create (у новой копии), check и restore."""
    out = []
    for manifest in sorted(Path(backup_dir).glob("*.json")):
        if not NAME.fullmatch(manifest.stem) or manifest.is_symlink():
            continue
        try:
            data = _read_json(manifest)
        except BackupError:
            continue
        dump = manifest.with_suffix(".dump")
        if (data.get("kind") == "amem.pg_dump" and data.get("file") == dump.name and dump.is_file()
                and not dump.is_symlink() and dump.stat().st_size == data.get("size")):
            out.append({"name": manifest.stem, "manifest": str(manifest), "dump": str(dump)})
    return out


def rotate(backup_dir: Path, keep: int = KEEP, *, protect: str | None = None) -> list[str]:
    """Удалить готовые копии сверх последних keep; .tmp, битые и неполные не трогаются и не считаются.
    Копия protect (только что сделанная) остаётся всегда и входит в keep."""
    if isinstance(keep, bool) or not isinstance(keep, int) or keep < 1:
        raise BackupError("keep: нужно целое от 1")
    ready = backups(backup_dir)
    kept = [item for item in ready if item["name"] == protect]
    others = [item for item in ready if item["name"] != protect]
    room = keep - len(kept)
    removed = []
    for item in (others[:-room] if room > 0 else others):
        Path(item["manifest"]).unlink(missing_ok=True)   # сначала манифест: дамп без него — уже не копия
        Path(item["dump"]).unlink(missing_ok=True)
        removed.append(item["name"])
    if removed:
        _fsync(Path(backup_dir))
    return removed


# Полный снимок


def _check_entries(folder: Path, names: list[str]) -> None:
    """В хранилище — только папки и обычные файлы: ссылки, FIFO и устройства — ошибка (FIFO повесил бы чтение)."""
    for name in names:
        mode = os.lstat(folder / name).st_mode
        if stat.S_ISLNK(mode):
            raise BackupError(f"{folder / name}: символическая ссылка в хранилище объектов")
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise BackupError(f"{folder / name}: не файл и не папка")


def _copy_tree(src: Path, dst: Path) -> list[dict]:
    """Копия дерева без ссылок и особых файлов; у каждого файла — путь, размер и SHA-256 копии; файлы и папки
    сброшены на диск."""
    files = []
    dst.mkdir(parents=True)
    copied_dirs = [dst]
    for folder, dirs, names in os.walk(src, followlinks=False):
        folder = Path(folder)
        _check_entries(folder, sorted(dirs + names))
        dirs.sort()
        rel_folder = folder.relative_to(src)
        for d in dirs:
            (dst / rel_folder / d).mkdir()
            copied_dirs.append(dst / rel_folder / d)
        for name in sorted(names):
            source, target = folder / name, dst / rel_folder / name
            h = hashlib.sha256()
            with open(source, "rb") as fin, open(target, "wb") as fout:
                for chunk in iter(lambda: fin.read(CHUNK), b""):
                    h.update(chunk)
                    fout.write(chunk)
                fout.flush()
                os.fsync(fout.fileno())
            files.append({"path": (rel_folder / name).as_posix(), "size": target.stat().st_size,
                          "sha256": h.hexdigest()})
    for folder in reversed(copied_dirs):
        _fsync(folder)
    return files


def _file_versions(conn: psycopg.Connection) -> list[dict]:
    return [{"object": str(object_id), "n": n, "digest": digest} for object_id, n, digest in conn.execute(
        "SELECT object_id, n, digest FROM object_version WHERE digest IS NOT NULL ORDER BY object_id, n")]


def _check_store(root: Path, versions: list[dict], what: str) -> None:
    """Каждая версия файла из списка есть в хранилище, и её содержимое — тот же digest."""
    store = ObjectStore(root)
    for version in versions:
        object_id, n, digest = version["object"], version["n"], version["digest"]
        try:
            path = store.content(object_id, n)
        except (StoreError, OSError, ValueError, KeyError, TypeError) as e:
            raise BackupError(f"{what}: нет версии {n} объекта obj:{object_id} ({e})") from None
        if not path.is_file() or "sha256:" + _sha256(path) != digest:
            raise BackupError(f"{what}: версия {n} объекта obj:{object_id} не совпадает с digest")


def snapshot(dsn: str, objects_root: Path, snapshot_dir: Path, *, now: datetime | None = None) -> dict:
    """Полный снимок: pg/<имя>.dump и .json, objects/ (корень OCFL), manifest.json. Сбой не оставляет готового каталога."""
    name, created_at = _stamp(now)
    snapshot_dir, objects_root = Path(snapshot_dir), Path(objects_root)
    target, tmp = snapshot_dir / name, snapshot_dir / f"{name}.tmp"
    if target.exists() or tmp.exists():
        raise BackupError(f"снимок {name} уже есть — существующий снимок не перезаписывается")
    if objects_root.is_symlink() or (objects_root.exists() and not objects_root.is_dir()):
        raise BackupError(f"{objects_root}: не папка хранилища объектов")
    if objects_root.exists() and any(objects_root.iterdir()) and not (objects_root / "0=ocfl_1.1").is_file():
        raise BackupError(f"{objects_root}: не корень OCFL (нет 0=ocfl_1.1) — в снимок попало бы чужое")
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    tmp.mkdir()
    state = {}
    try:
        with psycopg.connect(dsn, autocommit=True) as lock:
            # блокировка записи объектов — до снимка транзакции: запись версии, начатая раньше, успеет
            # зафиксироваться и попадёт в снимок, а новая не начнётся, пока хранилище копируется
            lock.execute("SET idle_session_timeout = 0")     # блокировка не пропадёт посреди долгой копии
            lock.execute("SELECT pg_advisory_lock(%s)", (OBJECTS_LOCK,))
            state["locked"] = True
            try:
                def copy_objects(conn):
                    versions = _file_versions(conn)      # в снимке дампа
                    if objects_root.exists():
                        with ObjectStore(objects_root)._locked():
                            files = _copy_tree(objects_root, tmp / "objects")
                    elif versions:
                        raise BackupError(f"{objects_root}: корня хранилища нет, а в базе {len(versions)} "
                                          "версий файлов")
                    else:
                        (tmp / "objects").mkdir()
                        files = []
                    lock.execute("SELECT pg_advisory_unlock(%s)", (OBJECTS_LOCK,))   # pg_dump читает тот же снимок
                    state.update(locked=False, versions=versions, files=files)

                dump = _dump(dsn, tmp / "pg", name, created_at, during=copy_objects)
            finally:
                if state.get("locked"):
                    lock.execute("SELECT pg_advisory_unlock(%s)", (OBJECTS_LOCK,))
        if state["versions"]:
            _check_store(tmp / "objects", state["versions"], "снимок")
        data = {"format": FORMAT, "kind": "amem.snapshot", "created_at": created_at, "base_id": dump["base_id"],
                "dump": {"manifest": f"pg/{Path(dump['manifest']).name}",
                         "sha256": _sha256(Path(dump["manifest"]))},
                "objects": {"root": "objects", "files": state["files"], "file_versions": state["versions"]}}
        _write_json(tmp / "manifest.json", data)
        os.replace(tmp, target)
        _fsync(snapshot_dir)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return {**data, "path": str(target)}


def _read_snapshot(root: Path) -> tuple[dict, Path]:
    """Корневой манифест снимка и манифест его дампа; всё проверено до какой-либо записи."""
    data = _read_json(root / "manifest.json")
    if data.get("format") != FORMAT or data.get("kind") != "amem.snapshot":
        raise BackupError(f"{root}: неизвестный формат снимка ({data.get('kind')!r}, {data.get('format')!r})")
    dump_info, objects = data.get("dump") or {}, data.get("objects") or {}
    manifest = _inside(root, dump_info.get("manifest"), f"{root}: dump")
    if not manifest.is_file() or _sha256(manifest) != dump_info.get("sha256"):
        raise BackupError(f"{root}: манифест дампа не совпадает со снимком")
    dump = check(manifest)
    if dump.get("base_id") != data.get("base_id"):
        raise BackupError(f"{root}: base_id дампа и снимка разные")
    objects_dir = _inside(root, objects.get("root"), f"{root}: objects")
    for folder, dirs, names in os.walk(objects_dir, followlinks=False):
        _check_entries(Path(folder), dirs + names)
    versions = objects.get("file_versions")
    if not isinstance(versions, list) or not all(
            isinstance(v, dict) and isinstance(v.get("object"), str) and isinstance(v.get("n"), int)
            and isinstance(v.get("digest"), str) for v in versions):
        raise BackupError(f"{root}: в манифесте снимка нет списка версий файлов")
    listed = set()
    files = objects.get("files")
    if not isinstance(files, list) or not all(isinstance(item, dict) for item in files):
        raise BackupError(f"{root}: в манифесте снимка нет списка файлов хранилища")
    for item in files:
        path = _inside(objects_dir, item.get("path"), f"{root}: objects")
        if not path.is_file() or path.stat().st_size != item.get("size") or _sha256(path) != item.get("sha256"):
            raise BackupError(f"{root}: файл хранилища {item.get('path')} не совпадает с манифестом")
        listed.add(path.relative_to(objects_dir).as_posix())
    actual = {p.relative_to(objects_dir).as_posix() for p in objects_dir.rglob("*") if not p.is_dir()}
    if actual != listed:
        raise BackupError(f"{root}: в копии хранилища лишние или недостающие файлы: "
                          f"{', '.join(sorted(actual ^ listed)[:5])}")
    return data, manifest


# Восстановление


def _require_empty_db(dsn: str) -> int:
    """Пустая база — без своих таблиц, представлений, функций и схем (объекты расширений не в счёт);
    вернуть server_version_num."""
    system = ("n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname NOT LIKE 'pg\\_toast%%' "
              "AND n.nspname NOT LIKE 'pg\\_temp%%'")

    def own(catalog: str, alias: str) -> str:
        return (f"NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = '{catalog}'::regclass "
                f"AND d.objid = {alias}.oid AND d.deptype = 'e')")

    with psycopg.connect(dsn, autocommit=True) as conn:
        version = int(conn.execute("SHOW server_version_num").fetchone()[0])
        row = conn.execute(
            f"SELECT (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            f"WHERE {system} AND {own('pg_class', 'c')}) "
            f"+ (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            f"WHERE {system} AND {own('pg_proc', 'p')}) "
            f"+ (SELECT count(*) FROM pg_namespace n WHERE {system} AND n.nspname <> 'public' "
            f"AND {own('pg_namespace', 'n')}) "
            # свои домены, перечисления, диапазоны и составные типы (не строки таблиц и не массивы)
            f"+ (SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace "
            f"WHERE {system} AND {own('pg_type', 't')} AND (t.typtype IN ('d', 'e', 'r') "
            f"OR (t.typtype = 'c' AND EXISTS (SELECT 1 FROM pg_class c WHERE c.oid = t.typrelid "
            f"AND c.relkind = 'c'))))").fetchone()
    if row[0]:
        raise BackupError("целевая база не пустая — восстановление только в пустую базу")
    return version


def _require_empty_dir(path: Path) -> None:
    if path.is_symlink() or (path.exists() and (not path.is_dir() or any(path.iterdir()))):
        raise BackupError(f"{path}: папка объектов не пустая — восстановление только в пустую или новую")


def restore(source: Path, dsn: str, *, objects_root: Path | None = None) -> dict:
    """Дамп (манифест .json) или полный снимок (каталог) → пустая база и, для снимка, пустая папка объектов."""
    source = Path(source)
    if source.is_dir():
        snap, manifest = _read_snapshot(source)
        objects_src = source / snap["objects"]["root"]
        if objects_root is None:
            raise BackupError(f"{source}: для снимка нужен objects_root — куда восстановить хранилище объектов")
    else:
        snap, manifest, objects_src = None, source, None
        if objects_root is not None:
            raise BackupError(f"{source}: в дампе без снимка нет хранилища объектов")
    dump = check(manifest)
    if objects_root is not None:
        objects_root = Path(objects_root)
        _require_empty_dir(objects_root)
    pg_restore = _tool("pg_restore")
    server = _require_empty_db(dsn)
    psql = _tool("psql") if server < 170000 else None
    conninfo, env, password = _client(dsn)
    # объекты — во временную папку рядом с целью; копия сверяется с манифестом и списком версий до записи в базу,
    # на место встаёт одним переименованием, когда база восстановлена и сверена: сбой не оставляет полусобранной папки
    tmp = (objects_root.parent / f".{objects_root.name}.restore-{uuid.uuid4().hex[:12]}.tmp"
           if objects_root is not None else None)
    try:
        if tmp is not None:
            copied = _copy_tree(objects_src, tmp)
            if sorted(copied, key=lambda item: item["path"]) != sorted(snap["objects"]["files"],
                                                                         key=lambda item: item["path"]):
                raise BackupError(f"{source}: копия хранилища не совпадает с манифестом снимка")
            _check_store(tmp, snap["objects"]["file_versions"], "восстановление")
        if server >= 170000:
            _run([pg_restore, "--exit-on-error", "--single-transaction", "--no-owner", "--no-privileges",
                  "--no-password", f"--dbname={conninfo}", str(manifest.parent / dump["file"])], env, password,
                 "pg_restore")
        else:
            _restore_via_sql(pg_restore, psql, manifest.parent / dump["file"], conninfo, env, password)
        with psycopg.connect(dsn, autocommit=True) as conn:
            facts = _facts(conn)
            for key in ("base_id", "migrations", "counts"):
                if facts[key] != dump[key]:
                    raise BackupError(f"восстановление: {key} не совпадает с манифестом")
            versions = _file_versions(conn)
        report = {"base_id": facts["base_id"], "migrations": [m["name"] for m in facts["migrations"]],
                  "counts": facts["counts"], "objects": None}
        if tmp is not None:
            if versions != snap["objects"]["file_versions"]:
                raise BackupError("восстановление: версии файлов в базе не совпадают со снимком")
            if objects_root.exists():
                objects_root.rmdir()
            os.replace(tmp, objects_root)
            report["objects"] = {"root": str(objects_root), "file_versions": len(versions)}
    except BaseException:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
        raise
    return report


def verify(source: Path, dsn: str, *, provider=None, scratch: Path | None = None) -> dict:
    """Пробное восстановление во временную базу того же сервера и поиск; база и временная папка удаляются
    при любом исходе. Копия хранилища снимка — во временной папке внутри scratch (по умолчанию — системная).

    Поиск — полнотекстовый по подписи пробного атома из манифеста: его поисковый документ должен находиться этим
    запросом, а сам запрос — давать выдачу; модель и сеть не нужны. С provider ещё и полный exact_fact с векторами.
    Рабочая база не меняется."""
    from . import recipes, search

    source = Path(source)
    name = f"amem_verify_{uuid.uuid4().hex[:12]}"
    temp_dsn = _with_db(dsn, name)
    _, _, password = _client(dsn)
    stage = "создание временной базы"
    workdir, created, done, left = None, False, False, ""
    try:
        try:
            try:
                workdir = Path(tempfile.mkdtemp(prefix="amem-verify-", dir=scratch))
            except OSError as e:
                raise BackupError(f"временная папка не создаётся: {e}") from None
            with psycopg.connect(dsn, autocommit=True) as admin:
                admin.execute(f'CREATE DATABASE "{name}"')
            created = True
            stage = "восстановление"
            report = restore(source, temp_dsn, objects_root=workdir / "objects" if source.is_dir() else None)
            stage = "поиск"
            if source.is_dir():
                manifest = _inside(source, _read_json(source / "manifest.json")["dump"]["manifest"], str(source))
            else:
                manifest = source
            probe = _read_json(manifest).get("probe")
            found = None
            if probe:
                with psycopg.connect(temp_dsn, autocommit=True) as conn:
                    row = conn.execute(
                        "SELECT d.search_vector @@ websearch_to_tsquery('russian', %s) FROM search_document d "
                        "WHERE d.target = 'atom' AND d.record_id = %s",
                        (probe["query"], probe["ref"].split(":", 1)[1])).fetchone()
                    found = bool(row and row[0])
                    if not found:
                        raise BackupError(f"атом {probe['ref']} не находится по своей подписи")
                    if not search._fts(conn, probe["query"], target="atom"):
                        raise BackupError("полнотекстовый поиск по пробной подписи ничего не вернул")
                    if provider is not None:
                        result = recipes.exact_fact(conn, probe["query"], agent=VERIFY_AGENT, provider=provider)
                        if not result["items"]:
                            raise BackupError("exact_fact по пробной подписи ничего не вернул")
            report["search"] = {"probe": probe, "found": found}
            done = True
            return report
        finally:
            cleanup = None
            if created:
                try:
                    with psycopg.connect(dsn, autocommit=True) as admin:
                        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
                except psycopg.Error as e:
                    cleanup = e
                    left = f" (временная база {name} осталась: {type(e).__name__})"
            if workdir is not None:
                shutil.rmtree(workdir, ignore_errors=True)
            if cleanup is not None and done:                 # при другой ошибке она важнее — не подменяем её
                stage = "удаление временной базы"
                raise cleanup
    except BackupError as e:
        raise BackupError(f"verify: {stage}: {e}{left}") from None
    except psycopg.Error as e:
        detail = str(e).replace(password, "***") if password else str(e)
        raise BackupError(f"verify: {stage}: {type(e).__name__}: {detail}{left}") from None
