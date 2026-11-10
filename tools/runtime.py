"""Комплект amemo для Windows и архив модели смыслового поиска (спецификация приложения для Windows, D2).

Комплект `amemo-runtime-<версия>-windows-x64.zip` — всё, что нужно amemo без установки чего-либо ещё и без прав
администратора:
- pgsql/ — PostgreSQL 18 из архива EDB «zip binaries» без pgAdmin, StackBuilder, документации, заголовков и библиотек
  сборки; с pgvector, собранным против него (job runtime в .github/workflows/runtime.yml, nmake);
- python/ — переносимый CPython 3.12 (python-build-standalone, install_only_stripped) с колёсами amemo[web,embed] и
  зависимостями; без тестов стандартной библиотеки, tkinter, idle и запускателей Scripts/*.exe (в них записан
  абсолютный путь к python.exe машины сборки);
- библиотеки Visual C++ рядом с postgres.exe и python.exe (--vcredist): Redistributable у человека может не быть;
- amemo.cmd — запуск amemo этим Python (`python -I -m amemo.cli`);
- runtime.json — версии частей; THIRD-PARTY-NOTICES.txt — лицензии PostgreSQL, pgvector, Python и пакетов.

Архив модели `amemo-model-paraphrase-multilingual-MiniLM-L12-v2.zip` — файлы модели в раскладке кэша fastembed
(то, что `amemo setup --embed --embed-models DIR` копирует в models_dir), с лицензией Apache-2.0 и NOTICE.

Шаги (каждый — подкоманда; запускаются по порядку в Windows, кроме сборки pgvector, которой нужен MSVC):
  python tools/runtime.py postgres WORK          PostgreSQL в WORK/pgsql
  python tools/runtime.py pgvector WORK          исходники pgvector в WORK/pgvector (собирает nmake, PGROOT=WORK/pgsql)
  python tools/runtime.py python WORK            Python в WORK/python
  python tools/runtime.py assemble WORK --wheels DIST --out OUT [--vcredist DIR]
  python tools/runtime.py model WORK --out OUT   модель — Python комплекта качает её с Hugging Face
Загрузки сверяются с SHA-256 ниже; новая версия части — новый адрес и сумма здесь.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

POSTGRES = {"version": "18.6-5",
            "url": "https://get.enterprisedb.com/postgresql/postgresql-18.6-5-windows-x64-binaries.zip",
            "sha256": "e2246ba91d22345bc3d017586c09ede52d9df180b1eeb480f050445f1cad84e2"}
PGVECTOR = {"version": "0.8.1",
            "url": "https://github.com/pgvector/pgvector/archive/refs/tags/v0.8.1.zip",
            "sha256": "61182a6afd6fb94c0e7740c037a7d3c36a8cab1cc581ae5bd9b7b2cfd789bdfc"}
PYTHON = {"version": "3.12.16+20261026",
          "url": "https://github.com/astral-sh/python-build-standalone/releases/download/20261026/"
                 "cpython-3.12.16%2B20261026-x86_64-pc-windows-msvc-install_only_stripped.tar.gz",
          "sha256": "1f2ab53880fc67ea323398c6388e05af28addc99a8e389209f08a51fdff4b149"}
APACHE = {"url": "https://www.apache.org/licenses/LICENSE-2.0.txt",
          "sha256": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"}
MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_ZIP = "amemo-model-paraphrase-multilingual-MiniLM-L12-v2.zip"
MAX_RUNTIME = 250 << 20                 # байт архива комплекта (спецификация, D2)
HOMEPAGE = "https://github.com/empty-complete/amemo"

# из pgsql/ — лишнее для amemo: клиенты-приложения, документация, всё для сборки расширений
PG_DROP_DIRS = ("pgAdmin 4", "StackBuilder", "doc", "include", "symbols", "installer", "lib/pgxs", "lib/pkgconfig")
PG_DROP_FILES = re.compile(r"^(bin/(wx\w+\.dll|stackbuilder\.exe|testplug\.dll|test_cloexec\.exe|.*\.lib)"
                           r"|lib/.*\.(lib|a)|(pgAdmin|StackBuilder)_.*\.txt)$", re.IGNORECASE)
PG_NOTICES = ("server_license.txt", "commandlinetools_3rd_party_licenses.txt")
# из python/ — то, чего amemo не импортирует
PY_DROP_DIRS = ("Lib/test", "Lib/idlelib", "Lib/tkinter", "Lib/turtledemo", "tcl", "Scripts")
PY_DROP_FILES = re.compile(r"^DLLs/(_tkinter\.pyd|tcl\d+t?\.dll|tk\d+t?\.dll)$", re.IGNORECASE)


def log(message: str) -> None:
    print(message, flush=True)


def fetch(source: dict, target: Path) -> Path:
    """Скачать source["url"] в target и сверить SHA-256; уже скачанный верный файл не качается заново."""
    if target.is_file() and sha256(target) == source["sha256"]:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    log(f"скачиваю {source['url']}")
    request = urllib.request.Request(source["url"], headers={"User-Agent": "amemo-runtime-build"})
    tmp = target.with_suffix(target.suffix + ".part")
    for attempt in range(1, 6):
        try:
            with urllib.request.urlopen(request, timeout=120) as response, open(tmp, "wb") as out:
                shutil.copyfileobj(response, out, 1 << 20)
            break
        except OSError as e:
            if attempt == 5:
                raise
            log(f"  попытка {attempt}: {e}")
    got = sha256(tmp)
    if got != source["sha256"]:
        tmp.unlink()
        raise SystemExit(f"{source['url']}: SHA-256 {got}, ожидалась {source['sha256']}")
    tmp.replace(target)
    return target


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def mb(size: int) -> str:
    return f"{size / (1 << 20):.1f} МиБ"


# --- части ---

def cmd_postgres(work: Path) -> None:
    archive = fetch(POSTGRES, work / "downloads" / "postgresql.zip")
    shutil.rmtree(work / "pgsql", ignore_errors=True)
    with zipfile.ZipFile(archive) as z:          # pgAdmin (~800 МБ) и документацию не распаковываем вовсе
        z.extractall(work, [n for n in z.namelist() if not n.startswith(("pgsql/pgAdmin 4/", "pgsql/doc/"))])
    log(f"PostgreSQL {POSTGRES['version']}: {work / 'pgsql'} ({mb(tree_size(work / 'pgsql'))})")


def cmd_pgvector(work: Path) -> None:
    archive = fetch(PGVECTOR, work / "downloads" / "pgvector.zip")
    shutil.rmtree(work / "pgvector", ignore_errors=True)
    with zipfile.ZipFile(archive) as z:
        z.extractall(work / "pgvector-src")
    (work / "pgvector-src" / f"pgvector-{PGVECTOR['version']}").rename(work / "pgvector")
    shutil.rmtree(work / "pgvector-src")
    log(f"pgvector {PGVECTOR['version']}: {work / 'pgvector'}")


def cmd_python(work: Path) -> None:
    archive = fetch(PYTHON, work / "downloads" / "python.tar.gz")
    shutil.rmtree(work / "python", ignore_errors=True)
    with tarfile.open(archive) as t:
        t.extractall(work, filter="data")          # в архиве — папка python/
    log(f"Python {PYTHON['version']}: {work / 'python'}")


def _strip(root: Path, dirs, files: re.Pattern) -> int:
    before = tree_size(root)
    for name in dirs:
        shutil.rmtree(root / name, ignore_errors=True)
    for path in list(root.rglob("*")):
        if path.is_file() and files.match(path.relative_to(root).as_posix()):
            path.unlink()
    return before - tree_size(root)


def _wheel_version(wheels: Path) -> str:
    found = sorted(wheels.glob("amemo-*-py3-none-any.whl"))
    if len(found) != 1:
        raise SystemExit(f"{wheels}: нужно ровно одно колесо amemo, найдено {[p.name for p in found]}")
    return found[0].name.split("-")[1]


def _packages(python: Path) -> list[dict]:
    script = ("import json, importlib.metadata as m\n"
              "print(json.dumps(sorted(({'name': d.metadata['Name'], 'version': d.version,\n"
              "  'license': d.metadata.get('License-Expression') or d.metadata.get('License') or ''}\n"
              "  for d in m.distributions()), key=lambda x: x['name'].lower())))")
    out = subprocess.run([str(python), "-I", "-c", script], check=True, capture_output=True, text=True,
                         encoding="utf-8").stdout
    return json.loads(out)


def _notices(work: Path, packages: list[dict], runtime_dlls: list[str]) -> str:
    parts = ["Third-party software in the amemo runtime for Windows",
             f"amemo itself: AGPL-3.0-only, source at {HOMEPAGE}", ""]
    for name in PG_NOTICES:
        parts += [f"===== PostgreSQL {POSTGRES['version']} (EDB binaries): {name} =====",
                  (work / "pgsql" / name).read_text(encoding="utf-8", errors="replace"), ""]
    parts += [f"===== pgvector {PGVECTOR['version']} (https://github.com/pgvector/pgvector): LICENSE =====",
              (work / "pgvector" / "LICENSE").read_text(encoding="utf-8"), ""]
    parts += [f"===== Python {PYTHON['version']} (python-build-standalone): LICENSE.txt =====",
              (work / "python" / "LICENSE.txt").read_text(encoding="utf-8", errors="replace"), ""]
    if runtime_dlls:
        parts += ["===== Microsoft Visual C++ runtime =====",
                  f"{', '.join(runtime_dlls)} in pgsql/bin and python/: redistributable files of Microsoft Visual "
                  f"Studio, deployed next to the programs as the Visual Studio license permits.", ""]
    parts += ["===== Python packages (name, version, license as declared by the package) ====="]
    parts += [f"{p['name']} {p['version']}: {(p['license'] or 'see package metadata').splitlines()[0][:200]}"
              for p in packages]
    return "\n".join(parts) + "\n"


LAUNCHER = ("@echo off\r\n"
            "rem amemo from the runtime: its own Python, no PYTHON* variables, no user site-packages\r\n"
            "\"%~dp0python\\python.exe\" -I -m amemo.cli %*\r\n"
            "exit /b %ERRORLEVEL%\r\n")


def _vcredist(folder: Path | None, targets: list[Path]) -> list[str]:
    """Библиотеки Visual C++ (msvcp140, vcruntime140 и др.) рядом с postgres.exe и python.exe: zip EDB и onnxruntime
    без них не запускаются, а у человека Visual C++ Redistributable может не быть. Копия «рядом с программой» —
    разрешённый Microsoft способ (папка VC/Redist/MSVC/<версия>/x64/Microsoft.VC*.CRT)."""
    if folder is None:
        return []
    dlls = sorted(folder.glob("*.dll"))
    if not dlls:
        raise SystemExit(f"{folder}: нет библиотек Visual C++")
    for target in targets:
        for dll in dlls:
            if not (target / dll.name).exists():
                shutil.copy2(dll, target / dll.name)
    return [d.name for d in dlls]


def cmd_assemble(work: Path, wheels: Path, out: Path, vcredist: Path | None = None) -> None:
    pgsql, python = work / "pgsql", work / "python"
    if not (pgsql / "lib" / "vector.dll").is_file():
        raise SystemExit(f"{pgsql}: нет lib/vector.dll — сначала соберите pgvector (nmake /F Makefile.win install)")
    version = _wheel_version(wheels)
    exe = python / "python.exe"
    log(f"amemo[web,embed]=={version} в {python}")
    subprocess.run([str(exe), "-I", "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                    "--no-warn-script-location", "--find-links", str(wheels), f"amemo[web,embed]=={version}"],
                   check=True)
    packages = _packages(exe)
    runtime_dlls = _vcredist(vcredist, [pgsql / "bin", python])
    notices = _notices(work, packages, runtime_dlls)
    log(f"PostgreSQL: убрано {mb(_strip(pgsql, PG_DROP_DIRS, PG_DROP_FILES))}; Python: убрано "
        f"{mb(_strip(python, PY_DROP_DIRS, PY_DROP_FILES))}")

    stage = work / "runtime"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir()
    shutil.move(str(pgsql), stage / "pgsql")
    shutil.move(str(python), stage / "python")
    (stage / "amemo.cmd").write_bytes(LAUNCHER.encode("ascii"))
    manifest = {"amemo": version, "postgres": POSTGRES["version"], "pgvector": PGVECTOR["version"],
                "python": PYTHON["version"], "platform": "windows-x64",
                "built": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "packages": {p["name"]: p["version"] for p in packages}}
    (stage / "runtime.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (stage / "THIRD-PARTY-NOTICES.txt").write_text(notices, encoding="utf-8")
    for name in PG_NOTICES:                       # тексты уже в THIRD-PARTY-NOTICES.txt
        (stage / "pgsql" / name).unlink(missing_ok=True)

    target = out / f"amemo-runtime-{version}-windows-x64.zip"
    size = _zip(stage, target)
    log(f"комплект: {target} — {mb(size)} (распакованный {mb(tree_size(stage))})")
    if size > MAX_RUNTIME:
        raise SystemExit(f"комплект {mb(size)} больше предела {mb(MAX_RUNTIME)}")


def cmd_model(work: Path, out: Path) -> None:
    """Модель качает Python комплекта (его fastembed и onnxruntime) — так раскладка кэша та же, что у человека."""
    exe = work / "runtime" / "python" / "python.exe"
    if not exe.is_file():
        raise SystemExit(f"{exe}: нет Python комплекта — сначала assemble")
    folder = work / "model"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir()
    script = ("import json, sys\n"
              "from amemo.embed import FastembedProvider\n"
              "from fastembed import TextEmbedding\n"
              "p = FastembedProvider(cache_dir=sys.argv[1], allow_download=True)\n"
              "vector = p.embed(['проба модели'])[0]\n"
              "info = next(m for m in TextEmbedding.list_supported_models() if m['model'] == p.name)\n"
              "print(json.dumps({'dims': len(vector), 'sources': info.get('sources'),\n"
              "                  'license': info.get('license')}, default=str))")
    found = json.loads(subprocess.run([str(exe), "-I", "-c", script, str(folder)], check=True, capture_output=True,
                                      text=True, encoding="utf-8").stdout.strip().splitlines()[-1])
    for lock in [p for p in folder.rglob(".locks") if p.is_dir()]:
        shutil.rmtree(lock)
    license_text = fetch(APACHE, work / "downloads" / "LICENSE-2.0.txt").read_text(encoding="utf-8")
    (folder / "LICENSE-model.txt").write_text(license_text, encoding="utf-8")
    (folder / "NOTICE-model.txt").write_text(
        f"Model: {MODEL} (dimensions: {found['dims']})\n"
        f"Files: ONNX export used by fastembed, sources {json.dumps(found['sources'], ensure_ascii=False)}\n"
        f"Original model: https://huggingface.co/{MODEL}\n"
        f"License: {found['license'] or 'apache-2.0'} (Apache License 2.0, text in LICENSE-model.txt)\n"
        f"Mirrored in amemo releases ({HOMEPAGE}) so that installation does not depend on Hugging Face.\n",
        encoding="utf-8")
    target = out / MODEL_ZIP
    size = _zip(folder, target)
    log(f"модель: {target} — {mb(size)}")


def _zip(folder: Path, target: Path) -> int:
    """Содержимое folder в zip (пути от folder, без самой папки) и рядом target.sha256 в формате sha256sum."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                z.write(path, path.relative_to(folder).as_posix())
    (target.parent / (target.name + ".sha256")).write_text(f"{sha256(target)}  {target.name}\n", encoding="utf-8")
    return target.stat().st_size


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="step", required=True)
    for name in ("postgres", "pgvector", "python"):
        sub.add_parser(name).add_argument("work", type=Path)
    p = sub.add_parser("assemble")
    p.add_argument("work", type=Path)
    p.add_argument("--wheels", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--vcredist", type=Path, help="папка Microsoft.VC*.CRT: библиотеки Visual C++ в комплект")
    p = sub.add_parser("model")
    p.add_argument("work", type=Path)
    p.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    work = args.work.absolute()
    if args.step == "postgres":
        cmd_postgres(work)
    elif args.step == "pgvector":
        cmd_pgvector(work)
    elif args.step == "python":
        cmd_python(work)
    elif args.step == "assemble":
        cmd_assemble(work, args.wheels.absolute(), args.out.absolute(),
                     args.vcredist.absolute() if args.vcredist else None)
    else:
        cmd_model(work, args.out.absolute())
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
