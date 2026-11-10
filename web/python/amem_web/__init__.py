"""Статика веб-интерфейса amem. Служба (подпроект 4) монтирует static_dir() по /ui."""
from importlib import resources
from pathlib import Path

__version__ = "0.1.0a1"


def static_dir() -> Path:
    """Папка со сборкой: index.html и assets/ с хэшами в именах."""
    return Path(str(resources.files("amem_web") / "dist"))
