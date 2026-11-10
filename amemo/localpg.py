"""Свой PostgreSQL amemo в папке пользователя (amemo setup, amemo pg): кластер без службы ОС и без прав администратора.

Кластер — каталог pg_data, программы — каталог pg_bin (initdb, pg_ctl, postgres; PostgreSQL 16+ с расширением vector в
его share). Сервер слушает только 127.0.0.1 на своём порту (по умолчанию первый свободный начиная с PORT_FROM), вход —
scram-sha-256. Суперпользователь кластера — роль amemo: кластер принадлежит одному человеку и служит одной базе amemo,
отдельная роль-владелец ничего не защищала бы. Пароль задаёт вызывающий (initdb читает его из временного файла с
правами 0600, файл удаляется сразу после initdb) и хранит в строке подключения amemo.toml.

Запуск и остановка — pg_ctl (-w: ждать готовности); журнал сервера — <pg_data>/log/postgresql.log. На Windows pg_ctl
отвязывает сервер от консоли сам: он живёт и после выхода вызвавшего процесса.
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .portable import WINDOWS

PG_MIN = 16                        # amemo поддерживает PostgreSQL 16+
PORT_FROM = 5436                   # 5432 часто занят чужим PostgreSQL, 5435 — базой compose; дальше — по порядку
PORT_TRIES = 64
ROLE = "amemo"
DATABASE = "amemo"
EXTENSIONS = ("vector", "btree_gist")
START_TIMEOUT = 90                 # с; первый старт на медленном диске Windows бывает долгим
TOOLS = ("initdb", "pg_ctl", "postgres")


def conf_lines(port: int) -> dict[str, str]:
    """Что setup дописывает в postgresql.conf нового кластера (последняя строка параметра побеждает): только TCP на
    127.0.0.1 — без unix-сокета, потому что каталог сокетов сборок Debian (/var/run/postgresql) обычному пользователю
    закрыт, а amemo подключается по TCP; журнал пишет pg_ctl -l."""
    return {"listen_addresses": "'127.0.0.1'", "port": str(port), "unix_socket_directories": "''",
            "logging_collector": "off"}


class LocalPgError(RuntimeError):
    """Кластер нельзя создать, запустить или подготовить; сообщение говорит, что проверить."""


def free_port(start: int = PORT_FROM, host: str = "127.0.0.1", tries: int = PORT_TRIES) -> int:
    """Первый порт от start, который сейчас можно занять на host."""
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((host, port))
            except OSError:
                continue
            return port
    raise LocalPgError(f"нет свободного порта в {start}–{start + tries - 1} на {host}")


def _major(text: str) -> int:
    found = re.search(r"\b(\d+)(?:\.\d+)?", text)
    if not found:
        raise LocalPgError(f"не понял версию PostgreSQL: {text.strip()!r}")
    return int(found.group(1))


@dataclass(frozen=True)
class Cluster:
    bin: Path
    data: Path

    def tool(self, name: str) -> Path:
        path = self.bin / (f"{name}.exe" if WINDOWS else name)
        if not path.is_file():
            raise LocalPgError(f"нет {path}: в pg_bin нужны {', '.join(TOOLS)} PostgreSQL {PG_MIN}+")
        return path

    def check(self) -> int:
        """Программы на месте и версии не ниже PG_MIN; мажорная версия."""
        for name in TOOLS:
            self.tool(name)
        done = self._run([self.tool("pg_ctl"), "--version"], "pg_ctl --version")
        major = _major(done.stdout)
        if major < PG_MIN:
            raise LocalPgError(f"PostgreSQL {major} в {self.bin}: нужен {PG_MIN} или новее")
        return major

    @property
    def exists(self) -> bool:
        return (self.data / "PG_VERSION").is_file()

    @property
    def log(self) -> Path:
        return self.data / "log" / "postgresql.log"

    def port(self) -> int:
        """Порт из postgresql.conf кластера (его записал initdb -c port=…)."""
        conf = self.data / "postgresql.conf"
        try:
            text = conf.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            raise LocalPgError(f"{conf}: {e}") from None
        found = re.findall(r"^\s*port\s*=\s*(\d+)", text, flags=re.MULTILINE)
        if not found:
            raise LocalPgError(f"{conf}: порт не задан")
        return int(found[-1])

    def init(self, password: str, port: int) -> None:
        """Новый кластер: роль amemo с паролем, UTF8 без локали, только localhost и scram-sha-256."""
        if self.exists:
            raise LocalPgError(f"{self.data}: кластер уже есть")
        if self.data.exists() and any(self.data.iterdir()):
            raise LocalPgError(f"{self.data}: папка не пустая и не кластер PostgreSQL — выберите другую")
        self.data.parent.mkdir(parents=True, exist_ok=True)
        fd, pwfile = tempfile.mkstemp(prefix="amemo-pw-", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                out.write(password + "\n")
            self._run([self.tool("initdb"), "-D", str(self.data), "-U", ROLE, "--pwfile", pwfile,
                       "-A", "scram-sha-256", "-E", "UTF8", "--no-locale"], "initdb")
        finally:
            Path(pwfile).unlink(missing_ok=True)
        with open(self.data / "postgresql.conf", "a", encoding="utf-8", newline="\n") as conf:
            conf.write("\n# amemo setup\n" + "".join(f"{k} = {v}\n" for k, v in conf_lines(port).items()))

    def running(self) -> bool:
        if not self.exists:
            return False
        done = subprocess.run([str(self.tool("pg_ctl")), "-D", str(self.data), "status"], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
        return done.returncode == 0

    def start(self) -> bool:
        """Запустить, если не запущен; True — запустили сейчас."""
        if not self.exists:
            raise LocalPgError(f"{self.data}: кластера нет — сначала amemo setup")
        if self.running():
            return False
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self._run([self.tool("pg_ctl"), "-D", str(self.data), "-l", str(self.log), "-w", "-t",
                   str(START_TIMEOUT), "start"], "pg_ctl start", detach=True)
        return True

    def stop(self) -> bool:
        """Остановить, если запущен; True — остановили сейчас."""
        if not self.running():
            return False
        self._run([self.tool("pg_ctl"), "-D", str(self.data), "-m", "fast", "-w", "stop"], "pg_ctl stop")
        return True

    def _run(self, argv: list, what: str, *, detach: bool = False) -> subprocess.CompletedProcess:
        kw = {}
        if detach and WINDOWS:                    # сервер не должен умереть вместе с консолью вызвавшего
            kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        try:
            # stdout сервера при start уходит в журнал (-l), поэтому вывод можно ждать без зависания
            done = subprocess.run([str(a) for a in argv], capture_output=not detach, text=True, encoding="utf-8",
                                  errors="replace", stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL if detach else None,
                                  stderr=subprocess.DEVNULL if detach else None, **kw)
        except OSError as e:
            raise LocalPgError(f"{what}: {e}") from None
        if done.returncode != 0:
            tail = ((done.stderr or "") + (done.stdout or "")).strip().splitlines()[-3:] if not detach else []
            where = f"; журнал — {self.log}" if what.startswith("pg_ctl start") else ""
            raise LocalPgError(f"{what}: код {done.returncode}" + (f": {' / '.join(tail)}" if tail else "") + where)
        return done


def dsn(password: str, port: int, database: str = DATABASE) -> str:
    from urllib.parse import quote

    return f"postgresql://{ROLE}:{quote(password, safe='')}@127.0.0.1:{port}/{database}"


def ensure_database(admin_dsn: str) -> list[str]:
    """База amemo и расширения vector, btree_gist в ней и в template1 (backup verify создаёт пробную базу из него).
    Возвращает, что создано сейчас."""
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    made = []
    try:
        with psycopg.connect(admin_dsn, autocommit=True, connect_timeout=10) as conn:
            if conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DATABASE,)).fetchone() is None:
                conn.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(DATABASE),
                                                                          sql.Identifier(ROLE)))
                made.append(f"база {DATABASE}")
        for name in (DATABASE, "template1"):
            with psycopg.connect(make_conninfo(admin_dsn, dbname=name), autocommit=True, connect_timeout=10) as conn:
                for ext in EXTENSIONS:
                    if conn.execute("SELECT 1 FROM pg_extension WHERE extname = %s", (ext,)).fetchone() is None:
                        conn.execute(sql.SQL("CREATE EXTENSION {}").format(sql.Identifier(ext)))
                        made.append(f"{ext} в {name}")
    except psycopg.Error as e:
        hint = (" — в pg_bin нет pgvector: нужен PostgreSQL со встроенным расширением vector"
                if "vector" in str(e) and "control" in str(e) else "")
        raise LocalPgError(f"подготовка базы: {e}".strip() + hint) from None
    return made
