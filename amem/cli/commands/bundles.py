"""Подборки локально, без службы: export, inspect, import — те же операции api, что у /bundles/*.

export кладёт подборку в AMEM_STATE (api.bundle_export: отбор, антология, предел места), переносит zip (и отчёт
антологии рядом, .html) в указанный файл и убирает папку состояния. import копирует zip в загрузку AMEM_STATE
(api.upload_finish — те же проверки архива), зовёт api.bundle_import и убирает загрузку: по умолчанию — пробный
импорт (план без записи), настоящий — --apply, и только человек. Владелец подборок CLI — агент команды.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from ..errors import USAGE, CliError
from . import add


def register(sub, shared) -> None:
    p = add(sub, shared, "export", "выгрузить подборку в zip", run_export)
    p.add_argument("out", metavar="FILE.zip", help="куда записать подборку (существующий файл не перезаписывается)")
    p.add_argument("--tag", action="append", help="записи с тегом (можно несколько раз)")
    p.add_argument("--project", help="сущность-проект ent:…")
    p.add_argument("--kind", action="append", help="вид атома")
    p.add_argument("--class", dest="entity_class", action="append", help="класс сущности")
    p.add_argument("--ref", action="append", help="запись atm:/ent:")
    p.add_argument("--status", action="append", help="статус (по умолчанию все, кроме rejected)")
    p.add_argument("--since", help="изменённые с момента ISO 8601 (с часовым поясом)")
    p.add_argument("--include-private", action="store_true", help="включить записи с пометкой private")
    p.add_argument("--with-files", action="store_true", help="с копиями файлов объектов")
    p.add_argument("--with-packs", action="store_true", help="с пакетами онтологии")
    p.add_argument("--anthology", action="store_true", help="антология с отчётом HTML")
    p.add_argument("--title", help="заголовок антологии")

    p = add(sub, shared, "inspect", "проверить zip подборки без базы", run_inspect)
    p.add_argument("file", metavar="FILE.zip")

    p = add(sub, shared, "import", "влить подборку в базу (по умолчанию — пробно, без записи)", run_import)
    p.add_argument("file", metavar="FILE.zip")
    p.add_argument("--trust", choices=("keep", "review"), help="keep — статусы как есть, review — всё на проверку")
    p.add_argument("--apply", action="store_true", help="настоящий импорт (только человек)")


def _selection(args) -> dict:
    selection = {}
    for name, value in (("tags", args.tag), ("kinds", args.kind), ("entity_classes", args.entity_class),
                        ("refs", args.ref), ("statuses", args.status)):
        if value:
            selection[name] = value
    if args.project:
        selection["project"] = args.project
    if args.since:
        selection["since"] = args.since
    if args.include_private:
        selection["include_private"] = True
    return selection


def run_export(ctx, args) -> int:
    from ... import api

    out = Path(args.out)
    report_out = out.with_suffix(".html")
    if report_out == out:                 # export x.html --anthology: отчёт не ложится поверх zip
        report_out = out.with_name(f"{out.stem}.report.html")
    for path in (out, report_out) if args.anthology else (out,):
        if path.exists() or path.is_symlink():
            raise CliError(f"{path}: файл уже есть — подборка не перезаписывает файлы", exit=USAGE, code="file")
    state = ctx.settings.state
    made = api.bundle_export(ctx.connect(), ctx.store(), state, agent=ctx.agent, owner=ctx.agent,
                             selection=_selection(args), with_files=args.with_files, with_packs=args.with_packs,
                             anthology=args.anthology, title=args.title, quota=ctx.settings.state_quota)
    folder = Path(state) / api.BUNDLES / made["id"]
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(folder / api.BUNDLE_FILE, out)
        if made["has_report"]:
            shutil.move(folder / api.REPORT_FILE, report_out)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    result = {**made, "file": str(out), "report_file": str(report_out) if made["has_report"] else None}

    def text(done):
        counts = ", ".join(f"{k} {v}" for k, v in done["summary"]["counts"].items())
        line = f"Подборка записана: {done['file']} ({counts})"
        return line + (f"\nотчёт: {done['report_file']}" if done["report_file"] else "")
    ctx.emit(result, text)
    return 0


def run_inspect(ctx, args) -> int:
    from ... import api, bundle

    state = Path(ctx.settings.state)
    state.mkdir(parents=True, exist_ok=True)
    report = api._jsonable(bundle.inspect(Path(args.file), tmp_dir=state))

    def text(done):
        r = done["report"]
        counts = ", ".join(f"{k} {v}" for k, v in (r.get("counts") or {}).items())
        state_line = "целая" if r["ok"] else f"повреждены части: {', '.join(r['damaged'])}"
        return f"Подборка {r.get('format')} из базы {r.get('base_id')}: {counts}; {state_line}"
    ctx.emit({"report": report}, text)
    return 0


def run_import(ctx, args) -> int:
    from ... import api

    source = Path(args.file)
    if not source.is_file():
        raise CliError(f"{source}: файла подборки нет", exit=USAGE, code="file")
    state, owner = ctx.settings.state, ctx.agent
    conn = ctx.connect()
    upload_id, part = api.upload_begin(state)
    try:
        shutil.copyfile(source, part)
        api.upload_finish(state, upload_id, part, owner=owner, quota=ctx.settings.state_quota)
        result = api.bundle_import(conn, ctx.store(), state, upload_id, agent=ctx.agent, owner=owner,
                                   trust=args.trust, dry_run=not args.apply)
    finally:
        part.unlink(missing_ok=True)
        shutil.rmtree(Path(state) / api.UPLOADS / upload_id, ignore_errors=True)

    def text(done):
        head = "План импорта (без записи)" if not args.apply else f"Влито пакетом {done['changeset_id']}"
        counts = ", ".join(f"{k} {v}" for k, v in (done.get("counts") or {}).items())
        lines = [f"{head}: {counts}"]
        lines += [f"  предупреждение: {w}" for w in done.get("warnings") or []]
        lines += [f"  коллизия: {c}" for c in done.get("collisions") or []]
        if not args.apply:
            lines.append("влить: тот же вызов с --apply")
        return "\n".join(lines)
    ctx.emit(result, text)
    return 0
