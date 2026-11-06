# amem

[README на русском](README.ru.md)

**amem** («another memory») is an open knowledge base built from atoms — small,
verifiable statements with sources, revisions and links. It is meant to be a shared
hybrid memory for people and AI agents: every claim has a source, every change has
a revision, and the human stays the one who decides.

**Status: in development.** This repository contains the core and the storage layer
(schema, revisions, objects, domain packs), the search engine (full text, codes,
vectors, ranking, usefulness), backups and the automatic check of submitted records —
as a Python library with a test suite.
There is no server, CLI or web UI yet — they come in the next subprojects.

## How it works

- **Atoms** — typed statements (fact, term, method, decision, question, lesson,
  requirement, parameter). **Entities** — things atoms talk about (project, document,
  edition, organization, person, place, software, topic).
- **Objects** — source files and references, stored by content digest (OCFL):
  a copy linked from a source is kept forever.
- **Links** — typed relations between atoms and entities, with end-pair rules,
  symmetry and retirement instead of deletion.
- **Revisions** — nothing is overwritten: every change is a new revision with
  a canonical body and a content hash (JSON Canonicalization Scheme, `sha256-c1:`).
- **Checks** — sources are resolved to object versions and digests, the quote
  matcher finds a quote in the actual file text, and every submitted record goes
  through the automatic check pipeline (see [Automatic checks](#automatic-checks)).
- **Domain packs** — vocabularies and templates are pluggable packages
  (`amem/packs/core` is the kernel itself; more packs via the `AMEM_PACKS`
  environment variable). Codes used by records are enforced by foreign keys.
- **Hub groundwork** — every database has a stable `base_id`; atoms imported
  from another base carry `provenance.origin_base`.

## Search

Four named recipes in `amem.recipes`, each returning plain JSON-compatible data:

- `exact_fact(conn, query, agent=…)` — codes and marks (exact and prefix), Russian full text
  and vectors merged with RRF; an exact code always comes first, ambiguity returns all candidates;
- `similar(conn, query, agent=…)` — semantic neighbours of a text or of a record (`atm:` / `ent:` ref), with a text fallback;
- `what_changed(conn, ref=…, since=…, until=…)` — revisions, review decisions, statuses and links over time;
- `around_entity(conn, ref, depth=1, rels=…, statuses=…)` — shortest paths over links and the
  `about` / `derived_from` fields; a path's confidence is its weakest scored link, and its
  `evidence_role` is the weakest source role.

Agents mark atoms that helped (`amem.usefulness.mark_helpful`); marks decay over time and give
a small capped boost in ranking — they never change status or checks.

Vectors are local and optional: `pip install -e ".[embed]"` adds fastembed (a model is downloaded
only with explicit permission). `AMEM_BACKEND=none` turns the semantic channel off — lexical search
keeps working and results say `semantic: unavailable`.

## Automatic checks

`amem.check.submit(conn, store, docs, proposals, links, agent=…)` is the single entry point for
writing knowledge: it checks the whole batch, then writes it in one transaction.

1. schema and templates — fields, types, link rules, UCUM units;
2. binding to the source — the quote is found in the file, the page matches, numbers of the claim
   are present in the fragment; works for PDF, Markdown, xlsx and docx;
3. common sense — value ranges, units, contradictions with existing atoms;
4. duplicates — by text and by vector.

An error at level 1 or 2 rejects the whole batch with a report; nothing is written. Otherwise each
record gets a status: `draft`, `needs_review` or `auto_verified` (an edit of a verified record waits
for a human decision). The answer (`Submitted`) separates what is done from what is only queued:
`complete` is false when review items were created, `queued` lists them, and level 5 (semantic
review by a human) is reported as `queued`. Numbers recomputed by an agent must carry
`role: "derived"` in the source. High risk (`high_risk` in pack templates, `decision` in the core)
always goes to a human.

## Backup

`amem.backup` needs the PostgreSQL 18 client (`pg_dump`, `pg_restore`, `psql`) — in `PATH`
or in the folder given by `AMEM_PG_BIN`.

- `create(dsn, folder)` — a `pg_dump -Fc` dump plus a JSON manifest (SHA-256, `base_id`,
  migrations, record counts — taken from the same snapshot as the dump); the last 14 copies are kept;
- `snapshot(dsn, objects_root, folder)` — a full snapshot: the dump and a copy of the OCFL object store,
  tied together by `base_id` and SHA-256;
- `restore(source, dsn, objects_root=…)` — into an empty database (and an empty folder) only,
  everything is checked before anything is written;
- `verify(source, dsn)` — a real trial restore into a temporary database and a search, then cleanup.

Storage is PostgreSQL 16+ with pgvector; the schema of record is LinkML
(`amem/schema/amem_v1.yaml`), from which the Pydantic models and JSON Schema
are generated.

## Development

Requires Python 3.11+ and Docker (for test databases).

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# test databases: PostgreSQL 18 (port 5433) and 16 (port 5434)
docker compose --profile test up -d --wait db-test db-test-pg16

# run the tests (backup tests need the PostgreSQL 18 client, see above)
.venv/bin/pytest -q
```

Other ports or servers: `AMEM_TEST_DSNS="postgresql://…/test,postgresql://…/test"`. A missing test
database or client is a test failure, not a skip.

If your environment exports a `PYTHONPATH` from other tooling (e.g. ROS), it
breaks pytest plugin autoloading — run tests with a clean one:

```bash
env -u PYTHONPATH .venv/bin/pytest -q
```

After editing `amem/schema/amem_v1.yaml`, regenerate and check the models:

```bash
.venv/bin/python tools/gen_schema.py          # writes amem/model_v1.py and the JSON Schema
.venv/bin/python tools/gen_schema.py --check  # CI check: generated files are up to date
```

## License and author

MIT, see [LICENSE.txt](LICENSE.txt). © 2026 Philipp Beloborodov (Филипп Белобородов).
