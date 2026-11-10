"""Коды выхода CLI (спецификация подпроекта 4, разд. 5.1) и подсказки «что сделать».

Таблица одна на службу и CLI: исключение сначала переводится в Problem службы (amemo/service/problems.to_problem —
те же ступени от частного к общему, что у HTTP), а CLI отображает статус и code ответа в код выхода. Так новая
ошибка библиотеки, получившая статус у службы, сразу получает и код CLI, и они не расходятся. Сверх таблицы службы —
только то, чего у HTTP нет: настройки, файлы на диске, бэкап, разбор аргументов.

  0 — успех; 1 — окружение (база недоступна или не подготовлена, нет хранилища, нет клиента PostgreSQL);
  2 — неверный вызов (аргументы, формат файла, право агента); 3 — неоднозначность (выведены кандидаты);
  4 — не найдено; 5 — отказ проверки (выведен отчёт); 6 — конфликт (пункт решён, папка занята, коллизия подборки).
"""
from __future__ import annotations

OK, ENV, USAGE, AMBIGUOUS, NOT_FOUND, REJECTED, CONFLICT = 0, 1, 2, 3, 4, 5, 6

# code ответа службы → код выхода; что не здесь — по статусу (BY_STATUS)
BY_CODE = {
    "ambiguous": AMBIGUOUS,
    "check_rejected": REJECTED,
    "review_closed": CONFLICT, "folder_exists": CONFLICT, "folder_not_empty": CONFLICT,
    "bundle_key_collision": CONFLICT, "bundle_pack_conflict": CONFLICT,
    "bundle_pack_missing": ENV,           # в базе нет пакета, на который опирается подборка: окружение получателя
    "db_unavailable": ENV, "store_unavailable": ENV, "semantic_unavailable": ENV, "timeout": ENV,
    "quota_exceeded": ENV, "internal": ENV,
}
BY_STATUS = {400: USAGE, 401: USAGE, 403: USAGE, 404: NOT_FOUND, 408: ENV, 409: CONFLICT, 413: USAGE, 415: USAGE,
             416: USAGE, 422: USAGE, 503: ENV, 507: ENV}

HINTS = {
    "db_unavailable": "задайте AMEMO_DSN или выполните amemo init",
    "db_auth": "проверьте пользователя и пароль в AMEMO_DSN",
    "no_dsn": "задайте AMEMO_DSN или выполните amemo init --dsn postgresql://…",
    "not_ready": "выполните amemo init",
    "store_unavailable": "проверьте AMEMO_DATA и что том с данными подключён (amemo doctor)",
    "not_found": "найдите запись: amemo search ТЕКСТ",
    "folder_not_found": "дерево папок: amemo folders tree",
    "ambiguous": "уточните текст или передайте ссылку atm:/ent: из списка",
    "check_rejected": "исправьте замечания отчёта и отправьте пакет снова",
    "forbidden": "это действие — для человека: выполните его в своём терминале, без агента",
    "review_forbidden": "свободные пункты для вашего агента: amemo review claim",
    "review_closed": "открытые пункты: amemo review list --state queued",
    "folder_exists": "дерево папок: amemo folders tree",
    "folder_not_empty": "сначала перенесите записи и вложенные папки",
    "task_closed": "незакрытые задачи: amemo tasks list --state open",
    "task_claimed": "задачу держит агент; отменить её может поставивший или человек: amemo tasks cancel ID",
    "bundle_pack_missing": "загрузите в базу недостающие пакеты и повторите",
    "bundle_key_collision": "ключи записей подборки уже заняты в этой базе: смотрите collisions",
    "bundle_pack_conflict": "свои виды подборки расходятся со своими видами базы: смотрите collisions",
    "semantic_unavailable": "смысловой поиск: amemo embed status (включить — amemo embed enable)",
    "backup": "клиент PostgreSQL 18 — в AMEMO_PG_BIN или PATH; восстановление — только в пустую базу",
    "tokens": "задайте AMEMO_TOKENS — путь к файлу токенов, например ~/.config/amemo/amemo-tokens.toml",
}


def exit_code(status: int, code: str) -> int:
    """Код выхода для ответа-ошибки службы (статус и code)."""
    if code in BY_CODE:
        return BY_CODE[code]
    if code.startswith("bundle_"):
        return USAGE                      # подборка не та: формат файла
    return BY_STATUS.get(status, ENV)


class CliError(Exception):
    """Ошибка CLI, которой нет у службы: настройки, окружение, файл. code — для --json и подсказки."""

    def __init__(self, message: str, *, exit: int, code: str, status: int | None = None, hint: str | None = None,
                 **extra):
        super().__init__(message)
        self.exit, self.code, self.status, self.extra = exit, code, status, extra
        self.hint = hint if hint is not None else HINTS.get(code)
