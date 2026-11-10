"""Различия POSIX и Windows в одном месте: замок файла, сброс на диск, двоичный os.open, домашняя папка.

- file_lock(path) — исключительный замок между процессами на файле-замке path (нет — создаётся): fcntl.flock на POSIX,
  msvcrt.locking первого байта на Windows; ждёт, пока замок не освободится. Замок держит открытый файл, а не процесс:
  второй file_lock того же пути в том же процессе ждёт так же, как чужой процесс; try_file_lock(path) — то же без
  ожидания: занят — в блок приходит False;
- fsync_dir(path) — переименования и новые файлы папки — на диск. На Windows папку для fsync не открыть (NTFS сама
  журналирует метаданные) — ничего не делает. fsync_path(path) — то же для файла или папки;
- O_BINARY — добавлять к флагам os.open: на Windows без него дескриптор открыт в текстовом режиме, и CRT пишет
  "\\r\\n" вместо "\\n" (а TextIOWrapper поверх такого дескриптора — "\\r\\r\\n");
- home(env) — домашняя папка по окружению env: HOME, а на Windows сначала USERPROFILE — там же свои настройки ищут
  Claude Code и Codex (и Path.home()); ни одной переменной — Path.home().
"""
from __future__ import annotations

import errno
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Mapping

WINDOWS = os.name == "nt"
O_BINARY = getattr(os, "O_BINARY", 0)
LOCK_RETRY = 0.05                       # с между попытками взять занятый замок (Windows)

if WINDOWS:
    import msvcrt

    _BUSY = {errno.EACCES, getattr(errno, "EDEADLOCK", errno.EDEADLK)}

    def _lock(fd: int) -> None:
        # msvcrt.locking запирает байты от текущей позиции; LK_LOCK сдаётся через 10 с — ждём сами, без предела,
        # как flock. Запирать за концом файла можно: файл-замок пустой
        while True:
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return
            except OSError as e:
                if e.errno not in _BUSY:
                    raise
            time.sleep(LOCK_RETRY)

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

    def _try_lock(fd: int) -> bool:
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError as e:
            if e.errno not in _BUSY:
                raise
            return False
else:
    import fcntl

    def _lock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX)

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            return False

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def file_lock(path: Path | str, mode: int = 0o600) -> Iterator[None]:
    """Исключительный замок на файле path на время блока; mode — права нового файла-замка (до umask)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | O_BINARY, mode)
    try:
        _lock(fd)
        try:
            yield
        finally:
            _unlock(fd)
    finally:
        os.close(fd)


@contextmanager
def try_file_lock(path: Path | str, mode: int = 0o600) -> Iterator[bool]:
    """Как file_lock, но без ожидания: в блок приходит True — замок взят, False — его держит другой (тогда блок
    идёт без замка, и решать, что делать, — вызывающему)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | O_BINARY, mode)
    try:
        taken = _try_lock(fd)
        try:
            yield taken
        finally:
            if taken:
                _unlock(fd)
    finally:
        os.close(fd)


def fsync_dir(path: Path | str) -> None:
    if WINDOWS:
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def fsync_path(path: Path | str) -> None:
    """Файл или папку — на диск. На Windows fsync (FlushFileBuffers) требует дескриптор с правом записи."""
    if os.path.isdir(path):
        fsync_dir(path)
        return
    fd = os.open(path, (os.O_RDWR if WINDOWS else os.O_RDONLY) | O_BINARY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def home(env: Mapping[str, str]) -> Path:
    if WINDOWS and env.get("USERPROFILE"):
        return Path(env["USERPROFILE"])
    return Path(env.get("HOME") or Path.home())
