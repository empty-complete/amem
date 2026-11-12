"""Заметки Markdown, как в Obsidian: записи отбора — .md-файлами по папкам пользователя, объекты без папки —
в «Объекты/», файлы источников — в «Источники/» под исходными именами (а не по хэшу, как в подборке amem.bundle/1).

Заметка — YAML-шапка (amemo_id, вид, статус, теги, псевдонимы, «о чём» ссылками [[…]]) и текст: тело записи,
значения таблицей, формула, таблица, связи и источники ссылками на файлы. Имя файла — название записи без знаков,
запрещённых в именах файлов и ссылках Obsidian; повтор в одной папке — « (2)». Ссылки между заметками — полным
путём без «.md» и с подписью: [[Проекты/Кампус/Нагрузка|Нагрузка]] — так они однозначны при одинаковых именах.

amemo_id в шапке — для обратной загрузки: тот же файл обновит ту же запись, а не создаст новую."""
from __future__ import annotations

import json
import os
import re
import shutil
import unicodedata
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from . import __version__, bundle, lookup
from .ids import uuid7
from .ocfl_store import StoreError

FORMAT = "amemo.notes-md/1"
MANIFEST = "amemo-notes.json"
NAME_MAX = 120                       # знаков в имени файла без расширения
_BAD = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f]')
DIRS = {"ru": ("Объекты", "Источники"), "en": ("Objects", "Sources")}
HEAD = {"ru": ("Значения", "Формула", "Таблица", "Связи", "Источники", "стр."),
        "en": ("Values", "Formula", "Table", "Links", "Sources", "p.")}


def _text(value, lang: str) -> str:
    """Строка на языке lang из LangString; нет — на русском, английском или любом."""
    if isinstance(value, str):
        return value
    if not isinstance(value, dict) or not value:
        return ""
    return value.get(lang) or value.get("ru") or value.get("en") or next(iter(value.values()), "") or ""


def _safe(name: str, fallback: str) -> str:
    """Имя файла без запрещённых знаков, пробелы сжаты, не длиннее NAME_MAX; пустое — fallback."""
    name = _BAD.sub(" ", unicodedata.normalize("NFC", name))
    name = re.sub(r"\s+", " ", name).strip(" .")[:NAME_MAX].strip(" .")
    return name or fallback


def _yaml(value) -> str:
    """Значение шапки: строки и списки — в JSON-записи (это допустимый YAML, кавычки и переводы строк экранированы)."""
    return json.dumps(value, ensure_ascii=False)


class _Names:
    """Пути заметок и файлов: в каждой папке имя занято один раз, повтор — « (2)», « (3)»."""

    def __init__(self) -> None:
        self.taken: set[str] = set()

    def place(self, folder: str, stem: str, ext: str) -> str:
        base = f"{folder}/{stem}" if folder else stem
        path, n = f"{base}{ext}", 1
        while path.lower() in self.taken:
            n += 1
            path = f"{base} ({n}){ext}"
        self.taken.add(path.lower())
        return path


def _folders(conn, target: str, ids: list[uuid.UUID]) -> dict[uuid.UUID, str | None]:
    if not ids:
        return {}
    rows = conn.execute(f"SELECT id, folder FROM {target} WHERE id = ANY(%s)", (ids,)).fetchall()
    return {r[0]: r[1] for r in rows}


def _number(x) -> str:
    return f"{x:g}" if isinstance(x, float) else str(x)


def _values(values: list[dict], lang: str, head: tuple) -> list[str]:
    rows = []
    for v in values:
        name = _text(v.get("label"), lang) or v.get("property", "")
        if v.get("amount") is not None:
            amount = _number(v["amount"])
        elif v.get("lower_bound") is not None or v.get("upper_bound") is not None:
            amount = f"{_number(v.get('lower_bound', '…'))}…{_number(v.get('upper_bound', '…'))}"
        else:
            amount = v.get("value_text") or v.get("value_state") or ""
        rows.append(f"| {name} | {amount} | {v.get('unit') or ''} |".replace("\n", " "))
    return [f"## {head[0]}", "", "| | | |", "|---|---|---|", *rows, ""] if rows else []


