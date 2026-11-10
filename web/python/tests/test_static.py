import pytest

import amemo_web


def test_static_dir_points_to_built_index():
    d = amemo_web.static_dir()
    if not (d / "index.html").exists():
        pytest.skip("статика не собрана: npm run build в web/")
    assert (d / "assets").is_dir()
    html = (d / "index.html").read_text(encoding="utf-8")
    assert '<div id="root">' in html
    assert "/ui/assets/" in html
