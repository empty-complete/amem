"""tools/release.py semver и latest: версия amemo (PEP 440) для приложения Tauri (desktop/), которому нужен semver, и
манифест его обновлений latest.json."""
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "release.py"
spec = importlib.util.spec_from_file_location("release", TOOL)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


@pytest.mark.parametrize("pep440, expected", [
    ("0.1.0a1", "0.1.0-alpha.1"), ("0.1.0b3", "0.1.0-beta.3"), ("1.2.0rc2", "1.2.0-rc.2"), ("1.2.0", "1.2.0"),
    ("2.0", "2.0.0"), ("1!2.0", None), ("1.0.post1", None), ("1.0.dev3", None), ("1.0+local", None),
    ("1.2.3.4", None),
])
def test_semver(pep440, expected):
    if expected is None:
        with pytest.raises(SystemExit):
            release.semver(pep440)
    else:
        assert release.semver(pep440) == expected


def test_semver_of_this_amemo():
    version = release._version_of(release.ROOT / "amemo" / "__init__.py")
    assert release.semver(version)


def test_latest_json(tmp_path, capsys):
    setup = tmp_path / "amemo_0.1.0-alpha.2_x64-setup.exe"
    setup.write_bytes(b"MZ")
    (tmp_path / f"{setup.name}.sig").write_text("dW50cnVzdGVkIGNvbW1lbnQ=\n", encoding="utf-8")
    url = "https://github.com/empty-complete/amemo/releases/download/v0.1.0a2/amemo-setup-0.1.0a2-windows-x64.exe"
    data = release.latest(setup, url, "0.1.0a2", "notes", now=datetime(2026, 11, 11, 9, 0, tzinfo=timezone.utc))
    assert data == {"version": "0.1.0-alpha.2", "notes": "notes", "pub_date": "2026-11-11T09:00:00Z",
                    "platforms": {"windows-x86_64": {"signature": "dW50cnVzdGVkIGNvbW1lbnQ=", "url": url}}}
    assert release.main(["latest", "--setup", str(setup), "--url", url, "--version", "0.1.0a2"]) == 0
    assert json.loads(capsys.readouterr().out)["version"] == "0.1.0-alpha.2"
    with pytest.raises(SystemExit):
        release.latest(tmp_path / "unsigned.exe", url, "0.1.0a2")
    with pytest.raises(SystemExit):
        release.latest(setup, "file:///x.exe", "0.1.0a2")
