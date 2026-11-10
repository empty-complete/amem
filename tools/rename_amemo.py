"""Переименование проекта amem → amemo: содержимое файлов и пути (git mv).

    python tools/rename_amemo.py [--dry-run]       в корне рабочего дерева

Для веток, начатых до переименования: прогнать скрипт на своей ветке, закоммитить, затем слить main — обе
стороны переименованы одинаково, конфликтов от переименования нет. Повторный запуск ничего не меняет.

Не меняется:
- миграции 0001–0012, уже бывшие в main: база сверяет их по sha256; функции триггеров переименовывает
  0013_rename_amemo.sql — скрипт создаёт её из старых определений, если её ещё нет;
- метки форматов amem.<вид>/<N> (atom, entity, bundle, card, check) и поле amem_version: ими помечены
  неизменяемые ревизии в базе и файлы подборок;
- этот файл.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

SELF = "tools/rename_amemo.py"
RENAME_SQL = "amemo/sql/0013_rename_amemo.sql"
APPLIED = re.compile(r"^amemo?/sql/00(0[1-9]|1[0-2])_[^/]+\.sql$")          # миграции из main: 0001–0012
WORD = re.compile(r"amem(?!o)", re.IGNORECASE)                                 # amemo — уже новое имя
# сохраняются только в нижнем регистре: amem.atom/1, amem\\.check/ (шаблон в JSON-схеме), amem_version
KEEP = re.compile(r"amem(?=(?:\\*\.)(?:atom|entity|bundle|card|check)/|_version\b)")
_FUNCTION = re.compile(r"^CREATE FUNCTION (amem_[a-z_]+)\(\)(.*?)^\$\$;$", re.M | re.S)


def rename_text(text: str) -> str:
    def new(m: re.Match) -> str:
        word = m.group(0)
        if word == "amem" and KEEP.match(text, m.start()):
            return word
        return word + ("O" if word.isupper() else "o")
    return WORD.sub(new, text)


def rename_path(path: str) -> str:
    return WORD.sub(lambda m: m.group(0) + ("O" if m.group(0).isupper() else "o"), path)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def rename_sql(root: Path) -> str | None:
    """0013_rename_amemo.sql: новые имена функций триггеров и сообщения «amemo: …»; None — функций amem_ нет."""
    blocks: dict[str, str] = {}
    sql = root / "amemo" / "sql" if (root / "amemo" / "sql").is_dir() else root / "amem" / "sql"
    for path in sorted(sql.glob("00*.sql")):
        if APPLIED.match(f"amem/sql/{path.name}"):
            for m in _FUNCTION.finditer(path.read_text(encoding="utf-8")):
                blocks[m.group(1)] = m.group(2)
    if not blocks:
        return None
    lines = ["-- Имя проекта amem → amemo: функции триггеров получают новые имена и сообщения «amemo: …».",
             "-- Миграции 0001–0012 не меняются (база сверяет их по sha256). Триггеры ссылаются на функцию по OID,",
             "-- поэтому переименование их не задевает. Файл создан tools/rename_amemo.py.", ""]
    for name in blocks:
        lines.append(f"ALTER FUNCTION {name}() RENAME TO amemo{name[4:]};")
    for name, rest in blocks.items():
        body = rest.replace("'amem: ", "'amemo: ")
        lines += ["", f"CREATE OR REPLACE FUNCTION amemo{name[4:]}(){body}$$;"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog=SELF)
    ap.add_argument("--dry-run", action="store_true", help="только посчитать")
    args = ap.parse_args(argv)
    root = Path(_git("rev-parse", "--show-toplevel").strip())
    files = [f for f in _git("-C", str(root), "ls-files", "-z").split("\0") if f]
    text_with_word = set(_git("-C", str(root), "grep", "-I", "-l", "-i", "amem").splitlines())
    changed = 0
    for rel in files:
        if rel == SELF or rel == RENAME_SQL or APPLIED.match(rel) or rel not in text_with_word:
            continue
        path = root / rel
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        new = rename_text(text)
        if new != text:
            changed += 1
            if not args.dry_run:
                path.write_text(new, encoding="utf-8")
    moves = [(rel, rename_path(rel)) for rel in files if rename_path(rel) != rel]
    if not args.dry_run:
        for old, new in moves:
            (root / new).parent.mkdir(parents=True, exist_ok=True)
            _git("-C", str(root), "mv", old, new)
        target = root / RENAME_SQL
        if not target.exists():
            sql = rename_sql(root)
            if sql:
                target.write_text(sql, encoding="utf-8")
                _git("-C", str(root), "add", RENAME_SQL)
    print(f"{'проверка: ' if args.dry_run else ''}файлов с правкой содержимого {changed}, переносов {len(moves)}")
    # строки длиннее на символ: biome переносит их так же, как в main, — иначе конфликты при слиянии
    biome = root / "web" / "node_modules" / ".bin" / "biome"
    if not args.dry_run and changed:
        if biome.exists():
            subprocess.run([str(biome), "format", "--write", "."], cwd=root / "web", check=True,
                           stdout=subprocess.DEVNULL)
        else:
            print("web: biome не установлен — выполните cd web && npm ci && npm run format")
    # model_v1.py: генератор переносит строки описания иначе, когда имена длиннее, — тот же вывод, что в main
    if not args.dry_run and changed:
        done = subprocess.run([sys.executable, "tools/gen_schema.py"], cwd=root, capture_output=True, text=True)
        if done.returncode != 0:
            print("model_v1.py: нужен venv с linkml (pip install -e '.[dev]'), затем python tools/gen_schema.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
