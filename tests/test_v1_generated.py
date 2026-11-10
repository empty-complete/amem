"""Сгенерированные файлы совпадают с amemo/schema/amemo_v1.yaml. Упал — выполнить python tools/gen_schema.py."""
import importlib.util
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "tools" / "gen_schema.py"


def test_generated_files_up_to_date():
    spec = importlib.util.spec_from_file_location("gen_schema", TOOL)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert gen.stale() == []
