"""Служба amem: HTTP v1 для веб-интерфейса — тонкий слой Starlette над библиотекой (спецификация подпроекта 4, разд. 3).

create_app(settings) — приложение ASGI; запуск — uvicorn (amem serve)."""
from .app import create_app

__all__ = ["create_app"]
