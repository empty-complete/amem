"""Антология — подборка проверенного и предпочтительного с читаемым отчётом (подпроект 5, часть F).

Отбор: действующие записи со статусом verified (условия отбора — как у bundle.Selection, статусы заменяются
на verified). Атомы с rank deprecated не входят. Если у одного объекта одна величина (параметр) записана
несколькими атомами и среди них есть preferred, в антологию идут только preferred — у получателя не будет
двух значений там, где база уже выбрала одно.

Подборка пишется тем же bundle.export (формат amem.bundle/1, импорт — bundle.import_). Отчёт — самодостаточная
HTML-страница: записи по объектам, значения, суть, источники с местом и цитатой.
"""

from __future__ import annotations

import html
import uuid
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from . import bundle, lookup
from .bundle import BundleError, Selection

ANTHOLOGY_STATUSES = ("verified",)


def _value_key(payload: dict) -> tuple[tuple[str, ...], str] | None:
    """Ключ «тот же параметр»: объекты about (отсортированные) и свойство первого значения."""
    if payload.get("kind") != "parameter":
        return None
    values = (payload.get("content") or {}).get("values") or []
    prop = values[0].get("property") if values else None
    about = tuple(sorted(payload.get("about") or ()))
    return (about, prop) if prop and about else None


def select(conn: psycopg.Connection, selection: Selection = Selection()) -> list[str]:
    """Ссылки atm: атомов антологии по отбору selection (статусы заменяются на verified), упорядоченные."""
    s = replace(selection, statuses=ANTHOLOGY_STATUSES)
    atom_ids, _ = bundle._select(conn, s)  # noqa: SLF001 — тот же отбор, что у подборки
    rows = bundle._current(conn, "atom", atom_ids)  # noqa: SLF001
    kept = {aid: r for aid, r in rows.items() if (r["payload"].get("rank") or "normal") != "deprecated"}
    groups: dict[tuple, list[uuid.UUID]] = defaultdict(list)
    for aid, r in kept.items():
        key = _value_key(r["payload"])
        if key:
            groups[key].append(aid)
    for ids in groups.values():
        preferred = [a for a in ids if kept[a]["payload"].get("rank") == "preferred"]
        if preferred:
            for a in ids:
                if a not in preferred:
                    kept.pop(a, None)
    return [f"atm:{aid}" for aid in sorted(kept, key=str)]


def _label(payload: dict) -> str:
    return (payload.get("label") or {}).get("ru") or ""


def _value_text(v: dict) -> str:
    unit = v.get("unit") or ""
    if v.get("value_text"):
        return f"{v['value_text']} {unit}".strip()
    if v.get("amount") is not None:
        return f"{v['amount']:g} {unit}".strip()
    lo, hi = v.get("lower_bound"), v.get("upper_bound")
    if lo is not None or hi is not None:
        return f"{'' if lo is None else f'{lo:g}'}…{'' if hi is None else f'{hi:g}'} {unit}".strip()
    return ""


def _place(selectors: list[dict]) -> str:
    out = []
    for s in selectors or ():
        t, v = s.get("type"), s.get("label") or s.get("value")
        out.append({"page": f"с. {v}", "sheet": f"лист {v}", "range": str(v)}.get(t, str(v)))
    return ", ".join(out)


