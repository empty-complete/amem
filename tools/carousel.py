"""Анимации карусели мастера (приложение amemo для Windows, спецификация п. 5): GIF из README пережимаются в
анимированный WebP для установщика.

    python tools/carousel.py [--width 960] [--quality 60]

docs/assets/readme/<язык>/demo-*.gif → web/src/setup/media/<язык>/demo-*.webp (папка не в git): ширина до 960 px
(окно приложения — 1200, карусель — правая колонка, запас на HiDPI), WebP с потерями, качество 60 — в 5–6 раз меньше
GIF при читаемом тексте интерфейса. Сборка мастера (web/vite.setup.config.ts) берёт WebP, если они есть, и тогда GIF
в установщик не попадают; без них — GIF (браузер, e2e).

Уже пережатый файл, чей исходник не менялся (SHA-256 в media/manifest.json), не пережимается: CI держит папку в
кэше. Нужен Pillow (в колёсах PyPI WebP с анимацией есть).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs" / "assets" / "readme"
TARGET = ROOT / "web" / "src" / "setup" / "media"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def convert(src: Path, out: Path, width: int, quality: int) -> None:
    from PIL import Image, ImageSequence

    frames, durations = [], []
    with Image.open(src) as image:
        for frame in ImageSequence.Iterator(image):
            rgb = frame.convert("RGB")
            if rgb.width > width:
                rgb = rgb.resize((width, round(rgb.height * width / rgb.width)), Image.LANCZOS)
            frames.append(rgb)
            durations.append(frame.info.get("duration", 100))
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    frames[0].save(tmp, "WEBP", save_all=True, append_images=frames[1:], duration=durations, loop=0,
                   quality=quality, method=6, minimize_size=True)
    tmp.replace(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools/carousel.py")
    ap.add_argument("--width", type=int, default=960)
    ap.add_argument("--quality", type=int, default=60)
    args = ap.parse_args(argv)
    try:
        import PIL  # noqa: F401
    except ImportError:
        sys.exit("нужен Pillow: pip install pillow")
    manifest_path = TARGET / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}
    key = f"{args.width}/{args.quality}"
    wanted = {}
    for src in sorted(SOURCE.glob("*/demo-*.gif")):
        name = f"{src.parent.name}/{src.stem}.webp"
        out = TARGET / name
        digest = f"{sha256(src)}@{key}"
        wanted[name] = digest
        if manifest.get(name) == digest and out.is_file():
            continue
        convert(src, out, args.width, args.quality)
        print(f"{src.relative_to(ROOT)}: {src.stat().st_size >> 10} КБ → {out.stat().st_size >> 10} КБ", flush=True)
    for stale in set(manifest) - set(wanted):        # сюжет убрали из README
        (TARGET / stale).unlink(missing_ok=True)
    TARGET.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(wanted, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    total = sum((TARGET / name).stat().st_size for name in wanted)
    print(f"карусель: {len(wanted)} анимаций, {total >> 10} КБ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
