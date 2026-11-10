"""Запуск службы (спецификация подпроекта 4, разд. 2 и 10): uvicorn на адресе из настроек, по умолчанию
127.0.0.1:8767.

serve(settings, no_auth=…) — то, что зовёт `amemo serve` (CLI, часть 4b) и `python -m amemo.service` (main). Перед
запуском — проверка открытости: адрес не loopback (0.0.0.0, адрес сети, имя) без AMEMO_TOKENS — отказ (Exposed,
CLI отвечает кодом 2): локальная служба доверяет любому запросу без cookie как модели с правом записи, и в сети это
запись для всех. Явный --no-auth снимает отказ (сеть закрыта, например внутри compose) и печатает громкое
предупреждение. Host проверяется всегда: при --host 0.0.0.0 имя службы в сети задаёт AMEMO_ALLOWED_HOSTS.
"""
from __future__ import annotations

import argparse
import ipaddress
import logging
import sys
from collections.abc import Callable, Mapping, Sequence

from .. import settings as settings_
from ..settings import Settings, SettingsError

LOOPBACK_NAMES = frozenset({"localhost"})
log = logging.getLogger("amemo.service")


class Exposed(SettingsError):
    """Служба открылась бы в сеть без входа: адрес не loopback, нет AMEMO_TOKENS и нет --no-auth."""


def loopback(host: str) -> bool:
    """Адрес только этой машины: 127.0.0.0/8, ::1 или localhost. Прочие имена и 0.0.0.0 — нет."""
    if host.strip().lower() in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host.strip().strip("[]")).is_loopback
    except ValueError:
        return False


def exposure(settings: Settings, *, no_auth: bool = False) -> str | None:
    """Проверка открытости перед запуском: текст предупреждения или None; открыта без входа и без --no-auth —
    Exposed."""
    if settings.tokens is not None:
        if no_auth:
            return "--no-auth не действует: задан AMEMO_TOKENS — вход по токенам"
        return None
    if loopback(settings.host):
        if no_auth:
            return (f"--no-auth: служба на {settings.host} и так без входа — она доступна только с этой машины")
        return None
    if not no_auth:
        raise Exposed(f"служба на {settings.host}:{settings.port} была бы доступна из сети без входа: любой запрос "
                      f"без cookie пишет как модель. Задайте AMEMO_TOKENS (файл токенов: amemo token create) или, "
                      f"если сеть закрыта (например, внутри compose), запустите с --no-auth")
    return (f"ВНИМАНИЕ: служба слушает {settings.host}:{settings.port} БЕЗ ВХОДА (--no-auth). Любой, кто достучится "
            f"до порта, читает базу и пишет в неё как модель {settings.model_agent}. Держите порт закрытым "
            f"(compose: наружу только 127.0.0.1) или задайте AMEMO_TOKENS")


def serve(settings: Settings, *, no_auth: bool = False, provider=None, log_level: str = "info",
          runner: Callable | None = None, warn: Callable[[str], None] | None = None) -> None:
    """Проверить открытость и запустить службу до остановки (Ctrl+C). runner — замена uvicorn.run (тесты),
    warn — куда писать предупреждение (по умолчанию stderr и журнал службы)."""
    warning = exposure(settings, no_auth=no_auth)
    from .app import create_app            # после проверки: отказ не открывает пул и не трогает базу

    app = create_app(settings, provider=provider)
    if warning:
        (warn or _warn)(warning)
    if runner is None:
        import uvicorn
        runner = uvicorn.run
    runner(app, host=settings.host, port=settings.port, log_level=log_level, server_header=False)


def _warn(text: str) -> None:
    line = "!" * 72
    print(f"{line}\n{text}\n{line}", file=sys.stderr, flush=True)
    log.warning("%s", text)


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m amemo.service", description="Служба amemo: HTTP v1 и веб-интерфейс")
    ap.add_argument("--host", help=f"адрес привязки (AMEMO_HOST, по умолчанию {settings_.DEFAULT_HOST})")
    ap.add_argument("--port", type=int, help=f"порт (AMEMO_PORT, по умолчанию {settings_.DEFAULT_PORT})")
    ap.add_argument("--no-auth", action="store_true",
                    help="разрешить адрес не loopback без AMEMO_TOKENS (закрытая сеть, compose)")
    return ap


def main(argv: Sequence[str] | None = None, *, env: Mapping[str, str] | None = None, **kw) -> int:
    """Вход `python -m amemo.service`: код 0 после остановки, 2 — неверная настройка или открытость без входа."""
    args = parser().parse_args(argv)
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        settings = settings_.load(env, host=args.host, port=args.port)
        serve(settings, no_auth=args.no_auth, **kw)
    except SettingsError as e:
        print(f"amemo: {e}", file=sys.stderr)
        return 2
    return 0
