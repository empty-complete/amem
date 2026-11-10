# amemo library reference

[Справочник на русском](library.ru.md) · [Back to README](../README.md)

This page documents the Python library — the part of amemo that is ready today: the data model,
search, automatic checks, the review queue, profiles and cards, bundles, folders and backups.
The HTTP service, CLI and MCP server build on these same functions (see the [roadmap](../README.md#roadmap)).

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
  (`amemo/packs/core` is the kernel itself; more packs via the `AMEMO_PACKS`
  environment variable). Codes used by records are enforced by foreign keys.
  A pack may depend on others (`requires`: pack name → version range); packs load
  in dependency order, the core (version 1.3.0) first, cycles and unmet ranges are errors,
  and a concept's `broader` must lead to a code of the same scheme in a loaded pack. An atom kind
  has a `family`: `source` (knowledge from a document) or `work` (from the work itself); a kind
  without one counts as `work`.
- **Basis and confidence** — an atom whose value does not come from a document about
  the object carries a `basis`: `default` (the domain's rule, "on the safe side"), `assumed`
  (accepted to go on, needs confirmation) or `author` (the person's own word; only a
  `person:` agent may set it). `default` and `assumed` without `derived_from` get a warning,
  as the rule behind them is not visible. A model's own estimate goes in `confidence`
  (0 to 1); a person's record has none.
- **Hub groundwork** — every database has a stable `base_id`; atoms imported
  from another base carry `provenance.origin_base`.

## Search

Four named recipes in `amemo.recipes`, each returning plain JSON-compatible data:

- `exact_fact(conn, query, agent=…)` — codes and marks (exact and prefix), Russian full text
  and vectors merged with RRF; an exact code always comes first, ambiguity returns all candidates;
- `similar(conn, query, agent=…)` — semantic neighbours of a text or of a record (`atm:` / `ent:` ref), with a text fallback;
- `what_changed(conn, ref=…, since=…, until=…)` — revisions, review decisions, statuses, folder moves and links over time;
- `around_entity(conn, ref, depth=1, rels=…, statuses=…)` — shortest paths over links and the
  `about` / `derived_from` fields; a path's confidence is its weakest scored link, and its
  `evidence_role` is the weakest source role.

Agents mark atoms that helped (`amemo.usefulness.mark_helpful`); marks decay over time and give
a small capped boost in ranking — they never change status or checks.

Vectors are local and optional: `pip install -e ".[embed]"` adds fastembed (a model is downloaded
only with explicit permission). `AMEMO_BACKEND=none` turns the semantic channel off — lexical search
keeps working and results say `semantic: unavailable`.

## Automatic checks

`amemo.check.submit(conn, store, docs, proposals, links, agent=…)` is the single entry point for
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

The review queue lives in `amemo.review`. `claim(conn, agent=…)` hands out the oldest items the agent
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

`group` is a code. To show groups in words, a pack may add an optional `parameter_group` vocabulary
(code, label); the core does not check it, and the web UI falls back to the code itself
(`operating_conditions` → “Operating conditions”). The sample pack `tools/sample-pack/meteo` shows all of it.

`amemo.profile.card(conn, ref, ancestors=True)` builds the card of an entity (format `amem.card/1`)
from the live `parameter` atoms about it; nothing is stored. Each field in `fields` has a `state`:

- `known` — one value (or several equal ones); the field also tells the `status` of the atom,
  who wrote it (`by`), `basis`, `confidence`, `rank`, source role and `sources`; other values go to `candidates`;
- `conflict` — different values with no single `preferred`, or "not applicable" against a value;
- `na` — the document says the quantity does not apply;
- `asked` — there is no value, but a question atom about it is open;
- `missing` — nothing is known yet.

`extra` lists atoms about quantities outside the profile (an entity without a profile has only `extra`),
`summary` counts fields by state, open blockers (`blockers_open`) and fields with a basis, and
`ancestors` holds the cards of the entities above along `part_of`. `amemo.profile.rules_for_entity(conn,
entity_class)` returns the rules a class gets from its templates.

`amemo.records.rebuild_projections(conn)` rebuilds the projections of atoms from all revisions
(idempotent, revision bodies stay as they are): `atom_property` is erased and built again, while
`atom_about` and `atom_derived` are protected from deletion and only get missing rows.

## Bundles

A bundle (`amem.bundle/1`) is a selection of records carried from one database to another: a folder
or a zip with the same layout. `manifest.json` is written last and holds the sha256 of every part;
the parts are `atoms.jsonl`, `entities.jsonl`, `links.jsonl`, `sources.jsonl`, `objects.jsonl` and
`concepts.jsonl`, and optionally the files of the source documents (`objects/sha256/…`), the
revision history and copies of the packs.

```python
from amemo import bundle

bundle.export(conn, store=store, folder=Path("out/shared"), agent="person:anna",
              selection=bundle.Selection(tags=("shared",), kinds=("parameter",)),
              with_files=True, with_history=False, with_packs=False)
bundle.inspect(Path("out/shared"))        # integrity check, no database needed
bundle.import_(conn, store, Path("out/shared"), agent="person:boris", trust="keep", dry_run=True)
```

**Export.** `Selection` narrows by `tags`, `kinds`, `entity_classes`, explicit `refs`, `project`,
`statuses` and `since`; a record must match every condition that is set. By default all statuses
except `rejected` are taken, and private records (`visibility: private`) stay out unless
`include_private=True`. The selection is then closed over references: entities the atoms are about,
editions of sources, links with both ends in the bundle, object records of every source, and the
packs that own the codes used. `with_files` adds the files from the object store, `with_history`
all revisions instead of the current one, `with_packs` copies of the pack folders. The result is
built aside and appears under its name only whole.

**Inspect.** `bundle.inspect(path)` returns the manifest plus `ok`, `damaged` (parts that are
missing or whose sha256 differs) and `unexpected` (files outside the manifest). A zip is checked
before it is unpacked: names, symbolic links, total size, number of entries and compression ratio.

**Import.** `bundle.import_(conn, store, folder, agent=…, trust="keep" | "review", dry_run=…)` never
overwrites, and runs in one transaction:

- a record the database does not have is created with the same id; its `provenance` tells the
  origin base, the hash of the original revision and the original agent;
- a record the database has already seen (any local revision with the same body) is left alone,
  so importing the same bundle twice does nothing;
- a record that differs gets a new `pending` revision and a review item with reason `imported`;
  the current revision does not change;
- a record with another `key`, or a `key` taken by another record, is a collision: the import is
  refused before anything is written (`dry_run` lists collisions instead); deprecated and superseded
  local records are skipped with a warning.

The packs of the manifest must be loaded with the same name, version and digest; otherwise
`BundleError` with `code="bundle_pack_missing"` says what is required and what is present (and the
path to add to `AMEMO_PACKS` if the bundle carries the packs). Other errors have their codes too:
`bundle_key_collision` (also a link id taken by a link with another `rel` or other ends),
`bundle_object_conflict`, `bundle_damaged`, `bundle_level1` (with the `amem.check/1` report). A file already in both databases is matched by
digest (a web page or a message — by address or name), and its copy is not stored twice. With
`trust="keep"` the status from the bundle is kept, except when the importer is a model (not `person:…`):
then a record that was checked or decided there (`verified`, `auto_verified`, `rejected`, `deprecated`,
`superseded`), a record with `basis: author`, or one written by a person waits for review
(`needs_review`, item `imported`) instead. With
`trust="review"` everything created is `needs_review`. The source check results are not taken on
trust: they are computed again against the local copies of the files, `no_file` where there is none; an
atom whose place is not confirmed that way (`fuzzy`, `not_found`, `no_file`) waits for review. A link is
retired by the import only if it is the same link (same id, `rel` and ends); agent concepts are taken only
for quantities (`property`), valid by schema and with a UCUM unit. Objects with new versions, paths or
files are taken in before the write, each in its own transaction (`objects.adopt`): the exclusive object
lock is held only while one object and its copies are stored, as with `objects.ingest`; the source check
runs without it, and the write transaction holds the shared lock, like `submit`, so `submit` does not wait
for an import. If the import is refused after that, what was taken in stays, as after `objects.ingest`:
the objects and their copies, the `source_changed` items set for a new version of a known object, the
text cache and the agent; importing again accepts the objects as they are. Re-importing the same bundle
does not take the exclusive lock, except for an object whose copy was skipped (no copy of the previous
version in the store): it is taken in again on every import until the copies arrive.
`dry_run=True` writes nothing and returns the plan: counts per action, warnings, collisions and the
level 1 report. The returned `Imported` also carries `changeset_id`, `queued` and `complete`.

## Folders, lists and object cards

- **Folders** (`amemo.folders`) sort records for people; a folder is a path like `Projects/Alpha`
  and is not part of a revision. The registry holds the folders (`create`, `delete`, `rename`;
  a new base gets four: Projects, Areas, Resources, Archive); `move(conn, ref, folder, agent=...)`
  moves an atom or an entity without a new revision and logs the move; `tree(conn)` returns the tree
  with counts (a record in `a/b` counts in `a` too) and the number of records with no folder.
  `lookup.get` shows the record's `folder`.
- **References** — `atm:` and `ent:` take a UUID or a `key` (`ent:sp20_13330`); an old key does not
  resolve (`records.resolve`, `RecordNotFound`). The database has a name: `db.set_base_name` / `db.base_name`.
- **Lists** — `lookup.list_records(conn, folder=, kinds=, statuses=, tag=, about=, limit=, cursor=)`
  returns summaries, newest first, by cursor, with `total` of the filter. `about` is an entity
  (`ent:...`) or an object (`obj:<UUID>` or a bare UUID): records whose current revision cites it.
  `lookup.labels(conn, refs)` gives labels for many references in one query.
- **Object card** — `lookup.object_view(conn, id)`: the object with versions, `status` (last mark),
  `cited_by` (sources of current revisions: record, object version, selectors, quote, verdict),
  `pages` (from the text cache, `None` if the text was never extracted; reading never extracts)
  and `sheets` (sheet names of xlsx/xlsm, else `None`).
- **Sheet window** — `objects.sheet(conn, store, id, n, name, "B2:D10")` returns `{name, range, rows}`
  with cell values as in the text used by checks. At most 10 000 cells per call (counted as a rectangle,
  empty cells too); without a range the window is `A1:L40`, cut at the data. `ObjectError.code` is
  `not_found`, `invalid` or `too_large`.

## Backup

`amemo.backup` needs the PostgreSQL 18 client (`pg_dump`, `pg_restore`, `psql`) — in `PATH`
or in the folder given by `AMEMO_PG_BIN`.

- `create(dsn, folder)` — a `pg_dump -Fc` dump plus a JSON manifest (SHA-256, `base_id`,
  migrations, record counts — taken from the same snapshot as the dump); the last 14 copies are kept;
- `snapshot(dsn, objects_root, folder)` — a full snapshot: the dump and a copy of the OCFL object store,
  tied together by `base_id` and SHA-256;
- `restore(source, dsn, objects_root=…)` — into an empty database (and an empty folder) only,
  everything is checked before anything is written;
- `verify(source, dsn)` — a real trial restore into a temporary database and a search, then cleanup.

Storage is PostgreSQL 16+ with pgvector; the schema of record is LinkML
(`amemo/schema/amemo_v1.yaml`), from which the Pydantic models and JSON Schema
are generated.
