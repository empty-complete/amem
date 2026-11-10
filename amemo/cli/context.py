"""Окружение одной команды CLI: настройки, агент, соединение, хранилище, вывод.

Агент CLI (спецификация подпроекта 4, разд. 5.2): в обычном терминале — человек AMEMO_AGENT (по умолчанию person: и
имя пользователя ОС). Окружение, которое выдаёт агента, делает запись моделью: AMEMO_AS_MODEL=имя — model:имя,
CLAUDECODE=1 — model:claude-code, переменные песочницы Codex (CODEX_SANDBOX, CODEX_SANDBOX_NETWORK_DISABLED) —
model:codex. --agent задаёт агента явно; person: при узнанном окружении агента не принимается (код 2): иначе модель
писала бы от имени человека одной опцией. CODEX_HOME признаком не считается — это настройка, которую задают и в
обычном терминале. Права дальше — те же, что у службы: их проверяют операции amemo/api.py.

Соединение — db.connect (autocommit) с коротким таймаутом входа. База должна быть подготовлена: все миграции
применены (иначе код 1 с подсказкой amemo init); счётчик UUIDv7 продолжается после самых поздних id базы
(db.seed_ids) — новый процесс не выдаёт id меньше уже выданных, даже если часы ушли назад.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Mapping

from .. import settings as settings_
from .errors import ENV, USAGE, CliError

CONNECT_TIMEOUT = 5                     # с; база не ответила — код 1, а не долгое ожидание
CLAUDE_CODE = "model:claude-code"
CODEX = "model:codex"
CODEX_VARS = ("CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED")


def detected_agent(env: Mapping[str, str]) -> tuple[str, str] | None:
    """Агент, которого выдаёт окружение, и признак (для сообщения); None — обычный терминал."""
    as_model = env.get("AMEMO_AS_MODEL", "").strip()
    if as_model:
        agent = f"model:{as_model}"
        if not settings_.MODEL.fullmatch(agent):
            raise CliError(f"AMEMO_AS_MODEL {as_model!r}: нужно имя из строчных латинских букв, цифр и «_.-»",
                           exit=USAGE, code="bad_agent")
        return agent, "AMEMO_AS_MODEL"
    if env.get("CLAUDECODE", "").strip() == "1":
        return CLAUDE_CODE, "CLAUDECODE=1"
    for var in CODEX_VARS:
        if env.get(var, "").strip():
            return CODEX, var
    return None


def _default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (uuid.UUID, Path)):
        return str(value)
    raise TypeError(f"{type(value).__name__} не переводится в JSON")


def dumps(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=_default)


class Context:
    """Всё, что нужно команде; тяжёлое (настройки, соединение, provider) — по первому обращению."""

    def __init__(self, args, env: Mapping[str, str], *, out=None, err=None, runner=None):
        self.args, self.env = args, env
        self.out, self.err = out or sys.stdout, err or sys.stderr
        self.json = bool(getattr(args, "json", False))
        self.runner = runner
        self._settings = None
        self._agent = None
        self._conns = []

    # --- настройки и агент ---

    @property
    def settings(self) -> settings_.Settings:
        if self._settings is None:
            self._settings = settings_.load(self.env)
        return self._settings

    @property
    def agent(self) -> str:
        if self._agent is None:
            explicit = getattr(self.args, "agent", None)
            detected = detected_agent(self.env)
            if explicit is not None:
                explicit = explicit.strip()
                if not settings_.AGENT.fullmatch(explicit):
                    raise CliError(f"--agent {explicit!r}: нужен person:<имя> или model:<имя> (строчные латинские "
                                   f"буквы, цифры, «_.-»)", exit=USAGE, code="bad_agent")
                if detected is not None and explicit.startswith("person:"):
                    raise CliError(f"--agent {explicit}: в окружении агента ({detected[1]}) запись от имени человека "
                                   f"не принимается — команда идёт от {detected[0]}", exit=USAGE, code="bad_agent",
                                   hint="человек пишет из своего терминала, без агента")
                self._agent = explicit
            elif detected is not None:
                self._agent = detected[0]
            else:
                self._agent = self.settings.agent
        return self._agent

    @property
    def is_person(self) -> bool:
        return self.agent.startswith("person:")

    # --- база ---

    def dsn(self) -> str:
        if not self.settings.dsn:
            raise CliError("база не задана", exit=ENV, code="no_dsn")
        return self.settings.dsn

    def connect(self, *, ready: bool = True):
        """Соединение с базой (закрывается в close). ready — база подготовлена (миграции); продолжить счётчик id."""
        from .. import db

        conn = db.connect(self.dsn(), connect_timeout=CONNECT_TIMEOUT)
        self._conns.append(conn)
        if ready:
            pending = pending_migrations(conn)
            if pending is None:
                raise CliError("база не подготовлена: в ней нет схемы amemo", exit=ENV, code="not_ready")
            if pending:
                raise CliError(f"база не подготовлена: не применены миграции {', '.join(pending)}", exit=ENV,
                               code="not_ready")
            db.seed_ids(conn)
        return conn

    def store(self):
        from ..ocfl_store import ObjectStore

        return ObjectStore(self.settings.data)

    def provider(self):
        """provider смыслового канала по AMEMO_BACKEND, как у службы; не выбирается — None (канал пропускается)."""
        from .. import embed

        try:
            return embed.get_provider(None)
        except embed.EmbeddingError:
            return None

    def close(self) -> None:
        for conn in self._conns:
            conn.close()
        self._conns.clear()

    # --- вывод ---

    def emit(self, data, text: Callable[[object], str] | str | None = None) -> None:
        """--json — data как есть (то же, что отдаёт операция api и HTTP); иначе текст для человека."""
        if self.json:
            print(dumps(data), file=self.out)
            return
        rendered = text(data) if callable(text) else text if text is not None else plain(data)
        if rendered:
            print(rendered, file=self.out)

    def note(self, line: str) -> None:
        """Строка для человека в stderr (не мешает --json и конвейерам)."""
        print(line, file=self.err)


def pending_migrations(conn) -> list[str] | None:
    """Не применённые миграции из кода; None — в базе нет учёта миграций (схема amemo не создана)."""
    import psycopg

    from .. import db

    try:
        with conn.transaction():
            applied = {row[0] for row in conn.execute("SELECT name FROM schema_migrations")}
    except psycopg.errors.UndefinedTable:
        return None
    return [p.name for p in sorted(db.SQL_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql")) if p.name not in applied]


def plain(data, indent: int = 0) -> str:
    """Простой текст из JSON: ключ: значение, вложенное — с отступом; для сводок без своего вида."""
    pad = "  " * indent
    lines = []
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)) and value:
                lines.append(f"{pad}{key}:")
                lines.append(plain(value, indent + 1))
            else:
                lines.append(f"{pad}{key}: {_scalar(value)}")
    elif isinstance(data, list):
        for value in data:
            if isinstance(value, (dict, list)) and value:
                lines.append(f"{pad}-")
                lines.append(plain(value, indent + 1))
            else:
                lines.append(f"{pad}- {_scalar(value)}")
    else:
        lines.append(f"{pad}{_scalar(data)}")
    return "\n".join(lines)


def _scalar(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, (dict, list)):
        return "—"
    return str(value)


def environ(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env
