"""Статика веб-интерфейса amemo. Служба (подпроект 4) монтирует static_dir() по /ui."""
from importlib import resources
from pathlib import Path

__version__ = "0.1.0.dev0"


def static_dir() -> Path:
    """Папка со сборкой: index.html и assets/ с хэшами в именах."""
    return Path(str(resources.files("amemo_web") / "dist"))
