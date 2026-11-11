"""Подготовка релиза на PyPI (.github/workflows/release.yml).

    python tools/release.py versions [--tag vX.Y.Z]   версии amemo и amemo-web совпадают, amemo[web] закреплён ровно
                                                      на ней, метка релиза (если дана) её называет; печатает версию
    python tools/release.py readme REF                README.md для страницы PyPI: относительные ссылки и картинки
                                                      ведут на GitHub в состоянии REF (метка или коммит); строка
                                                      копирайта — без «© …»: имя автора остаётся только на GitHub
    python tools/release.py semver [VERSION]          версия amemo (PEP 440) в semver для приложения Tauri:
                                                      0.1.0a1 → 0.1.0-alpha.1, 1.2.0rc2 → 1.2.0-rc.2
    python tools/release.py latest --setup EXE --url URL [--version V] [--notes TEXT] [--out FILE]
                                                      latest.json для updater приложения (спецификация приложения
                                                      для Windows, п. 3): версия semver, подпись EXE.sig, адрес
                                                      установщика; печатает в stdout или пишет в FILE
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from datetime import datetime, timezone
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


_PRE = {"a": "alpha", "b": "beta", "rc": "rc"}


def semver(version: str) -> str:
    """Semver из версии PEP 440: Tauri и его updater принимают только semver. Пост- и dev-версии и локальная часть
    в выпуски amemo не попадают — ошибка, а не молчаливая потеря."""
    v = Version(version)
    if v.epoch or v.post is not None or v.dev is not None or v.local is not None or len(v.release) > 3:
        sys.exit(f"версия {version}: для приложения нужна X.Y.Z с необязательной a/b/rc")
    core = ".".join(str(n) for n in (list(v.release) + [0, 0])[:3])
    return f"{core}-{_PRE[v.pre[0]]}.{v.pre[1]}" if v.pre else core


UPDATER_TARGET = "windows-x86_64"         # платформа updater Tauri для установщика NSIS x64


def latest(setup: Path, url: str, version: str, notes: str = "", now: datetime | None = None) -> dict:
    """Статичный манифест updater Tauri (https://v2.tauri.app/plugin/updater/, «Static JSON File»): version (semver),
    notes, pub_date (RFC 3339), platforms.<цель>.{signature, url}; подпись — содержимое файла EXE.sig, который пишет
    `tauri build` с createUpdaterArtifacts."""
    signature = Path(f"{setup}.sig")
    if not signature.is_file():
        sys.exit(f"нет подписи {signature}: установщик собран без ключа подписи обновлений")
    if not url.startswith(("https://", "http://")):
        sys.exit(f"--url {url}: нужен адрес http(s) установщика")
    stamp = (now or datetime.now(timezone.utc)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {"version": semver(version), "notes": notes, "pub_date": stamp,
            "platforms": {UPDATER_TARGET: {"signature": signature.read_text(encoding="utf-8").strip(), "url": url}}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools/release.py")
    sub = ap.add_subparsers(dest="command", required=True)
    v = sub.add_parser("versions")
    v.add_argument("--tag")
    r = sub.add_parser("readme")
    r.add_argument("ref")
    s = sub.add_parser("semver")
    s.add_argument("version", nargs="?")
    j = sub.add_parser("latest")
    j.add_argument("--setup", type=Path, required=True)
    j.add_argument("--url", required=True)
    j.add_argument("--version")
    j.add_argument("--notes", default="")
    j.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    if args.command == "versions":
        print(versions(args.tag))
    elif args.command == "semver":
        print(semver(args.version or _version_of(ROOT / "amemo" / "__init__.py")))
    elif args.command == "latest":
        data = latest(args.setup, args.url, args.version or _version_of(ROOT / "amemo" / "__init__.py"), args.notes)
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        if args.out:
            args.out.write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
    else:
        path = ROOT / "README.md"
        path.write_text(pypi_readme(path.read_text(encoding="utf-8"), args.ref), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
