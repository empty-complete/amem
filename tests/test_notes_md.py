"""Заметки Markdown (amemo/notes_md.py): .md по папкам, объекты в «Объекты/», файлы источников под исходными
именами, шапка с amemo_id, ссылки [[путь|название]], значения таблицей, связи; выгрузка через api.bundle_export."""
import json
import os
import zipfile
from pathlib import Path

import pytest

from amemo import api, bundle, check, db, folders, notes_md
from amemo.check import Proposal
from check_support import atom, entity, source_md, value

PACKS = Path(__file__).with_name("packs")
PERSON = "person:alice"


@pytest.fixture
def world(pg, monkeypatch, store, docs):
    """Датчик, параметр о нём с источником-заметкой и значением, своя заметка в папке со ссылкой на параметр."""
    monkeypatch.setenv("AMEMO_PACKS", os.pathsep.join([str(PACKS / "quantities"), str(PACKS / "ontology")]))
    db.prepare(pg)
    r = check.submit(pg, store, docs, [
        Proposal("entity", entity("@s", cls="sensor")),
        Proposal("atom", atom("@m", kind="parameter", about=["@s"], tags=["shared"],
                              sources=[source_md("заметка.md", "Масса 3 кг")],
                              content={"values": [value("mass", 3, "kg")]})),
        Proposal("atom", atom("@n", kind="note", body={"ru": "Общая заметка.\n\nВторой абзац."}, basis="author",
                              tags=["shared"], sources=None)),
    ], links=[{"rel": "see_also", "src": "@n", "dst": "@m"}], agent=PERSON)
    assert r.state == "approved", r.report
    refs = {rec["label"]: f"{'atm' if rec['target'] == 'atom' else 'ent'}:{rec['record_id']}" for rec in r.records}
    note = refs["@n"]                      # ключ ответа check.submit — @имя записи в пачке
    folders.move(pg, note, "Проекты/Кампус", agent=PERSON)
    return pg, refs, note


def read(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n).decode("utf-8") if n.endswith((".md", ".json")) else z.read(n) for n in z.namelist()}


def test_notes_by_folders_with_sources_and_links(world, store, tmp_path):
    pg, refs, note = world
    out = tmp_path / "notes.zip"
    m = notes_md.export(pg, store=store, out=out, selection=bundle.Selection(tags=("shared",)), agent=PERSON)
    assert m["format"] == notes_md.FORMAT and m["counts"] == {"notes": 2, "objects": 1, "files": 1}
    files = read(out)
    # заметка — в своей папке, объект без папки — в «Объекты/», файл источника — под исходным именем
    note_path = "Проекты/Кампус/Кронштейн крепится к закладной анкером (n).md"
    param_path = "Кронштейн крепится к закладной анкером (m).md"
    assert {note_path, param_path, "Объекты/Документ s.md", "Источники/заметка.md", notes_md.MANIFEST} <= set(files)
    text = files[note_path]
    head, body = text.split("---\n", 2)[1:]
    assert f'amemo_id: "{note}"' in head and 'kind: "note"' in head and 'tags: ["shared"]' in head
    assert body.lstrip().startswith("Общая заметка.\n\nВторой абзац.")
    assert "- see_also: [[Кронштейн крепится к закладной анкером (m)|Кронштейн крепится к закладной анкером (m)]]" \
        in body
    param = files[param_path]
    assert 'about: ["[[Объекты/Документ s|Документ s]]"]' in param
    assert "| mass | 3 | kg |" in param
    assert "- [[Источники/заметка.md]] — «Масса 3 кг»" in param
    assert json.loads(files[notes_md.MANIFEST])["counts"]["notes"] == 2


def test_same_names_and_unsafe_signs():
    names = notes_md._Names()
    assert names.place("А", "Б", ".md") == "А/Б.md"
    assert names.place("А", "б", ".md") == "А/б (2).md"                 # без учёта регистра, как в Windows
    assert notes_md._safe('Нагрузка: w0 / 2 "ветер" [зона #1]?', "x") == "Нагрузка w0 2 ветер зона 1"
    assert notes_md._safe("  ...  ", "запасное") == "запасное"


