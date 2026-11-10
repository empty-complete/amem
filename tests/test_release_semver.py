"""tools/release.py semver: версия amemo (PEP 440) для приложения Tauri (desktop/), которому нужен semver."""
import importlib.util
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