def _table(table: dict, lang: str, head: tuple) -> list[str]:
    cols = table.get("columns") or []
    if not cols:
        return []
    codes = [c.get("code") for c in cols]
    out = [f"## {head[2]}", "", "| " + " | ".join(_text(c.get("label"), lang) or c.get("code", "") for c in cols) + " |",
           "|" + "---|" * len(cols)]
    for row in table.get("rows") or []:
        cells = [row.get(c) for c in codes] if isinstance(row, dict) else list(row)
        out.append("| " + " | ".join("" if c is None else str(c).replace("|", "\\|").replace("\n", " ")
                                     for c in cells) + " |")
    return [*out, ""]


def export(conn: psycopg.Connection, *, store, out: Path, selection: bundle.Selection, agent: str,
           with_files: bool = True, lang: str = "ru") -> dict:
    """Записать заметки отбора в zip out и вернуть манифест (format, counts). Отбор и его замыкание — как у
    подборки (bundle.gather): заметка о чём-то тянет за собой и объект. with_files — файлы источников из store."""
    out = Path(out)
    if out.exists():
        raise bundle.BundleError(f"{out.name}: уже есть — заметки пишутся в новое место")
    if with_files and store is None:
        raise bundle.BundleError("with_files: нужно хранилище объектов (store)")
    lang = lang if lang in DIRS else "ru"
    objects_dir, sources_dir = DIRS[lang]
    head = HEAD[lang]
    atoms, entities = bundle.gather(conn, selection)
    folder_of = _folders(conn, "atom", list(atoms)) | _folders(conn, "entity", list(entities))
    names = _Names()
    path_of: dict[uuid.UUID, str] = {}
    label_of: dict[uuid.UUID, str] = {}
    for target, rows in (("entity", entities), ("atom", atoms)):
        for rid in sorted(rows):
            label = _text(rows[rid]["payload"].get("label"), lang)
            label_of[rid] = label or f"{'ent' if target == 'entity' else 'atm'}:{rid}"
            folder = folder_of.get(rid) or (objects_dir if target == "entity" else "")
            path_of[rid] = names.place(folder, _safe(label, str(rid)), ".md")

    def wiki(rid: uuid.UUID) -> str:
        return f"[[{path_of[rid][:-3]}|{label_of[rid]}]]"

    # источники текущих ревизий и файлы под исходными именами
    revisions = {"atom": [r["id"] for r in atoms.values()], "entity": [r["id"] for r in entities.values()]}
    found = {t: lookup.revisions_sources(conn, t, ids) for t, ids in revisions.items()}
    object_ids = {bundle._ref_uuid(s["object"]) for f in found.values() for ss in f.values() for s in ss}
    objects = {o: lookup.get_object(conn, o) for o in sorted(object_ids)}
    file_of: dict[tuple[uuid.UUID, int], str] = {}
    links = bundle._links(conn, set(atoms) | set(entities))

    work = out.parent / f".{out.name}.{uuid7()}.part"
    work.mkdir(parents=True)
    try:
        for oid, o in objects.items():
            if not o or o["kind"] != "file":
                continue
            for v in o["versions"]:
                stem, ext = os.path.splitext(_safe(o.get("original_name") or "", str(oid)))
                rel = names.place(sources_dir, stem, ext) if with_files else f"{sources_dir}/{stem}{ext}"
                file_of[(oid, v["n"])] = rel
                if with_files:
                    target = work / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        shutil.copyfile(store.content(o["id"], v["n"]), target)
                    except (StoreError, OSError) as e:
                        raise bundle.BundleError(f"obj:{oid} версия {v['n']}: файл не скопирован из хранилища: "
                                                 f"{bundle._reason(e)}") from e
        counts = {"notes": 0, "objects": 0, "files": len(file_of) if with_files else 0}
        for target, rows in (("entity", entities), ("atom", atoms)):
            for rid, row in rows.items():
                p = row["payload"]
                about = [wiki(e) for e in (bundle._ref_uuid(a) for a in p.get("about") or []) if e in path_of]
                meta = {"amemo_id": f"{'ent' if target == 'entity' else 'atm'}:{rid}",
                        ("class" if target == "entity" else "kind"): row["code"],
                        "status": row["status"], "title": label_of[rid],
                        "tags": p.get("tags") or [], "aliases": p.get("aliases") or [],
                        "codes": p.get("codes") or [], "about": about,
                        "updated": row["recorded_at"].isoformat()}
                lines = ["---", *(f"{k}: {_yaml(v)}" for k, v in meta.items() if v not in ([], None, "")), "---", ""]
                text = _text(p.get("body"), lang) or _text(p.get("description"), lang)
                if text:
                    lines += [text.rstrip(), ""]
                content = p.get("content") or {}
                lines += _values(content.get("values") or [], lang, head)
                if (formula := content.get("formula")) and formula.get("latex"):
                    lines += [f"## {head[1]}", "", "$$", formula["latex"], "$$", ""]
                if content.get("table"):
                    lines += _table(content["table"], lang, head)
                mine = [lk for lk in links if bundle._ref_uuid(lk["src"]) == rid and not lk["retired_at"]]
                linked = [(lk["rel"], bundle._ref_uuid(lk["dst"])) for lk in mine]
                linked = [(rel, d) for rel, d in linked if d in path_of]
                if linked:
                    lines += [f"## {head[3]}", "", *(f"- {rel}: {wiki(d)}" for rel, d in linked), ""]
                srcs = found[target].get(row["id"], [])
                if srcs:
                    lines += [f"## {head[4]}", ""]
                    for s in srcs:
                        oid = bundle._ref_uuid(s["object"])
                        o = objects.get(oid) or {}
                        rel = file_of.get((oid, s["object_version"]))
                        page = s.get("page")
                        ref = (f"[[{rel}{f'#page={page}' if page and rel.lower().endswith('.pdf') else ''}]]"
                               if rel else o.get("url") or o.get("original_name") or s["object"])
                        where = f", {head[5]} {page}" if page else ""
                        quote = f" — «{s['quote']}»" if s.get("quote") else ""
                        lines.append(f"- {ref}{where}{quote}")
                    lines.append("")
                file = work / path_of[rid]
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
                counts["objects" if target == "entity" else "notes"] += 1
        manifest = {"format": FORMAT, "created_at": datetime.now(timezone.utc).isoformat(), "agent": agent,
                    "amem_version": __version__, "selection": selection.as_json(), "counts": counts,
                    "with_files": with_files, "lang": lang}
        (work / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        part = work.with_name(work.name + ".zip")
        try:
            with zipfile.ZipFile(part, "w") as z:
                for f in sorted(p for p in work.rglob("*") if p.is_file()):
                    name = f.relative_to(work).as_posix()
                    z.write(f, name, compress_type=zipfile.ZIP_DEFLATED if name.endswith((".md", ".json"))
                            else zipfile.ZIP_STORED)
            os.replace(part, out)
        finally:
            part.unlink(missing_ok=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return manifest


# --- загрузка: .md или zip хранилища Obsidian (план 12, PR 2) ---

_FRONT = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.S)
_H1 = re.compile(r"^#\s+(.+?)\s*$", re.M)
_GENERATED = re.compile(r"^## (?:" + "|".join(re.escape(h) for hs in HEAD.values() for h in hs[:5]) + r")\s*$", re.M)
SKIP_DIRS = {".obsidian", ".trash", ".git"}


def is_notes(root: Path) -> bool:
    """Папка загрузки — заметки Markdown (а не подборка): нет manifest.json, есть .md."""
    return not (Path(root) / "manifest.json").is_file() and any(_notes(Path(root)))


def _notes(root: Path):
    for f in sorted(root.rglob("*.md")):
        rel = f.relative_to(root)
        if f.is_file() and not f.is_symlink() and not any(p in SKIP_DIRS or p.startswith(".") for p in rel.parts):
            yield f, rel


def _tags(value) -> list[str]:
    items = value if isinstance(value, list) else re.split(r"[,\s]+", value) if isinstance(value, str) else []
    out = []
    for t in items:
        t = str(t).strip().lstrip("#").strip().lower()
        if t and ":" not in t.split()[0] and t not in out:
            out.append(t)
    return out


def inspect(root: Path) -> dict:
    """Отчёт загрузки заметок без базы: формат, сколько заметок и сколько из них выгружены из amemo (amemo_id)."""
    notes = list(_notes(Path(root)))
    with_id = 0
    for f, _ in notes:
        m = _FRONT.match(f.read_text(encoding="utf-8", errors="replace")[:4096])
        with_id += bool(m and re.search(r"^amemo_id:", m.group(1), re.M))
    return {"format": "markdown", "counts": {"notes": len(notes), "with_id": with_id}, "ok": True,
            "damaged": [], "unexpected": []}


def parse(text: str, stem: str) -> dict:
    """Заметка → {meta, title, body, tags}: шапка YAML (кривая — как нет её), название — title, первый
    заголовок # или имя файла; у выгруженной из amemo (amemo_id) — без разделов, которые выгрузка дописала сама."""
    import yaml

    meta: dict = {}
    m = _FRONT.match(text)
    if m:
        try:
            loaded = yaml.safe_load(m.group(1))
            meta = loaded if isinstance(loaded, dict) else {}
        except yaml.YAMLError:
            meta = {}
        text = text[m.end():]
    if meta.get("amemo_id"):
        cut = _GENERATED.search(text)
        if cut:
            text = text[:cut.start()]
    title = str(meta.get("title") or "").strip()
    if not title and (h1 := _H1.search(text)) and not text[:h1.start()].strip():
        title, text = h1.group(1), text[h1.end():]
    return {"meta": meta, "title": title or stem, "body": text.strip(), "tags": _tags(meta.get("tags"))}


def import_(conn: psycopg.Connection, store, docs, root: Path, *, agent: str, dry_run: bool = True,
            lang: str = "ru") -> dict:
    """Заметки папки root (распакованная загрузка) → записи: с amemo_id существующей записи — её новая ревизия
    (если поменялись название, текст или теги), иначе — новая заметка (вид из шапки kind, иначе note) в папке по
    пути файла. Объекты выгрузки (шапка class) не трогаются. dry_run — только план. Ответ — как у bundle.import_:
    counts (new, changed, same, skipped — ключи как у подборки), changeset_id, warnings, queued, collisions, complete."""
    from . import check, folders
    from .check import Proposal

    root = Path(root)
    counts = {"new": 0, "changed": 0, "same": 0, "skipped": 0}
    warnings: list[str] = []
    proposals: list[Proposal] = []
    places: list[str | None] = []
    for f, rel in _notes(root):
        note = parse(f.read_text(encoding="utf-8", errors="replace"), f.stem)
        meta = note["meta"]
        folder = rel.parent.as_posix() if rel.parent.as_posix() != "." else None
        if meta.get("class"):
            counts["skipped"] += 1
            continue
        ref = str(meta.get("amemo_id") or "")
        current = None
        if ref.startswith("atm:"):
            try:
                current = bundle._current(conn, "atom", {bundle._ref_uuid(ref)}).get(bundle._ref_uuid(ref))
            except (ValueError, bundle.BundleError):
                current = None
            if current is None:
                warnings.append(f"{rel.as_posix()}: записи {ref} в базе нет — загружается как новая")
        if current is not None:
            p = dict(current["payload"])
            before = (_text(p.get("label"), lang), _text(p.get("body"), lang), p.get("tags") or [])
            if before == (note["title"], note["body"], note["tags"]):
                counts["same"] += 1
                continue
            p["label"] = {**(p.get("label") or {}), lang: note["title"]}
            p["body"] = {**(p.get("body") or {}), lang: note["body"]} if note["body"] else p.get("body")
            p["tags"] = note["tags"] or None
            proposals.append(Proposal("atom", {k: v for k, v in p.items() if v is not None}, current["record_id"]))
            counts["changed"] += 1
        else:
            payload = {"ref": f"@n{len(proposals)}", "kind": str(meta.get("kind") or "note"),
                       "label": {lang: note["title"]}, "basis": "author"}
            if note["body"]:
                payload["body"] = {lang: note["body"]}
            if note["tags"]:
                payload["tags"] = note["tags"]
            proposals.append(Proposal("atom", payload))
            counts["new"] += 1
        places.append(folder)
    out = {"changeset_id": None, "counts": counts, "queued": [], "warnings": warnings, "collisions": [],
           "complete": True}
    if dry_run or not proposals:
        return out
    made = check.submit(conn, store, docs, proposals, agent=agent, reason="загрузка заметок Markdown")
    if made.state != "approved":
        raise bundle.BundleError("заметки не записаны: " + "; ".join(
            f"{i.get('where', '')}: {i.get('message', i.get('code', ''))}"
            for i in (made.report.get("issues") or [])[:5] if i.get("severity") == "violation"))
    # записи ответа — в порядке предложений (check.submit: план за планом)
    for rec, folder in zip(made.records, places):
        folders.move(conn, f"atm:{rec['record_id']}", folder, agent=agent)
    return out | {"changeset_id": str(made.changeset_id), "queued": made.queued, "complete": made.complete}