def test_api_markdown_format(world, store, tmp_path):
    pg, refs, note = world
    made = api.bundle_export(pg, store, tmp_path / "state", agent=PERSON, owner="o", selection={"tags": ["shared"]},
                             with_files=False, notes_format="markdown")
    assert made["summary"]["format"] == notes_md.FORMAT and made["summary"]["counts"]["files"] == 0
    with pytest.raises(api.BadRequest):
        api.bundle_export(pg, store, tmp_path / "state", agent=PERSON, owner="o", selection={},
                          notes_format="markdown", anthology=True)
    with pytest.raises(api.BadRequest):
        api.bundle_export(pg, store, tmp_path / "state", agent=PERSON, owner="o", selection={}, notes_format="pdf")


def test_parse_front_matter_title_and_generated_sections():
    note = notes_md.parse('---\ntitle: "Своё"\ntags: [Работа, "#наука", "объект:x"]\n---\n# Не заголовок\nТекст', "f")
    assert note["title"] == "Своё" and note["tags"] == ["работа", "наука"] and note["body"].startswith("# Не")
    assert notes_md.parse("# Заголовок\n\nТекст", "f")["title"] == "Заголовок"
    assert notes_md.parse("Просто текст", "Имя файла")["title"] == "Имя файла"
    assert notes_md.parse("---\n: : кривая\n---\nТекст", "f") == {"meta": {}, "title": "f", "body": "Текст", "tags": []}
    exported = '---\namemo_id: "atm:x"\n---\n\nТело.\n\n## Источники\n\n- [[Источники/a.md]]\n'
    assert notes_md.parse(exported, "f")["body"] == "Тело."


def test_round_trip_and_obsidian_vault(world, store, docs, tmp_path):
    """Выгруженные заметки обратно: без правок — без изменений; правка текста — новая ревизия той же записи;
    заметки хранилища Obsidian — новые записи в папках по пути, .obsidian пропускается."""
    pg, refs, note = world
    out = tmp_path / "notes.zip"
    notes_md.export(pg, store=store, out=out, selection=bundle.Selection(tags=("shared",)), agent=PERSON)
    root = tmp_path / "up"
    with zipfile.ZipFile(out) as z:
        z.extractall(root)
    assert notes_md.is_notes(root) and notes_md.inspect(root)["counts"] == {"notes": 3, "with_id": 3}
    plan = notes_md.import_(pg, store, docs, root, agent=PERSON, dry_run=True)
    assert plan["counts"] == {"new": 0, "changed": 0, "same": 2, "skipped": 1}
    path = root / "Проекты/Кампус/Кронштейн крепится к закладной анкером (n).md"
    path.write_text(path.read_text(encoding="utf-8").replace("Общая заметка.", "Общая заметка, правка."),
                    encoding="utf-8")
    vault = root / "Входящие"
    vault.mkdir()
    (vault / "Идея.md").write_text("---\ntags: [наука]\n---\nМысль из Obsidian.", encoding="utf-8")
    (root / ".obsidian").mkdir()
    (root / ".obsidian" / "workspace.md").write_text("служебное", encoding="utf-8")
    done = notes_md.import_(pg, store, docs, root, agent=PERSON, dry_run=False)
    assert done["counts"] == {"new": 1, "changed": 1, "same": 1, "skipped": 1} and done["changeset_id"]
    row = pg.execute("SELECT r.payload->'body'->>'ru' FROM atom_current r WHERE r.atom_id = %s",
                     (note.split(":", 1)[1],)).fetchone()
    assert row[0].startswith("Общая заметка, правка.")
    idea = pg.execute("SELECT a.folder, r.payload->>'kind', r.payload->'tags' FROM atom a "
                      "JOIN atom_current r ON r.atom_id = a.id WHERE r.payload->'label'->>'ru' = 'Идея'").fetchone()
    assert idea == ("Входящие", "note", ["наука"])
