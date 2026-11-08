"""Веб-интерфейс по /ui (подпроект 4, часть 4a, задача 8): статика пакета amem_web — здесь поддельного, в
sys.modules, с папкой сборки во временном каталоге. Кэш (immutable у файлов с хэшем, no-cache у index.html),
cookie человека у index.html только своей странице, SPA (неизвестный путь — index.html), обходы и символические
ссылки — 404, без пакета — 404 с подсказкой."""
import json
import sys
import types

import pytest

import contract
from amem import db
from amem.service import session

V1 = "/api/v1"
ASSET = "index-BxY3k9aP.js"
INDEX_HTML = "<!doctype html><title>amem</title><script type=module src=/ui/assets/index-BxY3k9aP.js></script>"


@pytest.fixture
def web(tmp_path, monkeypatch, pg):
    """Поддельный amem_web: dist/ с index.html, assets/ (файл с хэшем, ссылка наружу), значок; рядом — секрет."""
    db.prepare(pg)
    dist = tmp_path / "web" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (dist / "assets" / ASSET).write_text("console.log('amem')", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    secret = tmp_path / "web" / "secret.txt"
    secret.write_text("пароль от щита", encoding="utf-8")
    (dist / "assets" / "link.js").symlink_to(secret)
    (dist / "inside.js").symlink_to(dist / "assets" / ASSET)       # ссылка внутрь — тоже не отдаётся
    module = types.ModuleType("amem_web")
    module.static_dir = lambda: dist
    monkeypatch.setitem(sys.modules, "amem_web", module)
    return dist


def problem(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    contract.component("Problem", body)
    assert body["code"] == code
    return body


def common_headers(response) -> None:
    assert response.headers["x-content-type-options"] == "nosniff"
    csp = response.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "default-src 'self'" in csp and "frame-ancestors 'none'" in csp


def test_index_no_cache_and_cookie_only_for_own_page(serve, web):
    client = serve()
    typed = client.get("/ui/", headers={"Sec-Fetch-Site": "none"})       # адрес введён в строке браузера
    assert typed.status_code == 200 and typed.text == INDEX_HTML
    assert typed.headers["content-type"] == "text/html; charset=utf-8"
    assert typed.headers["cache-control"] == "no-cache"
    common_headers(typed)
    assert "set-cookie" not in typed.headers                 # cookie выдаст первый fetch /session интерфейса
    fetched = client.get(f"{V1}/session", headers={"Sec-Fetch-Site": "same-origin"})
    assert session.COOKIE in fetched.headers["set-cookie"]
    other = serve()
    own = other.get("/ui/index.html", headers={"Sec-Fetch-Site": "same-origin"})
    assert own.status_code == 200 and own.headers["cache-control"] == "no-cache"
    cookie = own.headers["set-cookie"]
    assert cookie.startswith(f"{session.COOKIE}=") and "HttpOnly" in cookie and "SameSite=Strict" in cookie
    assert other.get(f"{V1}/session").json()["agent"].startswith("person:")
    foreign = serve().get("/ui/", headers={"Sec-Fetch-Site": "cross-site"})        # переход с чужой страницы
    assert foreign.status_code == 200 and "set-cookie" not in foreign.headers


def test_hashed_assets_are_immutable(serve, web):
    client = serve()
    response = client.get(f"/ui/assets/{ASSET}")
    assert response.status_code == 200 and response.text == "console.log('amem')"
    assert "javascript" in response.headers["content-type"]
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    common_headers(response)
    icon = client.get("/ui/favicon.svg")
    assert icon.status_code == 200 and icon.headers["cache-control"] == "no-cache"


def test_unknown_path_is_index(serve, web):
    client = serve()
    for path in ("/ui/records/atm:0193b000-0000-7000-8000-000000000001", "/ui/review/", "/ui/review/items/x"):
        response = client.get(path)
        assert response.status_code == 200 and response.text == INDEX_HTML, path
        assert response.headers["cache-control"] == "no-cache"
    problem(client.get("/ui/assets/missing-AAAAAAAA.js"), 404, "not_found")     # нет скрипта — не HTML вместо него


@pytest.mark.parametrize("path", [
    "/ui/%2e%2e/secret.txt", "/ui/assets/%2E%2E/%2e%2e/secret.txt", "/ui/..%2fsecret.txt", "/ui/%252e%252e/secret.txt",
    "/ui/assets/link.js", "/ui/inside.js", "/ui/%2e/index.html", "/ui//index.html", "/ui/a%5c..%5csecret.txt",
    "/ui/x%00.js",
])
def test_traversal_and_symlinks_are_404(serve, web, path):
    response = serve().get(path)
    problem(response, 404, "not_found")
    assert "пароль" not in response.text


def test_redirects_to_ui(serve, web):
    client = serve()
    for path in ("/", "/ui"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 307 and response.headers["location"] == "/ui/", path


def test_without_package_404_with_hint(serve, pg, monkeypatch):
    db.prepare(pg)
    monkeypatch.setitem(sys.modules, "amem_web", None)        # пакет не установлен
    client = serve()
    for path in ("/", "/ui", "/ui/", "/ui/assets/x.js"):
        body = problem(client.get(path, follow_redirects=False), 404, "not_found")
        assert "pip install 'amem[web]'" in body["detail"], path


def test_package_without_build_404(serve, pg, monkeypatch, tmp_path):
    db.prepare(pg)
    module = types.ModuleType("amem_web")
    module.static_dir = lambda: tmp_path / "empty"
    monkeypatch.setitem(sys.modules, "amem_web", module)
    body = problem(serve().get("/ui/"), 404, "not_found")
    assert "сборки" in body["detail"]


def test_static_is_public_in_shared_service(serve, web, tmp_path):
    """Общая служба (AMEM_TOKENS): статика интерфейса без входа, cookie не выдаётся; API — по токену."""
    from test_service_core import tokens_file

    client = serve({"AMEM_TOKENS": tokens_file(tmp_path, ("t-one", "person:anna", True))})
    for path in ("/ui/", "/ui/index.html", f"/ui/assets/{ASSET}", "/ui/records/x"):
        response = client.get(path, headers={"Sec-Fetch-Site": "same-origin"})
        assert response.status_code == 200, path
        assert "set-cookie" not in response.headers
    assert client.get("/", follow_redirects=False).status_code == 307
    problem(client.get(f"{V1}/session", headers={"Sec-Fetch-Site": "same-origin"}), 401, "auth_required")
    assert client.get(f"{V1}/session", headers={"Authorization": "Bearer t-one"}).json()["agent"] == "person:anna"
    problem(client.post("/ui/index.html", json={}), 401, "auth_required")      # запись мимо API — тоже по токену


def test_immutable_only_for_vite_hashed_names(serve, web):
    """Без манифеста — по имени vite: «имя-хэш.расш», хэш 8+ знаков и не слово из строчных букв."""
    for name in ("index-template.js", "my.longfilename.js", "index.BxY3k9aP.js", "index-Bx3k9a.js",
                 "index-BxY3k9aP.js.map"):
        (web / "assets" / name).write_text("x", encoding="utf-8")
    (web / "assets" / "codemirror-D1x_k2-q.js").write_text("x", encoding="utf-8")
    (web / "assets" / "inter-latin-400-normal-C38fXH4l.woff2").write_bytes(b"x")
    (web / "hashed-BxY3k9aP.js").write_text("x", encoding="utf-8")         # не в assets/
    client = serve()
    for name in ("index-template.js", "my.longfilename.js", "index.BxY3k9aP.js", "index-Bx3k9a.js",
                 "index-BxY3k9aP.js.map"):
        response = client.get(f"/ui/assets/{name}")
        assert response.status_code == 200 and response.headers["cache-control"] == "no-cache", name
    for name in ("codemirror-D1x_k2-q.js", "inter-latin-400-normal-C38fXH4l.woff2", ASSET):
        assert client.get(f"/ui/assets/{name}").headers["cache-control"] == "public, max-age=31536000, immutable"
    assert client.get("/ui/hashed-BxY3k9aP.js").headers["cache-control"] == "no-cache"


def test_manifest_decides_immutable_and_is_not_served(serve, web):
    """С манифестом vite (.vite/manifest.json) immutable — только у файлов сборки из него; сам манифест — 404."""
    (web / ".vite").mkdir()
    (web / ".vite" / "manifest.json").write_text(json.dumps({
        "index.html": {"file": f"assets/{ASSET}", "css": ["assets/index-C9kQ2xZa.css"], "isEntry": True},
        "_codemirror-D1x_k2-q.js": {"file": "assets/codemirror-D1x_k2-q.js", "assets": ["assets/font-A1b2C3d4.woff2"]},
    }), encoding="utf-8")
    for name in ("index-C9kQ2xZa.css", "codemirror-D1x_k2-q.js", "font-A1b2C3d4.woff2", "stray-Q7w8E9r0.js"):
        (web / "assets" / name).write_text("x", encoding="utf-8")
    client = serve()
    for name in (ASSET, "index-C9kQ2xZa.css", "codemirror-D1x_k2-q.js", "font-A1b2C3d4.woff2"):
        assert client.get(f"/ui/assets/{name}").headers["cache-control"] == "public, max-age=31536000, immutable", \
            name
    stray = client.get("/ui/assets/stray-Q7w8E9r0.js")                # имя как у сборки, а в манифесте нет
    assert stray.status_code == 200 and stray.headers["cache-control"] == "no-cache"
    for path in ("/ui/.vite/manifest.json", "/ui/.vite/", "/ui/assets/.hidden.js"):
        problem(client.get(path), 404, "not_found")
    (web / ".vite" / "manifest.json").write_text("не JSON", encoding="utf-8")       # испорчен — никому immutable
    assert serve().get(f"/ui/assets/{ASSET}").headers["cache-control"] == "no-cache"
