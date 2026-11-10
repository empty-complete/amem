"""Подготовка релиза на PyPI (.github/workflows/release.yml).

    python tools/release.py versions [--tag vX.Y.Z]   версии amemo и amemo-web совпадают, amemo[web] закреплён ровно
                                                      на ней, метка релиза (если дана) её называет; печатает версию
    python tools/release.py readme REF                README.md для страницы PyPI: относительные ссылки и картинки
                                                      ведут на GitHub в состоянии REF (метка или коммит); строка
                                                      копирайта — без «© …»: имя автора остаётся только на GitHub
"""
from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

from packaging.version import Version

ROOT = Path(__file__).resolve().parent.parent
REPO = "https://github.com/empty-complete/amemo"
RAW = "https://raw.githubusercontent.com/empty-complete/amemo"

_VERSION = re.compile(r'^__version__ = "([^"]+)"$', re.M)
_LOCAL = r"(?!https?:|#|mailto:|data:)"                       # ссылка внутри репозитория
_ATTR = re.compile(rf'\b(src|srcset|href)="{_LOCAL}([^"]+)"')
_MD = re.compile(rf"(!?)\[([^\]]*)\]\({_LOCAL}([^)\s]+)\)")
_COPYRIGHT = re.compile(r"\s*©[^\n]*")


def _version_of(path: Path) -> str:
    found = _VERSION.search(path.read_text(encoding="utf-8"))
    if not found:
        sys.exit(f"{path.relative_to(ROOT)}: нет строки __version__ = \"…\"")
    return found.group(1)


def versions(tag: str | None) -> str:
    core = _version_of(ROOT / "amemo" / "__init__.py")
    web = _version_of(ROOT / "web" / "python" / "amemo_web" / "__init__.py")
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extra = pyproject["project"]["optional-dependencies"]["web"]
    problems = []
    if str(Version(core)) != core:
        problems.append(f"версия {core} не в канонической форме PEP 440 ({Version(core)})")
    if web != core:
        problems.append(f"amemo {core}, amemo-web {web}: версии должны совпадать")
    if extra != [f"amemo-web=={core}"]:
        problems.append(f"amemo[web] = {extra}, нужно [\"amemo-web=={core}\"]")
    if tag is not None and tag != f"v{core}":
        problems.append(f"метка {tag}, а версия {core}: нужна метка v{core}")
    if problems:
        sys.exit("\n".join(problems))
    return core


def _absolute(target: str, ref: str, *, image: bool) -> str:
    target = target.removeprefix("./")
    return f"{RAW}/{ref}/{target}" if image else f"{REPO}/blob/{ref}/{target}"


def pypi_readme(text: str, ref: str) -> str:
    """Относительные ссылки README → адреса GitHub, «© …» до конца строки убирается; блоки кода не трогаются."""
    out, fenced = [], False
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced:
            line = _ATTR.sub(lambda m: f'{m[1]}="{_absolute(m[2], ref, image=m[1] != "href")}"', line)
            line = _MD.sub(lambda m: f"{m[1]}[{m[2]}]({_absolute(m[3], ref, image=bool(m[1]))})", line)
            line = _COPYRIGHT.sub("", line)
        out.append(line)
    return "".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools/release.py")
    sub = ap.add_subparsers(dest="command", required=True)
    v = sub.add_parser("versions")
    v.add_argument("--tag")
    r = sub.add_parser("readme")
    r.add_argument("ref")
    args = ap.parse_args(argv)
    if args.command == "versions":
        print(versions(args.tag))
    else:
        path = ROOT / "README.md"
        path.write_text(pypi_readme(path.read_text(encoding="utf-8"), args.ref), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
