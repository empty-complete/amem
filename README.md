# amem

[README на русском](README.ru.md)

**amem** («another memory») is an open knowledge base built from atoms — small,
verifiable statements with sources, revisions and links. It is meant to be a shared
hybrid memory for people and AI agents: every claim has a source, every change has
a revision, and the human stays the one who decides.

**Status: in development.** This repository currently contains the core and the
storage layer (schema, revisions, objects, domain packs) with a test suite.
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
- **Self-checking** — sources are resolved to object versions and digests;
  quotes are verified against the actual file text.
- **Domain packs** — vocabularies and templates are pluggable packages
  (`amem/packs/core` is the kernel itself; more packs via the `AMEM_PACKS`
  environment variable). Codes used by records are enforced by foreign keys.
- **Hub groundwork** — every database has a stable `base_id`; atoms imported
  from another base carry `provenance.origin_base`.

Storage is PostgreSQL 16+ with pgvector; the schema of record is LinkML
(`amem/schema/amem_v1.yaml`), from which the Pydantic models and JSON Schema
are generated.

## Development

Requires Python 3.10+ and Docker (for test databases).

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# test databases: PostgreSQL 18 (port 5433) and 16 (port 5434)
docker compose --profile test up -d --wait db-test db-test-pg16

# run the tests
.venv/bin/pytest -q
```

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
