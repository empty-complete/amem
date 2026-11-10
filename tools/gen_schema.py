"""Генерирует amemo/model_v1.py (Pydantic) и amemo/schema/amemo_v1.schema.json из amemo/schema/amemo_v1.yaml.

  python tools/gen_schema.py          записать файлы
  python tools/gen_schema.py --check  только сравнить: код 1 и список устаревших файлов

Нужен LinkML — зависимость разработки (uv pip install --python .venv/bin/python -e '.[dev]'). Сервер работает без него.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "amemo/schema/amemo_v1.yaml"    # относительный путь: генератор записывает его в model_v1.py
PYDANTIC = ROOT / "amemo" / "model_v1.py"
JSON_SCHEMA = ROOT / "amemo" / "schema" / "amemo_v1.schema.json"


def _fail(message: str):
    sys.exit(f"gen_schema: {message}")


def _patch_pydantic(text: str) -> str:
    """Доводит вывод gen-pydantic до нужной строгости. Каждая правка проверяет, что нашла своё место."""
    # (a) Шаблоны полей: gen-pydantic ищет их через re.search, а `$` в Python совпадает и перед завершающим \n,
    # так что «ent:sp20\n» прошёл бы. fullmatch такую строку отклоняет.
    if "pattern.search(" not in text:
        _fail("вывод gen-pydantic изменился: нет «pattern.search(» — нечего заменять на fullmatch, посмотрите model_v1.py")
    text = text.replace("pattern.search(", "pattern.fullmatch(")
    # (b) NaN и Infinity нельзя ни хэшировать по RFC 8785, ни сохранить в jsonb.
    anchor = "        strict = False,\n"
    if text.count(anchor) != 1:
        _fail("вывод gen-pydantic изменился: в ConfiguredBaseModel нет единственной строки «strict = False,» — "
              "некуда вставить allow_inf_nan = False")
    return text.replace(anchor, anchor + "        allow_inf_nan = False,\n")


def generate() -> dict[Path, str]:
    try:
        from linkml.generators.jsonschemagen import JsonSchemaGenerator
        from linkml.generators.pydanticgen import PydanticGenerator
    except ImportError:
        _fail("не установлен LinkML (зависимость разработки). Выполните: "
              "uv pip install --python .venv/bin/python -e '.[dev]'")

    cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        py = PydanticGenerator(SOURCE).serialize()
        js = json.loads(JsonSchemaGenerator(SOURCE, top_class="Bundle").serialize())
    finally:
        os.chdir(cwd)
    py = _patch_pydantic(py)
    # Any в LinkML — любое значение, но генератор JSON Schema не включает в него массив.
    # Строки таблицы (Table.rows) — списки, поэтому массив добавляем.
    any_type = js.get("$defs", {}).get("Any", {}).get("type")
    if not isinstance(any_type, list):
        _fail("вывод генератора JSON Schema изменился: $defs.Any.type не список — посмотрите amemo_v1.schema.json")
    if "array" not in any_type:
        any_type.append("array")
    return {PYDANTIC: py, JSON_SCHEMA: json.dumps(js, ensure_ascii=False, indent=2) + "\n"}


def stale() -> list[Path]:
    return [p for p, text in generate().items() if not p.exists() or p.read_text(encoding="utf-8") != text]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Генерация model_v1.py и amemo_v1.schema.json из amemo_v1.yaml.")
    parser.add_argument("--check", action="store_true", help="только сравнить: код 1 и список устаревших файлов")
    args = parser.parse_args(argv)
    if args.check:
        old = stale()
        for p in old:
            print(f"устарел: {p.relative_to(ROOT)} — выполните python tools/gen_schema.py", file=sys.stderr)
        return 1 if old else 0
    for p, text in generate().items():
        p.write_text(text, encoding="utf-8")
        print(f"записан: {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
