"""Хранилище копий файлов-источников: корень OCFL 1.1 с раскладкой 0004-hashed-n-tuple-storage-layout.

Объект OCFL — один логический документ, его id — obj:<UUID> объекта базы. Версия (v1, v2…) — состояние файла:
в каждой версии один файл, логическое имя — исходное имя файла в NFC; имя на диске длиннее 255 байт укорачивается
с тем же расширением. Алгоритм дайджеста — sha256, тот же хэш, что digest источника. Содержимое, уже лежащее
в объекте, второй раз не копируется (manifest OCFL).

Модуль не знает о базе: id и номер версии даёт вызывающий (amemo/objects.py), он же держит блокировку базы —
два процесса в один корень разом не пишут; init() и запись берут ещё и блокировку файла <корень>.lock, чтобы
init() без блокировки базы не разбирал чужую запись на ходу. Номер версии вызывающий берёт из базы, поэтому
версия новее записанных базой — след сбоя: база её не знает.

Запись устроена так, чтобы сбой в любом месте не портил корень надолго:
- работа идёт во временной папке <корень>.tmp — на той же файловой системе, что корень; первым в неё пишется
  отметка, какой объект пишется;
- файл копируется туда с подсчётом хэша; файлы и папки сбрасываются на диск (fsync) до переименований;
- новый объект собирается там целиком и встаёт на место одним переименованием;
- у существующего объекта vN (её inventory.json уже внутри) переносится в объект, затем заменяются корневой
  inventory.json и его sidecar — каждый через временный файл;
- исключение посреди записи сразу возвращает объект к его корневому inventory; после жёсткого сбоя то же
  делает следующая запись или init() — по отметкам во временной папке: лишние vN удаляются, sidecar
  сверяется с inventory, пустые папки раскладки убираются; перед записью объект приводится в порядок всегда;
- починка ничего записанного не удаляет: объект без корневого inventory (его могли тронуть вручную) получает
  inventory своей старшей версии, если она цела; иначе — ошибка, разбор вручную;
- версия N, которую хранилище записало, а база нет: запись того же содержимого с тем же N принимает её как есть,
  другого — откатывает её (корневой inventory из v(N-1); v1 — весь объект переносом во временную папку)
  и пишет заново.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

LAYOUT = "0004-hashed-n-tuple-storage-layout"
LAYOUT_CONFIG = {"extensionName": LAYOUT, "digestAlgorithm": "sha256", "tupleSize": 3, "numberOfTuples": 3,
                 "shortObjectRoot": False}
LAYOUT_JSON = {"extension": LAYOUT, "description": "Hashed N-tuple Storage Layout (sha256, 3 × 3)"}
INVENTORY_TYPE = "https://ocfl.io/1.1/spec/#inventory"
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
VERSION_DIR = re.compile(r"^v[1-9][0-9]*$")
MARK = "object"                # файл-отметка во временной папке: id объекта, который пишется
NAME_BYTES = 255               # предел длины имени файла (ext4)
CHUNK = 1 << 20


class StoreError(RuntimeError):
    pass


def ocfl_id(object_id: uuid.UUID | str) -> str:
    return f"obj:{uuid.UUID(str(object_id))}"


def layout_path(identifier: str) -> str:
    """Путь объекта в корне по раскладке 0004: sha256 id, три части по 3 знака и весь хэш."""
    h = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
    return f"{h[0:3]}/{h[3:6]}/{h[6:9]}/{h}"


def disk_name(name: str) -> str:
    """Имя копии на диске: исходное, а длиннее 255 байт — укороченное по границе символа, с тем же расширением."""
    if len(name.encode("utf-8")) <= NAME_BYTES:
        return name
    base, dot, ext = name.rpartition(".")
    suffix = f".{ext}" if dot and base and len(ext.encode("utf-8")) <= 15 else ""
    stem = name[:len(name) - len(suffix)].encode("utf-8")[:NAME_BYTES - len(suffix.encode("utf-8"))]
    return stem.decode("utf-8", errors="ignore") + suffix


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _json(data: dict) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _sidecar(raw: bytes) -> bytes:
    return f"{hashlib.sha256(raw).hexdigest()} inventory.json\n".encode("utf-8")


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write(path: Path, raw: bytes) -> None:
    """Файл через временный рядом: на месте всегда либо старое содержимое, либо новое целиком — и уже на диске."""
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    _fsync_dir(path.parent)


class ObjectStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.deposit = self.root.with_name(self.root.name + ".tmp")
        self.lockfile = self.root.with_name(self.root.name + ".lock")

    @contextmanager
    def _locked(self):
        """Блокировка файла рядом с корнем: init() и запись в одном корне идут по очереди и между процессами."""
        self.lockfile.parent.mkdir(parents=True, exist_ok=True)
        with open(self.lockfile, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    # корень

    def init(self, *, create: bool) -> None:
        """Проверить корень и разобрать следы прерванной записи. Вызывать под той же блокировкой, что и запись.

        Корня нет — создать, только если create. Пустая папка на месте хранилища, файлы которого база уже знает, —
        это неподключённый том (пустой tmpfs вместо data после перезагрузки), а не новое хранилище."""
        with self._locked():
            if not (self.root / "0=ocfl_1.1").is_file():
                if not create:
                    raise StoreError(f"{self.root}: корня хранилища нет — папка данных не подключена?")
                self._create()
            try:
                layout = json.loads((self.root / "ocfl_layout.json").read_text(encoding="utf-8"))
                config = json.loads((self.root / "extensions" / LAYOUT / "config.json").read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                raise StoreError(f"{self.root}: раскладка корня не читается: {e}") from e
            if layout.get("extension") != LAYOUT or config != LAYOUT_CONFIG:
                raise StoreError(f"{self.root}: у корня другая раскладка, нужна {LAYOUT} {LAYOUT_CONFIG}")
            self._recover()

    def _create(self) -> None:
        leftovers = {"0=ocfl_1.1.tmp", "ocfl_layout.json.tmp"}  # временные файлы прерванного создания
        names = {p.name for p in self.root.iterdir()} if self.root.exists() else set()
        if names - {"extensions", "ocfl_layout.json"} - leftovers:       # недостроенный корень достраивается
            raise StoreError(f"{self.root}: папка не пуста и это не корень OCFL — писать в неё нельзя")
        for name in leftovers:
            (self.root / name).unlink(missing_ok=True)
        ext = self.root / "extensions" / LAYOUT
        ext.mkdir(parents=True, exist_ok=True)
        _write(ext / "config.json", _json(LAYOUT_CONFIG))
        _write(self.root / "ocfl_layout.json", _json(LAYOUT_JSON))
        _write(self.root / "0=ocfl_1.1", b"ocfl_1.1\n")        # последним: корень готов

    def _recover(self) -> None:
        """Следы прерванной записи: объект из каждой отметки — к его корневому inventory, временные папки — прочь."""
        if not self.deposit.is_dir():
            return
        for work in self.deposit.iterdir():
            mark = work / MARK
            if mark.is_file():
                self._repair(uuid.UUID(mark.read_text(encoding="utf-8").strip()))
            shutil.rmtree(work, ignore_errors=True)

    def _repair(self, object_id: uuid.UUID) -> None:
        """Объект — к его корневому inventory: лишние vN прочь, sidecar — по inventory. Записанное не удаляется:
        объекта нет — убрать пустые папки раскладки; нет корневого inventory — взять inventory старшей версии."""
        obj = self.object_dir(object_id)
        path = obj / "inventory.json"
        if not obj.exists():
            self._prune(obj.parent)
            return
        if not path.is_file():
            self._restore_inventory(obj)
        raw = path.read_bytes()
        head = int(json.loads(raw)["head"][1:])
        for d in obj.iterdir():
            if VERSION_DIR.fullmatch(d.name) and int(d.name[1:]) > head:
                shutil.rmtree(d)
            elif d.name.endswith(".tmp"):
                d.unlink()
        sidecar = obj / "inventory.json.sha256"
        head_raw = obj / f"v{head}" / "inventory.json"
        # sidecar пересчитывается только для inventory, который записали мы (он равен inventory своей версии):
        # правленый вручную inventory должен остаться виден валидатору
        if head_raw.is_file() and head_raw.read_bytes() == raw and (
                not sidecar.is_file() or sidecar.read_bytes() != _sidecar(raw)):
            _write(sidecar, _sidecar(raw))

    @staticmethod
    def _restore_inventory(obj: Path) -> None:
        """Корневой inventory — из старшей версии, если её inventory сходится со своим sidecar. Не цела — ошибка:
        inventory младшей версии сделал бы старшие лишними, и починка удалила бы то, что база, может быть, записала."""
        versions = sorted((int(d.name[1:]), d) for d in obj.iterdir() if VERSION_DIR.fullmatch(d.name))
        if versions:
            d = versions[-1][1]
            raw, sidecar = d / "inventory.json", d / "inventory.json.sha256"
            if raw.is_file() and sidecar.is_file() and sidecar.read_bytes() == _sidecar(raw.read_bytes()):
                _write(obj / "inventory.json", raw.read_bytes())
                return
        raise StoreError(f"{obj}: нет корневого inventory.json, а старшая версия не цела — нужен разбор вручную")

    def _prune(self, path: Path) -> None:
        """Пустые папки раскладки от path вверх до корня."""
        while path != self.root and path.is_dir() and not any(path.iterdir()):
            path.rmdir()
            path = path.parent

    # объекты

    def object_dir(self, object_id: uuid.UUID | str) -> Path:
        return self.root / layout_path(ocfl_id(object_id))

    def _inventory(self, object_id: uuid.UUID | str) -> dict | None:
        path = self.object_dir(object_id) / "inventory.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def head(self, object_id: uuid.UUID | str) -> int:
        """Номер последней версии объекта в хранилище; 0 — объекта нет."""
        inventory = self._inventory(object_id)
        return int(inventory["head"][1:]) if inventory else 0

    def content(self, object_id: uuid.UUID | str, n: int) -> Path:
        """Файл версии n — копия, которую видел источник, даже если файл в папке документов изменили."""
        inventory = self._inventory(object_id)
        state = (inventory or {}).get("versions", {}).get(f"v{n}", {}).get("state")
        if not state:
            raise StoreError(f"{ocfl_id(object_id)}: в хранилище нет версии {n}")
        [digest] = state
        return self.object_dir(object_id) / inventory["manifest"][digest][0]

    def add_version(self, object_id: uuid.UUID | str, n: int, src: Path, name: str, digest: str, *, user: str,
                    message: str) -> None:
        """Записать файл src версией n объекта; digest — «sha256:…», который вызывающий посчитал по src.

        Хэш считается заново при копировании: файл, изменившийся после подсчёта, — ошибка, версия не пишется.
        Ошибка файловой системы — StoreError с именем файла; объект при этом возвращается к прежнему состоянию."""
        object_id = uuid.UUID(str(object_id))
        name = unicodedata.normalize("NFC", name)
        if not name or name in (".", "..") or any(c in name for c in "/\\\x00"):
            raise StoreError(f"{name!r}: недопустимое имя файла")
        if not isinstance(n, int) or n < 1:
            raise StoreError(f"номер версии {n!r}: нужно целое от 1")
        if not DIGEST.fullmatch(digest):
            raise StoreError(f"digest {digest!r}: нужен sha256: и 64 знака 0-9a-f")
        if not (self.root / "0=ocfl_1.1").is_file():
            raise StoreError(f"{self.root}: корня хранилища нет — сначала init()")
        with self._locked():
            self._recover()
            self._repair(object_id)                         # перед записью объект — в порядке, что бы с ним ни было
            self.deposit.mkdir(parents=True, exist_ok=True)
            work = Path(tempfile.mkdtemp(dir=self.deposit))
            _fsync_dir(self.deposit)
            try:
                _write(work / MARK, str(object_id).encode("utf-8"))      # первым: по отметке чинит _recover
                self._add(object_id, n, src, name, digest.removeprefix("sha256:"), work, user=user,
                          message=message)
            except BaseException as e:
                self._repair(object_id)
                if isinstance(e, OSError):
                    raise StoreError(f"{name}: копия не записана: {e}") from e
                raise
            finally:
                shutil.rmtree(work, ignore_errors=True)

    def _add(self, object_id: uuid.UUID, n: int, src: Path, name: str, hexdigest: str, work: Path, *, user: str,
             message: str) -> None:
        obj = self.object_dir(object_id)
        inventory = self._inventory(object_id)
        head = int(inventory["head"][1:]) if inventory else 0
        if head > n:
            raise StoreError(f"{ocfl_id(object_id)}: в хранилище есть версии новее {n}, которых база не знает — "
                             "нужен разбор вручную")
        if head == n:
            if list(inventory["versions"][f"v{n}"]["state"]) == [hexdigest] and self.content(object_id, n).is_file():
                return                  # версию записали, а база — нет (сбой после записи): та же
            self._rollback(object_id, n, work)              # база её не знает, а пришло другое содержимое
            inventory, head = self._inventory(object_id), n - 1
        if n != head + 1:
            raise StoreError(f"{ocfl_id(object_id)}: следующая версия — {head + 1}, а не {n}")
        version = f"v{n}"
        vdir = work / version
        content_path = None
        if inventory is None or hexdigest not in inventory["manifest"]:
            (vdir / "content").mkdir(parents=True)
            content_path = f"{version}/content/{disk_name(name)}"
            self._copy(src, work / content_path, hexdigest)
            _fsync_dir(vdir / "content")
        else:
            vdir.mkdir(parents=True)
        if inventory is None:
            inventory = {"id": ocfl_id(object_id), "type": INVENTORY_TYPE, "digestAlgorithm": "sha256",
                         "head": "v0", "contentDirectory": "content", "manifest": {}, "versions": {}}
        if content_path:
            inventory["manifest"][hexdigest] = [content_path]
        inventory["head"] = version
        inventory["versions"][version] = {"created": _now(), "state": {hexdigest: [name]}, "message": message,
                                          "user": {"name": user, "address": user}}
        raw = _json(inventory)
        _write(vdir / "inventory.json", raw)
        _write(vdir / "inventory.json.sha256", _sidecar(raw))
        if head == 0:
            # новый объект собирается целиком и встаёт на место одним переименованием
            staged = work / "staged"
            staged.mkdir()
            _write(staged / "0=ocfl_object_1.1", b"ocfl_object_1.1\n")
            os.replace(vdir, staged / version)
            _write(staged / "inventory.json", raw)
            _write(staged / "inventory.json.sha256", _sidecar(raw))
            missing = [p for p in obj.parents if self.root in p.parents and not p.exists()]
            obj.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, obj)
            for p in {obj.parent, *(m.parent for m in missing)}:
                _fsync_dir(p)
            return
        os.replace(vdir, obj / version)
        _fsync_dir(obj)
        _write(obj / "inventory.json", raw)
        _write(obj / "inventory.json.sha256", _sidecar(raw))

    def _rollback(self, object_id: uuid.UUID, n: int, work: Path) -> None:
        """Откатить версию n, которой база не знает: корневой inventory — из v(n-1), vn — прочь. v1 — весь объект:
        он переносится во временную папку одним переименованием и удаляется уже там."""
        obj = self.object_dir(object_id)
        if n == 1:
            os.replace(obj, work / "rolled-back")
            _fsync_dir(obj.parent)
            shutil.rmtree(work / "rolled-back")
            self._prune(obj.parent)
            return
        raw = (obj / f"v{n - 1}" / "inventory.json").read_bytes()
        _write(obj / "inventory.json", raw)
        _write(obj / "inventory.json.sha256", _sidecar(raw))
        shutil.rmtree(obj / f"v{n}")

    @staticmethod
    def _copy(src: Path, dst: Path, hexdigest: str) -> None:
        h = hashlib.sha256()
        with open(src, "rb") as fin, open(dst, "wb") as fout:
            while chunk := fin.read(CHUNK):
                h.update(chunk)
                fout.write(chunk)
            fout.flush()
            os.fsync(fout.fileno())
        if h.hexdigest() != hexdigest:
            raise StoreError(f"{src.name}: файл изменился, пока его копировали — запишите источник заново")
