"""Служба amemo: HTTP v1 для веб-интерфейса — тонкий слой Starlette над библиотекой (спецификация подпроекта 4, разд. 3).

create_app(settings) — приложение ASGI; serve(settings, no_auth=…) — запуск uvicorn с проверкой открытости
(amemo serve, python -m amemo.service)."""
from .app import create_app
from .server import serve

__all__ = ["create_app", "serve"]
