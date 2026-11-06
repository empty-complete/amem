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
  A pack may depend on others (`requires`: pack name → version range); packs load
  in dependency order, the core (version 1.2.0) first, cycles and unmet ranges are errors,
  and a concept's `broader` must lead to a code of the same scheme in a loaded pack.
- **Basis and confidence** — an atom whose value does not come from a document about
  the object carries a `basis`: `default` (the domain's rule, "on the safe side"), `assumed`
  (accepted to go on, needs confirmation) or `author` (the person's own word; only a
  `person:` agent may set it). `default` and `assumed` without `derived_from` get a warning,
  as the rule behind them is not visible. A model's own estimate goes in `confidence`
  (0 to 1); a person's record has none.
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
review by another model or a human) is reported as `queued`. Numbers recomputed by an agent must carry
`role: "derived"` in the source. High risk (`high_risk` in pack templates, `decision` in the core)
always goes to a human.

The review queue lives in `amem.review`. `claim(conn, agent=…)` hands out the oldest items the agent
may decide, with a lease (15 minutes by default) so that parallel reviewers never take the same
item; `release` gives an item back, `items` lists items for interfaces. `resolve(conn, item_id,
outcome, agent=…)` records a verdict and applies it, also without a prior claim. A model (`model:…`)
decides only `semantic`, never for its own batch, and gives a `confidence`: `confirmed` at 0.8 or
more makes an atom `auto_verified`, anything else sends it to a human as `semantic_doubt`; the
status changes only while the atom is still `draft`, otherwise just the verdict is recorded. A human
(`person:…`) decides everything with `confirmed` or `refuted`: the record becomes `verified` or
`rejected` and its other open items (except `source_changed`) are closed; for `edit` the edit is
accepted or declined and the record stays `verified`. `enqueue` lets a human put a record into the
queue by hand (`calibration`, `audit`), `stats` reports queue sizes, decision times, rejected
batches and audit results. When a file gets a new version (`objects.ingest`), the current and
pending revisions citing an older version get a `source_changed` item; `rejected`, `deprecated` and
`superseded` records are skipped.

A record written by a person (`person:…`) is `verified` at once, with no risk and no queue
(only `source_changed` can still queue it); levels 1 to 4 run as usual and their remarks stay in
the report. An edit of such a record by a model waits for a human decision. A low `confidence`
(below 0.8) means high risk when the template enables the `low_confidence` rule.

## Profiles and cards

A template for entities (`target: entity`) may have a `parameters` section — the profile of
an entity class: which quantities (codes of the `property` vocabulary) describe such a thing.
A rule sets the quantity, `required` (a blocker if missing), `group`, `origin` (where the value
usually comes from, vocabulary `parameter_origin`), `default` (shown, but never counted as a
value), and `ask` / `hint` / `when` (whom to ask, where to look, when it applies). Profiles
inherit through `extends`: a descendant's rule replaces its ancestor's rule for the same quantity.

`amem.profile.card(conn, ref, ancestors=True)` builds the card of an entity (format `amem.card/1`)
from the live `parameter` atoms about it; nothing is stored. Each field in `fields` has a `state`:

- `known` — one value (or several equal ones); the field also tells the `status` of the atom,
  who wrote it (`by`), `basis`, `confidence`, `rank`, source role and `sources`; other values go to `candidates`;
- `conflict` — different values with no single `preferred`, or "not applicable" against a value;
- `na` — the document says the quantity does not apply;
- `asked` — there is no value, but a question atom about it is open;
- `missing` — nothing is known yet.

`extra` lists atoms about quantities outside the profile (an entity without a profile has only `extra`),
`summary` counts fields by state, open blockers (`blockers_open`) and fields with a basis, and
`ancestors` holds the cards of the entities above along `part_of`. `amem.profile.rules_for_entity(conn,
entity_class)` returns the rules a class gets from its templates.

`amem.records.rebuild_projections(conn)` rebuilds the projections of atoms from all revisions
(idempotent, revision bodies stay as they are): `atom_property` is erased and built again, while
`atom_about` and `atom_derived` are protected from deletion and only get missing rows.

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
