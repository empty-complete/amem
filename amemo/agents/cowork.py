"""Плагин amemo для Claude Cowork и чата в приложении Claude: `amemo install cowork [--out FILE] [--dry-run]`.

В аккаунт claude.ai плагин ставит только человек: Customize → Plugins → Add → Upload plugin (zip папки плагина).
Командой или API этого не сделать, а плагин, поставленный из Claude Code (`claude plugin install`), остаётся на
этой машине и в аккаунт не попадает. Поэтому установщик собирает zip и говорит, куда его загрузить.

Что в плагине (https://claude.com/docs/plugins/build, …/platform-support; сверено 10.11.2026, FORMAT):
- .claude-plugin/plugin.json — name, displayName, version, description, author, license, homepage;
- .mcp.json — сервер MCP `amemo`: полный путь к команде amemo этой машины, `mcp --agent model:cowork` и
  AMEMO_AS_MODEL=cowork, как у Claude Code. Локальный сервер Cowork запускает только в сессии на этом компьютере
  (приложение Claude); в облачной сессии и в чате на claude.ai его нет — там amemo не виден;
- skills/ИМЯ/SKILL.md — навыки ядра (те же, что ставит `amemo install claude-code`).

Хуков нет: Cowork загружает хуки плагина и в облачных сессиях, где команды amemo нет, — хук падал бы на каждом
событии. Без хуков агент обращается к amemo через навыки и сервер MCP.

Zip собирается одинаково при одинаковом содержимом (порядок и время файлов фиксированы), пишется атомарно. Повторная
сборка без изменений ничего не пишет. Чужой файл по тому же пути не перезаписывается. `amemo uninstall cowork`
удаляет только свой zip; из аккаунта плагин убирает человек (Customize → Plugins).

Плагин сохраняется в аккаунте и после загрузки синхронизируется в Claude Code на любой машине. Путь к amemo в нём —
этой машины, поэтому загружать стоит с той машины, где идут сессии Cowork. На машинах, где amemo поставлен в Claude
Code (`amemo install claude-code`), сервер amemo получается дважды: оставьте один.
"""
from __future__ import annotations

import io
import json
import os
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from .. import __version__
from ..portable import home
from .install import InstallError, amemo_command, mcp_entry, show, skill_text
from .platforms import SERVER, SKILLS

FORMAT = "claude-plugin/2026-11-10"
DOCS = ("https://claude.com/docs/plugins/build", "https://claude.com/docs/plugins/platform-support")
NAME = "amemo"
MODEL = "cowork"
FILENAME = "amemo-plugin.zip"
UPLOAD = "Customize → Plugins → Add → Upload plugin"
HOMEPAGE = "https://github.com/empty-complete/amemo"
_STAMP = (2026, 1, 1, 0, 0, 0)                  # время файлов в zip: одинаковое содержимое — одинаковые байты


@dataclass
class PluginReport:
    path: Path
    dry_run: bool
    remove: bool = False
    action: str | None = None                   # создан | изменён | удалён; None — без изменений
    files: list[str] = field(default_factory=list)
    command: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"agent": "cowork", "format": FORMAT, "project": None, "dry_run": self.dry_run,
                "changed": self.action is not None, "path": str(self.path), "files": self.files,
                "command": show(self.command) if self.command else None,
                "changes": [{"path": str(self.path), "action": self.action}] if self.action else [],
                "commands": [], "notes": self.notes, "warnings": self.warnings}

    def lines(self) -> list[str]:
        if self.action is None:
            return [f"без изменений: {self.path}" if self.path.exists() or not self.remove
                    else f"без изменений: {self.path} нет"]
        return [f"{'будет ' if self.dry_run else ''}{self.action}: {self.path}"]


def manifest() -> dict:
    return {"name": NAME, "displayName": "amemo", "version": __version__,
            "description": "Shared memory with sourced claims: search, read and propose records in your amemo base "
                           "through the local MCP server.",
            "author": {"name": "amemo"}, "license": "MIT", "homepage": HOMEPAGE}


def plugin_files(command: list[str]) -> dict[str, str]:
    """Файлы плагина: путь в zip → текст."""
    entry = mcp_entry(command, MODEL)
    server = {"command": entry["command"], "args": entry["args"], "env": entry["env"]}
    files = {".claude-plugin/plugin.json": _json(manifest()),
             ".mcp.json": _json({"mcpServers": {SERVER: server}})}
    for name in SKILLS:
        files[f"skills/{name}/SKILL.md"] = skill_text(name)
    return files


def _json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def zip_bytes(files: Mapping[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, _STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[name].encode("utf-8"))
    return buffer.getvalue()


def is_ours(path: Path) -> bool:
    """Файл — zip плагина amemo: в нём .claude-plugin/plugin.json с name amemo."""
    try:
        with zipfile.ZipFile(path) as archive:
            return json.loads(archive.read(".claude-plugin/plugin.json")).get("name") == NAME
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return False


def default_path(env: Mapping[str, str]) -> Path:
    return home(env) / FILENAME


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def build(env: Mapping[str, str], out: Path | None = None, *, dry_run: bool = False) -> PluginReport:
    """Собрать zip плагина в out (по умолчанию ~/amemo-plugin.zip)."""
    path = Path(out).expanduser().absolute() if out is not None else default_path(env)
    if path.is_dir():
        raise InstallError(f"--out {path}: это папка, нужен путь к файлу .zip")
    command, note = amemo_command(env)
    files = plugin_files(command)
    data = zip_bytes(files)
    report = PluginReport(path, dry_run, files=sorted(files), command=command)
    if note:
        report.notes.append(note)
    if path.exists():
        if not is_ours(path):
            raise InstallError(f"{path}: файл есть, и это не плагин amemo — укажите другой путь (--out)")
        if path.read_bytes() != data:
            report.action = "изменён"
    else:
        report.action = "создан"
    if report.action and not dry_run:
        _write(path, data)
    report.notes += [f"загрузите {path} в приложении Claude или на claude.ai: {UPLOAD}; ставит плагин только "
                     f"человек, из командной строки этого не сделать",
                     "сервер amemo работает в сессиях Cowork на этом компьютере (приложение Claude); в облачных "
                     "сессиях и в чате на claude.ai локального сервера нет",
                     "плагин из аккаунта появится и в Claude Code; если там уже стоит amemo install claude-code, "
                     "сервер amemo будет дважды — оставьте один"]
    return report


def remove(env: Mapping[str, str], out: Path | None = None, *, dry_run: bool = False) -> PluginReport:
    """Удалить свой zip; из аккаунта плагин убирает человек."""
    path = Path(out).expanduser().absolute() if out is not None else default_path(env)
    report = PluginReport(path, dry_run, remove=True)
    if path.exists():
        if is_ours(path):
            report.action = "удалён"
            if not dry_run:
                path.unlink()
        else:
            report.warnings.append(f"{path}: это не плагин amemo — оставлен на месте")
    report.notes.append("из аккаунта плагин убирается в приложении Claude: Customize → Plugins → amemo → Remove")
    return report
