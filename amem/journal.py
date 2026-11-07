"""Журнал запросов (спецификация подпроекта 4, разд. 6.5): строка JSON Lines на каждый явный поиск.

Строка — время (UTC), рецепт, текст запроса после private.strip, base_id, агент, число находок, длительность в мс
и retrieval_id выдачи. Самих находок в журнале нет. Пишут только пути явного поиска службы (/search, /similar);
поиск хука (подсказка по ходу работы) — не явный и в журнал не пишет. Путь — AMEM_QUERY_LOG (по умолчанию
AMEM_STATE/queries.jsonl), off — журнал выключен (путь None). Файл не поворачивается: его объём ограничен числом
явных поисков. Создаётся с правами 0600 — в запросах бывает то, что не для чужих глаз.

Журнал — сигнал пользы, а не часть ответа: ошибка файла (нет прав, диск полон) уходит предупреждением в журнал
службы и поиск не роняет.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("amem.service")
_lock = threading.Lock()            # строки параллельных поисков (пул потоков службы) не перемешиваются


def record(path: Path | None, *, recipe: str, query: str, agent: str, base_id: str | None, count: int,
           duration_ms: float, retrieval_id: str | None) -> bool:
    """Дописать строку о поиске; True — записано, False — журнал выключен или файл не записался."""
    if path is None:
        return False
    line = json.dumps({"at": datetime.now(timezone.utc).isoformat(), "recipe": recipe, "query": query,
                       "base_id": base_id, "agent": agent, "count": count, "duration_ms": round(duration_ms, 1),
                       "retrieval_id": retrieval_id}, ensure_ascii=False) + "\n"
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(fd, line.encode("utf-8"))
            finally:
                os.close(fd)
    except OSError as e:
        log.warning("журнал запросов %s не записан: %s", path, e)
        return False
    return True