def report(conn: psycopg.Connection, refs: list[str], *, title: str = "Антология") -> str:
    """HTML-отчёт по атомам refs: группы по объектам (about), в группе — запись, значения, суть, источники."""
    ids = {uuid.UUID(r.split(":", 1)[1]) for r in refs}
    atoms = bundle._current(conn, "atom", ids)  # noqa: SLF001
    about_ids = {uuid.UUID(a.split(":", 1)[1]) for r in atoms.values() for a in r["payload"].get("about") or ()}
    entities = bundle._current(conn, "entity", about_ids)  # noqa: SLF001
    found = lookup.revisions_sources(conn, "atom", [r["id"] for r in atoms.values()])
    names: dict[str, str] = {}

    def object_name(oid: str) -> str:
        if oid not in names:
            o = lookup.get_object(conn, oid) or {}
            names[oid] = o.get("original_name") or o.get("url") or oid
        return names[oid]

    groups: dict[str, list[dict]] = defaultdict(list)
    for r in atoms.values():
        about = r["payload"].get("about") or []
        key = about[0] if about else ""
        groups[key].append(r)

    def group_title(ref: str) -> str:
        if not ref:
            return "Без объекта"
        row = entities.get(uuid.UUID(ref.split(":", 1)[1]))
        return _label(row["payload"]) if row else ref

    e = html.escape
    parts = []
    for key in sorted(groups, key=lambda k: (k == "", group_title(k))):
        items = []
        for r in sorted(groups[key], key=lambda x: _label(x["payload"])):
            p = r["payload"]
            vals = ", ".join(t for t in (_value_text(v) for v in (p.get("content") or {}).get("values") or ()) if t)
            srcs = []
            for s in found.get(r["id"]) or ():
                quote = f" — «{e(s['quote'])}»" if s.get("quote") else ""
                srcs.append(f"<li>{e(object_name(str(s['object'])))}"
                            f"{', ' + e(_place(s.get('selectors') or [])) if s.get('selectors') else ''}{quote}</li>")
            basis = p.get("basis")
            items.append(
                "<article>"
                f"<h3>{e(_label(p))}</h3>"
                f"<p class=meta>{e(p.get('kind', ''))}{' · ' + e(vals) if vals else ''}"
                f"{' · основание: ' + e(basis) if basis and not srcs else ''}</p>"
                f"{'<p>' + e((p.get('summary_plain') or {}).get('ru', '')) + '</p>' if p.get('summary_plain') else ''}"
                f"{'<ul class=src>' + ''.join(srcs) + '</ul>' if srcs else ''}"
                f"<p class=ref>atm:{r['record_id']}</p>"
                "</article>")
        parts.append(f"<section><h2>{e(group_title(key))}</h2>{''.join(items)}</section>")
    made = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        "<!doctype html><html lang=ru><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width, initial-scale=1'>"
        f"<title>{e(title)}</title>"
        "<style>body{font:16px/1.55 system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem;"
        "color:#1d1f24;background:#fbfbfd}h1{font-size:1.6rem;margin:0 0 .25rem}h2{font-size:1.15rem;margin:2rem 0 .5rem;"
        "border-bottom:1px solid #d8dbe2;padding-bottom:.25rem}h3{font-size:1rem;margin:1rem 0 .15rem}"
        ".meta,.ref,.lead{color:#5b6070;font-size:.875rem;margin:0}.ref{font-family:ui-monospace,monospace;font-size:.75rem}"
        "ul.src{margin:.25rem 0;padding-left:1.1rem;font-size:.9rem}"
        "@media (prefers-color-scheme:dark){body{color:#e8eaef;background:#16181d}h2{border-color:#33363f}"
        ".meta,.ref,.lead{color:#a2a7b4}}</style>"
        f"<h1>{e(title)}</h1><p class=lead>{len(atoms)} записей · проверенное и предпочтительное · {made}</p>"
        + "".join(parts) + "</html>")


def export(conn: psycopg.Connection, *, store, folder: Path, agent: str, selection: Selection = Selection(),
           with_files: bool = False, title: str = "Антология") -> dict:
    """Записать антологию подборкой в folder (zip, если имя кончается на .zip) и вернуть
    {"manifest": манифест amem.bundle/1, "refs": атомы, "report": HTML-отчёт}. Пустой отбор — BundleError."""
    refs = select(conn, selection)
    if not refs:
        raise BundleError("антология пуста: в отборе нет проверенных записей")
    manifest = bundle.export(conn, store=store, folder=folder, agent=agent, with_files=with_files,
                             selection=Selection(refs=tuple(refs), statuses=ANTHOLOGY_STATUSES,
                                                 include_private=selection.include_private))
    return {"manifest": manifest, "refs": refs, "report": report(conn, refs, title=title)}
