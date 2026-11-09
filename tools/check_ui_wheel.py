"""Проверка поставки веб-UI: служба из установленных колёс amem и amem-web отдаёт /ui как положено.

Запускать интерпретатором окружения, куда поставлены оба колеса (CI — чистое окружение):
  AMEM_DSN=… python tools/check_ui_wheel.py [--port 8769]
Проверяется: /ui/ — 200, CSP службы и no-cache; файл сборки с хэшем — immutable; маршрут приложения (/ui/records/) —
та же страница; boot.js и значок — на месте. Код 0 — всё так, 1 — что-то нет (печатается что).
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

# без прокси из окружения: служба на 127.0.0.1
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(url: str) -> tuple[int, dict[str, str], str]:
    try:
        with OPENER.open(url, timeout=5) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8769)
    args = ap.parse_args(argv)
    base = f"http://127.0.0.1:{args.port}"
    state = tempfile.mkdtemp(prefix="amem-ui-check-")
    env = {**os.environ, "AMEM_DATA": os.path.join(state, "objects"), "AMEM_BACKEND": "none",
           "AMEM_QUERY_LOG": "off"}
    service = subprocess.Popen([sys.executable, "-m", "amem.service", "--port", str(args.port)], env=env,
                               cwd=state)
    failures: list[str] = []
    try:
        for _ in range(60):
            try:
                if get(f"{base}/health")[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(0.5)
        else:
            print("служба не поднялась за 30 с", file=sys.stderr)
            return 1

        def expect(ok: bool, what: str) -> None:
            print(("ok   " if ok else "НЕТ  ") + what)
            if not ok:
                failures.append(what)

        status, headers, html = get(f"{base}/ui/")
        expect(status == 200, "/ui/ — 200")
        expect("script-src 'self'" in headers.get("content-security-policy", ""), "/ui/ — CSP службы")
        expect(headers.get("cache-control") == "no-cache", "/ui/ — no-cache")
        expect('src="/ui/boot.js"' in html and "<script>" not in html, "без встроенных скриптов, boot.js подключён")
        asset = re.search(r'/ui/assets/index-[^"]+\.js', html)
        expect(asset is not None, "в странице есть файл сборки с хэшем")
        if asset:
            expect("immutable" in get(base + asset.group(0))[1].get("cache-control", ""), "файл с хэшем — immutable")
        expect(get(f"{base}/ui/records/")[2] == html, "маршрут приложения — та же страница")
        expect(get(f"{base}/ui/boot.js")[0] == 200, "boot.js — 200")
        expect(get(f"{base}/ui/favicon.svg")[0] == 200, "значок — 200")
    finally:
        service.terminate()
        service.wait(timeout=15)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
