<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/banner-dark.svg">
    <img alt="amem — another memory" src="docs/assets/readme/banner-light.svg" width="100%">
  </picture>
</p>

<h3 align="center">Shared memory for people and AI agents, where every claim comes with its proof.</h3>

<p align="center">
  An open knowledge base of small, sourced statements. Agents propose, automatic checks find
  the quote in the actual file, and a human has the final word.
</p>

<p align="center">
  <a href="https://github.com/empty-complete/amem/actions/workflows/ci.yml"><img alt="Tests" src="https://img.shields.io/github/actions/workflow/status/empty-complete/amem/ci.yml?branch=main&label=tests&style=flat-square"></a>
  <a href="https://github.com/empty-complete/amem/actions/workflows/web.yml"><img alt="Web UI" src="https://img.shields.io/github/actions/workflow/status/empty-complete/amem/web.yml?branch=main&label=web%20ui&style=flat-square"></a>
  <a href="LICENSE.txt"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-2a78d6?style=flat-square"></a>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-3776ab?style=flat-square&logo=python&logoColor=white">
  <img alt="PostgreSQL 16+ with pgvector" src="https://img.shields.io/badge/PostgreSQL-16%2B%20%C2%B7%20pgvector-4169e1?style=flat-square&logo=postgresql&logoColor=white">
  <img alt="Status: early development" src="https://img.shields.io/badge/status-early%20development-eb6834?style=flat-square">
</p>

<p align="center">
  <a href="#quickstart"><b>Quickstart</b></a> ·
  <a href="#features"><b>Features</b></a> ·
  <a href="#how-it-works"><b>How it works</b></a> ·
  <a href="#roadmap"><b>Roadmap</b></a> ·
  <a href="docs/library.md"><b>Docs</b></a> ·
  <a href="docs/MANIFESTO.md"><b>Manifesto</b></a> ·
  <a href="README.ru.md"><b>Русский</b></a>
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/en/sky-dark.png">
    <img alt="The sky: the whole memory as a constellation of atoms and objects" src="docs/assets/readme/en/sky-light.png" width="100%">
  </picture>
</p>

> [!IMPORTANT]
> **amem is in early development.** The core library works today: storage with revisions, hybrid search,
> automatic checks, the review queue, entity cards, bundles and backups, tested in CI on PostgreSQL 18
> and 16. The HTTP service and the web UI run on it; the screenshots of the sky, a record, the review
> queue and an entity card are taken from the service. The agent picture is a placeholder until agent
> memory ships.

## Why amem

Agents forget everything between sessions, and what they do remember is text without proof. Notes and
wikis keep what people wrote, but not where it came from or who decided it was right.

amem keeps something smaller and sturdier: an **atom**. An atom is one statement, the exact place in the
file it came from, the full history of its changes, and the decision of a person.

<table>
  <tr>
    <td width="50%" valign="top">
      <b>Every claim has a source</b><br>
      A quote is checked against the real text of the file: a page in a PDF, a heading in Markdown,
      a cell range in a spreadsheet.
    </td>
    <td width="50%" valign="top">
      <b>Nothing is overwritten</b><br>
      Every change is a new revision with a reason, an author and a content hash. Mistakes are
      superseded, not erased.
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <b>Checks run on every write</b><br>
      Schema, units, the quote, common sense and duplicates are checked before anything lands.
      A failed batch writes nothing.
    </td>
    <td width="50%" valign="top">
      <b>The human decides</b><br>
      Agents propose and pre-verify. Accepting a claim into the canon is a person's call, and the
      system shows who made it.
    </td>
  </tr>
</table>

## Features

<table>
  <tr>
    <td width="50%" valign="top">
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/en/record-dark.png">
        <img alt="A record page with the quote highlighted on the source page" src="docs/assets/readme/en/record-light.png">
      </picture>
      <h3>A claim next to its proof</h3>
      A record reads like a note: properties, a Markdown body and the quote highlighted on the real page
      of the source file. Cited files are stored once by content hash and kept forever.
    </td>
    <td width="50%" valign="top">
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/en/review-dark.png">
        <img alt="The review queue with the claim, the quote and the decision buttons" src="docs/assets/readme/en/review-light.png">
      </picture>
      <h3>Review in one keystroke</h3>
      Anything doubtful, risky or changed lands in a queue. Each item shows the claim, the quote and
      its neighbours. <kbd>Y</kbd> confirms, <kbd>N</kbd> rejects, <kbd>J</kbd>/<kbd>K</kbd> move on, and
      parallel reviewers never get the same item.
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/en/card-dark.png">
        <img alt="An entity card with completeness and grouped parameters" src="docs/assets/readme/en/card-light.png">
      </picture>
      <h3>Entity cards</h3>
      A profile says which parameters an object needs. The card shows what is known, missing or in
      conflict, and it is built live from atoms, so nothing goes stale.
    </td>
    <td width="50%" valign="top">
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/en/agent-dark.svg">
        <img alt="An agent session that searches amem, fetches records and marks what helped (placeholder)" src="docs/assets/readme/en/agent-light.svg">
      </picture>
      <h3>Memory for agents</h3>
      Claude Code and Codex ask amem first. They read short cards, fetch only the records they need, and
      mark what helped, which costs fewer tokens than reading raw files. <i>Arrives with the MCP server.</i>
    </td>
  </tr>
</table>

**Under the hood**

- **Hybrid search.** Exact codes, full text and local vectors are merged with RRF. An exact code always
  comes first, and an ambiguous query returns every candidate instead of a guess.
- **History you can query.** Bodies are stored as canonical JSON (JCS) with a `sha256-c1:` hash, and
  `what_changed` answers "what changed since Monday" for one record or the whole base.
- **Files that stay put.** Sources live in an OCFL object store by content digest. When a new version
  of a file arrives, every record that cites an older version gets a review item.
- **Domain packs.** Vocabularies, templates and entity profiles are plug-in packages with versions
  and dependencies. The core itself is a pack.
- **Bundles.** You can share a branch of knowledge between bases as a folder or a zip, with or without
  the files. Ids survive the trip, and anything that differs from the local copy goes to review.
- **Backups with proof.** A backup is a `pg_dump` plus a snapshot of the object store. It is verified
  by a real trial restore into a temporary database.
- **Boring storage.** Data lives in plain PostgreSQL 16+ with pgvector. The schema is written in
  LinkML, with Pydantic models and JSON Schema generated from it.

## Quickstart

amem needs Python 3.11+, Docker (for PostgreSQL) and Linux or macOS. On Windows, use WSL2.

**1. Start PostgreSQL and install the library**

```bash
git clone https://github.com/empty-complete/amem.git
cd amem
docker compose up -d --wait db      # PostgreSQL 18 + pgvector on 127.0.0.1:5435
python3 -m venv .venv
.venv/bin/pip install -e .          # or -e ".[embed]" for local multilingual vectors
```

**2. Write a fact with its source**

```python
from pathlib import Path

from amem import check, db, recipes
from amem.check import Proposal
from amem.ocfl_store import ObjectStore

conn = db.connect("postgresql://amem:amem@127.0.0.1:5435/amem")
db.prepare(conn)                                  # migrations and the core vocabulary

docs = Path("my-docs")                            # the folder with your source files
store = ObjectStore(Path("amem-objects"))         # cited files, kept by content hash
(docs / "pgvector").mkdir(parents=True, exist_ok=True)
(docs / "pgvector" / "README.md").write_text(
    "## HNSW\n\nvector - up to 2,000 dimensions, halfvec - up to 4,000 dimensions\n")

fact = {
    "kind": "fact",
    "label": {"en": "pgvector indexes vector with HNSW up to 2,000 dimensions",
              "ru": "pgvector: индекс HNSW по vector — до 2000 измерений"},
    "summary_plain": {"en": "Longer embeddings need halfvec, up to 4,000.",
                      "ru": "Длинные векторы индексируются через halfvec, до 4000."},
    "sources": [{"path": "pgvector/README.md",
                 "selectors": [{"type": "heading", "value": "HNSW"}],
                 "quote": "vector - up to 2,000 dimensions"}],
}
result = check.submit(conn, store, docs, [Proposal("atom", fact)], agent="model:my-agent")
print(result.state, result.records[0]["status"])  # approved draft
```

Levels 1–4 passed and the file was copied into the store. The atom stays a `draft` until the semantic
review (level 5) or a person confirms it.

**3. Try to cite something the file doesn't say**

```python
wrong = {**fact, "sources": [{**fact["sources"][0], "quote": "vector - up to 16,000 dimensions"}]}
result = check.submit(conn, store, docs, [Proposal("atom", wrong)], agent="model:my-agent")
print(result.state, result.report["issues"][0]["code"])  # rejected quote_fuzzy
```

The whole batch is rejected and nothing is written. The report shows the closest real text in the file:
`vector - up to 2,000 dimensions`.

**4. Search**

```python
hits = recipes.exact_fact(conn, "halfvec", agent="model:my-agent")
print(hits["items"][0]["label"]["en"])  # pgvector indexes vector with HNSW up to 2,000 dimensions
```

The [library reference](docs/library.md) covers the rest: the review queue, entity cards, bundles,
folders and backups.

### Try the web UI on sample data

The web UI runs on the service, or on mock data of the same HTTP contract. What is there:

- **Sky.** The home page is a constellation of records, colored by family (source, work, object); a new
  record flashes as it lands. A 3D view loads on request.
- **Reading.** A record shows its properties and body next to the source: the quote highlighted on the real
  PDF page, a spreadsheet range or a text fragment, with the file version. Entity cards, objects and a
  feed of changes.
- **Writing.** Quick write in one line (`N`), a full editor with Markdown, formulas and sources, folders
  with drag and drop, and a kind constructor. Every action has a 6-second undo.
- **Review.** The queue in two panes with `J` `K` `Y` `N` `S`: the claim, its source, the reviewer's notes,
  a word diff for edits and both versions when a source changed. **Base** shows the queue, statuses and
  backups; **Bundles** exports and imports `amem.bundle/1` and anthologies.

Light and dark themes, Russian and English, phone layouts. The design system is described in
[`web/DESIGN.md`](web/DESIGN.md).

On the service, with a sample base (a weather station: sensors, a PDF manual with quotes, notes and an
open review queue), in an empty database:

```bash
.venv/bin/pip install -e . -e web/python          # the service and the web UI package
(cd web && npm ci && npm run build)               # Node 24+; the build goes into the amem-web package
export AMEM_DSN=postgresql://amem:amem@127.0.0.1:5435/amem AMEM_DOCS=~/amem-sample/docs
export AMEM_PACKS=$PWD/tools/sample-pack/meteo          # sample pack: sensors with profiles
.venv/bin/python tools/seed_sample.py             # the sample: 22 records, 2 open review items
.venv/bin/python -m amem.service                  # then open http://127.0.0.1:8767/ui/
```

On mock data, without a database:

```bash
cd web && npm ci && npm run dev:mock              # then open http://127.0.0.1:5173/ui/
```

### One-command install

```bash
pip install amem              # or pipx / uv tool install; until the PyPI release: pip install -e . from a clone
amem init --dsn postgresql://amem:amem@127.0.0.1:5435/amem   # database, object store; the DSN goes to amem.toml
amem install claude-code      # MCP server, hooks and skills; `amem install codex` for Codex CLI
amem doctor                   # what works and what to fix
```

`amem init --dsn` remembers the connection string in `~/.config/amem/amem.toml` (mode `0600`), so agents, hooks
and the CLI find the database without `AMEM_DSN` in their environment. PostgreSQL with pgvector comes from
`docker compose up -d --wait db` or your own server. CI runs these steps on every push.

## Service

The HTTP service serves the [v1 contract](docs/api/http-v1.openapi.yaml) at `/api/v1` and the web UI at `/ui`.
Start it with `amem serve` (or `python -m amem.service`):

```bash
export AMEM_DSN=postgresql://amem:amem@127.0.0.1:5435/amem
.venv/bin/amem serve      # http://127.0.0.1:8767; --host and --port change the address
```

- **Local trust.** By default the service listens on `127.0.0.1` only. It answers only to its own name in `Host`
  (`127.0.0.1`, `localhost`, `[::1]`, the bind address) and only to its own page or `AMEM_UI_ORIGINS` in `Origin`;
  writes take JSON only. The web UI gets a person cookie, new on every start. When you type the address into the
  browser, the page itself gets no cookie: the UI's first `fetch` to `/api/v1/session` receives it. Requests
  without the cookie (scripts, agents) write as a model, and their writes go through the checks.
- **Shared service.** With `AMEM_TOKENS` (a `0600` file with token hashes) every API request needs
  `Authorization: Bearer <token>`. A token without `write = true` is read-only: writes answer `403 read_only`.
  `/health` and the UI's static files stay public. A `--host` other than loopback without tokens is refused;
  `--no-auth` allows it for a closed network and prints a warning.
- **Behind a name.** With `--host 0.0.0.0` (for example, in docker compose) list the names clients use in
  `AMEM_ALLOWED_HOSTS`: `AMEM_ALLOWED_HOSTS=amem` accepts `Host: amem:8767`. List only names you control: a name a browser
  can resolve to someone else's address opens the service to DNS rebinding.
- **State.** Bundles and uploads live in `AMEM_STATE` (`~/.local/state/amem`) for 24 hours, up to
  `AMEM_STATE_QUOTA` per owner (10 GiB). The query log is `AMEM_STATE/queries.jsonl`; `AMEM_QUERY_LOG=off` turns
  it off. The service writes its own log to stderr.
- **Web UI.** `/ui` needs the web package: `pip install 'amem[web]'`. Without it `/ui` answers 404 with a hint,
  and the API works as usual.

## Docker compose

`docker-compose.yml` runs the database and the service; settings live in `.env` (copy `.env.example`), the file
itself holds no secrets.

```bash
cp .env.example .env                          # set AMEM_PG_PASSWORD and AMEM_AGENT
docker compose up -d --wait amem              # PostgreSQL 18 + pgvector and the service on http://127.0.0.1:8767
docker compose exec amem amem doctor
docker compose --profile web up -d --wait amem-web   # the same with the web UI at /ui (instead of amem)
```

- **Inside and outside.** The service listens on `0.0.0.0:8767` inside the compose network and is published only
  on `127.0.0.1:8767`. `AMEM_ALLOWED_HOSTS=amem` lets other containers call it as `http://amem:8767`.
- **Login.** Without `AMEM_TOKENS` the service runs with `--no-auth`: anyone who reaches the port writes as a model,
  so keep it on `127.0.0.1`. For a shared service issue a token
  (`docker compose exec amem amem token create person:me --file /var/lib/amem/state/tokens`), set
  `AMEM_TOKENS=/var/lib/amem/state/tokens` in `.env` and restart.
- **Volumes.** `amem-pg` (database), `amem-objects` (object store), `amem-state` (bundles, uploads, query log,
  tokens), `amem-backups` (`docker compose exec amem amem backup create`; the image has the PostgreSQL 18 client).
  `AMEM_DOCS_DIR` mounts your documents folder read-only.
- **Health.** Both the image and compose check `/health`; `docker compose up --wait` waits for it.
- **Profile `web`.** `amem-web` is the same service built with `amem[web]`. It shares the port and the volumes, so
  run either `amem` or `amem-web`.
- **Image.** `docker build -t amem .` (target `service`) or `--target web`; `--build-arg AMEM_EXTRAS=embed` adds
  the local embedding model.

## CLI

`pip install -e .` puts the `amem` command in the venv. It talks to the database directly (`AMEM_DSN` or
`amem init --dsn …`, which remembers the DSN in `~/.config/amem/amem.toml`) and does not need the service.

```
amem init [--dsn DSN]                 database and object store
amem serve [--host --port --no-auth]  HTTP API, /mcp and the web UI
amem mcp [--agent model:NAME]         MCP server on stdio, for an agent
amem search QUERY [--kind --limit]    search, step 1
amem timeline REF                     what is around a record, step 2
amem get REF...                       full records, step 3
amem card REF                         entity card
amem submit FILE.json                 write a batch (same body as POST /submit; "-" reads stdin)
amem review list|claim|release|resolve|stats
amem folders tree|create|delete|rename|move
amem export|inspect|import FILE.zip   bundles (import is a dry run without --apply)
amem backup create|list|restore|verify
amem token create|list|revoke         tokens of a shared service
amem base [name [NAME]]               database summary and name
amem doctor [--project DIR]          database, store, model, documents, agents, service
```

- **Output.** Text for people, or `--json` with the same object the HTTP API returns for that operation.
  An error names what to do next: «set AMEM_DSN or run amem init».
- **Exit codes.** `0` success, `1` environment (no database, no store), `2` wrong call, `3` ambiguous text
  instead of a reference (the candidates are printed), `4` not found, `5` the check rejected the batch (the
  report is printed), `6` conflict (item already resolved, folder taken, bundle collision).
- **Who writes.** In a plain terminal it is the person `AMEM_AGENT` (by default `person:` and your OS user name).
  When the environment belongs to an agent, the command runs as a model: `CLAUDECODE=1` — `model:claude-code`,
  the Codex sandbox variables — `model:codex`, `AMEM_AS_MODEL=name` — `model:name`. `--agent` sets the agent
  explicitly, but never `person:` inside an agent's environment.
- **Tokens.** `amem token create person:ann` (or `model:…`, `--read-only`) prints the token once and stores only
  its hash in `AMEM_TOKENS`. Only a person issues and revokes tokens.
- **Backups.** A model may run `amem backup create`, but without rotation: `--keep` and `restore` are for people.
- **Debugging.** `AMEM_DEBUG=1` adds the traceback of an internal error to stderr.

## MCP

The MCP server gives an agent 14 tools over the same operations as the HTTP API:

| Tool | What it does |
|---|---|
| `amem_search(query, kind?, limit?)` | Step 1: short hits `{ref, label, kind, status, snippet}` and a `retrieval_id` |
| `amem_similar(query \| ref, limit?)` | Similar records, in the same form |
| `amem_timeline(ref)` | Step 2: recent events of the record and its neighbors |
| `amem_get(refs)` | Step 3: full records with body, sources, status and open items |
| `amem_card(ref)` | Entity card `amem.card/1` |
| `amem_submit(proposals, links?, reason?)` | Write a batch through `check.submit` |
| `amem_helpful(retrieval_id, refs)` | Mark the atoms that helped |
| `amem_move(ref, folder)` | Move a record to an existing folder |
| `amem_object_status(path)`, `amem_mark_object(path, status, note?)` | What has been atomized from a document |
| `amem_review_claim`, `amem_review_release`, `amem_review_resolve` | For the semantic reviewer |
| `amem_vocab(scheme)` | Vocabulary codes with labels |

Search goes in three steps so the agent reads only what it needs: `amem_search` gives short cards,
`amem_timeline` shows what is around a hit, and `amem_get` returns the full records it picked. Text that matches
several records without a clear leader comes back as `ambiguous: true` with candidates, not as the first match.

**Over stdio.** `amem mcp` runs one session per process with its own small connection pool. Claude Code:

```bash
claude mcp add amem --env AMEM_DSN=postgresql://amem:amem@127.0.0.1:5435/amem -- amem mcp --agent model:claude-code
```

or in the project's `.mcp.json`:

```json
{
  "mcpServers": {
    "amem": {
      "command": "amem",
      "args": ["mcp", "--agent", "model:claude-code"],
      "env": { "AMEM_DSN": "postgresql://amem:amem@127.0.0.1:5435/amem" }
    }
  }
}
```

Codex CLI, in `~/.codex/config.toml` (the DSN stays in `amem.toml` or in the environment, not in this file):

```toml
[mcp_servers.amem]
command = "amem"
args = ["mcp", "--agent", "model:codex"]
env_vars = ["AMEM_DSN", "AMEM_CONFIG"]
```

**Over HTTP.** A running service serves the same tools at `/mcp` (Streamable HTTP):

```bash
claude mcp add --transport http amem http://127.0.0.1:8767/mcp --header "X-Amem-Agent: model:claude-code"
```

```toml
[mcp_servers.amem]
url = "http://127.0.0.1:8767/mcp"
http_headers = { "X-Amem-Agent" = "model:codex" }
```

- **Always a model.** An MCP client writes as `model:…`, and its writes go through the checks. Over stdio the
  agent comes from `--agent model:…` or the agent's environment; over `/mcp` from the `X-Amem-Agent` header,
  otherwise from the token's model agent, otherwise `AMEM_MODEL_AGENT` (`model:local`). `person:` is refused.
- **Shared service.** With `AMEM_TOKENS`, `/mcp` needs `Authorization: Bearer <token>` like the API; a read-only
  token can search, and write tools answer `read_only`. A header that disagrees with the token's model agent is
  refused.
- **Usefulness.** `amem_helpful` marks atoms only from a search of the same session (or, for clients without
  sessions, of the same agent and login); someone else's `retrieval_id` answers `forbidden`.
- **Query log.** Explicit searches (`amem search`, `amem_search`, `amem_similar`) add a line to
  `AMEM_STATE/queries.jsonl`, like the service's `/search`; reading steps do not.

## Agent memory

`amem install claude-code` and `amem install codex` connect amem to an agent, globally or with `--project DIR`.
`amem uninstall …` removes exactly what was installed; `--dry-run` shows the changes first.

| | Claude Code | Codex CLI |
|---|---|---|
| MCP server | `claude mcp add --scope user` (or `~/.claude.json`); project — `.mcp.json` | `[mcp_servers.amem]` in `~/.codex/config.toml`; project — `.codex/config.toml` |
| Hooks | `SessionStart`, `UserPromptSubmit`, `PreCompact` in `settings.json` | `SessionStart`, `UserPromptSubmit` in `hooks.json` |
| Skills | `~/.claude/skills/amem-*`; project — `.claude/skills/` | `~/.agents/skills/`; project — `.agents/skills/`, plus a block in `AGENTS.md` |

- **Hooks.** `amem hook SessionStart` adds 3–5 verified atoms about the project (by the git root name) and a
  reminder; `UserPromptSubmit` adds confident hits for the prompt («amem first»); `PreCompact` asks the summary
  to list findings worth saving. A hook reads the database directly, fits in 1.5 s, and on any failure answers
  nothing with exit code 0. Text from memory comes framed as data with its review status, not as instructions.
- **Skills.** `amem-remember` (write 1–3 atoms at the end of a task), `amem-answer` (answer from memory with
  sources), `amem-verify` (the semantic reviewer, level 5).
- **Who writes.** The installer sets `AMEM_AS_MODEL` for the MCP server and the hooks, so the agent writes as
  `model:claude-code` or `model:codex`, never as you.
- **Edits only its own.** JSON keys `amem` and hook entries with `amem hook`, a `# amem:begin … # amem:end` block in
  TOML, a `<!-- amem:begin … -->` block in Markdown. Before the first edit a file is copied to `<file>.amem-backup`.
- **Codex.** Codex passes an MCP server only the variables listed in `env_vars`; the installer lists `AMEM_DSN`,
  `AMEM_CONFIG`, `AMEM_STATE`, `PGPASSFILE` and `PGSERVICE` and never writes a connection string into
  `config.toml`. Put the database into `amem.toml` with `amem init --dsn …` (or into those variables). Codex reads
  project files only in a trusted project.
- **Project files.** With `--project` the files get a bare `amem` command, without this machine's path, so they
  can be committed; `amem` must be on the agent's `PATH`. A global install uses the full path.
- **Windows.** Hook commands are POSIX shell lines (`AMEM_AS_MODEL=… amem hook …`): they work on Linux, macOS and
  WSL2, not in native Windows shells. Use WSL2.
- **Check.** `amem doctor` shows what is installed (globally and for the project of the current folder) and whether
  its command still exists; then `claude mcp list` or `codex mcp list` confirms the agent sees the server.

**Scheduling `amem-verify`.** The semantic reviewer is an agent run on a schedule of your choice, for example
every night with cron:

```cron
# m h dom mon dow
30 3 * * *  cd ~/notes && claude -p "Use the amem-verify skill: review up to 20 open semantic items." >> ~/.local/state/amem/verify.log 2>&1
```

or a systemd user timer:

```ini
# ~/.config/systemd/user/amem-verify.service
[Service]
Type=oneshot
WorkingDirectory=%h/notes
ExecStart=/usr/bin/env claude -p "Use the amem-verify skill: review up to 20 open semantic items."

# ~/.config/systemd/user/amem-verify.timer
[Timer]
OnCalendar=*-*-* 03:30
Persistent=true
[Install]
WantedBy=timers.target
```

`systemctl --user enable --now amem-verify.timer`. The agent needs the amem MCP server (`amem install …`).

## How it works

```mermaid
flowchart LR
    agents["Agents<br/>MCP · CLI · hooks"] -- propose --> check
    people["People<br/>web UI · CLI"] -- write --> check
    check["check.submit<br/>1 schema and templates<br/>2 quote found in the file<br/>3 common sense<br/>4 duplicates"]
    check -- one transaction --> base[("PostgreSQL + pgvector<br/>atoms · entities · links · revisions")]
    check -. cited files by digest .-> files[("OCFL object store")]
    base --> queue{{"review queue"}}
    queue -- confirm or reject --> people
    base --> search["search recipes<br/>exact_fact · similar<br/>what_changed · around_entity"]
    search -- short cards, then full records --> agents
```

Every write goes through `check.submit`. It checks the whole batch, then writes it in one transaction:

1. **Schema and templates:** fields, types, link rules and UCUM units.
2. **Binding to the source:** the quote is found in the file, the page matches, and the numbers of the
   claim appear in the fragment. Works for PDF, Markdown, xlsx and docx. A scanned PDF page (an image
   without a text layer) is OCR'd with Tesseract through PyMuPDF when its language data is installed
   (`sudo apt install tesseract-ocr tesseract-ocr-rus` on Debian/Ubuntu, `brew install tesseract tesseract-lang`
   on macOS; languages `rus+eng` by default, `AMEM_OCR_LANGUAGES` to change). A quote matched against OCR
   text gets an `info` finding `quote_ocr` and a softer fuzzy threshold; without Tesseract such pages are
   reported as having no text layer.
3. **Common sense:** value ranges, units, and contradictions with atoms already in the base.
4. **Duplicates:** by text and by vector.

An error at level 1 or 2 rejects the batch with a report. Otherwise each record gets a status:

| Status | Meaning |
|---|---|
| `draft` | Passed levels 1–4 without remarks; waits for the semantic review (level 5) |
| `needs_review` | Has a warning or a high risk; waits for a person |
| `auto_verified` | Passed all five levels with low risk |
| `verified` | Confirmed by a person against the source. A person's own record is verified at once |
| `rejected` | Rejected by a person |
| `deprecated`, `superseded` | Retired; kept for history |

**What an atom looks like** (`amem.atom/1`):

```yaml
kind: fact
key: pgvector.hnsw_max_dimensions
label:
  en: pgvector indexes vector with HNSW up to 2,000 dimensions
  ru: "pgvector: индекс HNSW по vector — до 2000 измерений"
summary_plain:
  en: Longer embeddings need halfvec, up to 4,000.
  ru: Длинные векторы индексируются через halfvec, до 4000.
content:
  values:
    - {property: max_indexed_dimensions, amount: 2000, unit: "1"}
sources:
  - path: pgvector/README.md
    selectors: [{type: heading, value: HNSW}]
    quote: vector - up to 2,000 dimensions
    role: primary
```

The agent never sets the status; the checks and people do.

**Core concepts**

| Concept | What it is |
|---|---|
| **Atom** | A small typed claim: fact, term, method, decision, question, lesson, requirement or parameter |
| **Entity** | What atoms are about: project, document, edition, organization, person, place, software, topic |
| **Object** | A source file, web page or message. Files are stored once by content digest |
| **Link** | A typed relation between records, with rules for its ends. Links are retired, never deleted |
| **Revision** | One change of a record: a canonical body, a content hash, an author and a reason |
| **Pack** | A domain vocabulary with templates and entity profiles. The core is a pack too |
| **Bundle** | A portable selection of records (`amem.bundle/1`), with or without files |

**Search recipes.** Five named recipes return plain JSON, so agents can work with them directly:

| Recipe | Answers |
|---|---|
| `exact_fact` | *What exactly is X?* Codes, marks, full text and vectors merged with RRF |
| `similar` | *What else is like this?* Semantic neighbours of a text or a record |
| `what_changed` | *What changed since Monday?* Revisions, decisions, statuses, moves and links |
| `around_entity` | *What do we know around X?* Shortest paths over links, rated by the weakest link; stops at `limit` (300 by default, was unlimited before), `total` counts nodes without it |
| `overview` | *What does the whole base look like?* Hubs by number of links (`degree`), their neighbours, the edges between them; filter by `project` |

Agents mark the atoms that helped them. These marks decay over time and give a small, capped boost in
ranking. They never change a status or skip a check.

## Roadmap

- [x] **Core and storage:** LinkML schema, revisions, objects by digest, domain packs
- [x] **Search engine:** four recipes, RRF ranking, usefulness marks, backups
- [x] **Automatic checks** (levels 1–4) and a **review queue** with leases, audit and metrics
- [x] **Ontology:** entity profiles, live cards, portable bundles
- [x] **Library for the service:** folders, record lists, references by key, object view
- [x] **HTTP service:** `amem serve` with the [v1 contract](docs/api/http-v1.openapi.yaml)
- [x] **CLI and MCP server:** three-step retrieval, usefulness marks, `<private>` stripping
- [x] **Agent memory:** Claude Code hooks, Codex CLI, `amem install`, core skills
- [x] **Web UI:** all screens, on the service and on mock data; checked end to end against the service
- [ ] **asearch:** file search as an amem plugin

## Documentation

| | |
|---|---|
| [Library reference](docs/library.md) | Data model, search, checks, review queue, cards, bundles, folders, backups |
| [HTTP API v1](docs/api/) | The OpenAPI contract between the service and the web UI |
| [Manifesto](docs/MANIFESTO.md) | Why amem exists and what it stands for |
| [Design specs and plans](docs/superpowers/) | How each subproject was decided and built |

**Good to know**

- Schema v1 requires a Russian label (`ru`); other languages are optional. Full-text search is tuned
  for Russian, and the optional local vector model is multilingual.
- Vectors are local and optional: `pip install -e ".[embed]"` adds fastembed, and a model is downloaded
  only with explicit permission. `AMEM_BACKEND=none` turns the semantic channel off, and lexical search
  keeps working.
- Backups need the PostgreSQL 18 client (`pg_dump`, `pg_restore`, `psql`) in `PATH` or in `AMEM_PG_BIN`.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# test databases: PostgreSQL 18 (port 5433) and 16 (port 5434)
docker compose --profile test up -d --wait db-test db-test-pg16

# run the tests (backup tests need the PostgreSQL 18 client)
.venv/bin/pytest -q
```

To use other ports or servers, set `AMEM_TEST_DSNS="postgresql://…/test,postgresql://…/test"`. A missing
test database or client counts as a failure, not a skip. If your environment exports a `PYTHONPATH` from
other tooling (ROS, for example), it breaks pytest plugin autoloading, so run `env -u PYTHONPATH .venv/bin/pytest -q`.

After editing `amem/schema/amem_v1.yaml`, regenerate the models:

```bash
.venv/bin/python tools/gen_schema.py          # writes amem/model_v1.py and the JSON Schema
.venv/bin/python tools/gen_schema.py --check  # CI check: generated files are up to date
```
Before pushing, enable the privacy check: `git config core.hooksPath tools/hooks`; the hook reads its patterns from `~/.config/amem/private-patterns.txt` (outside the repository).

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) in English:
`type(scope): subject`, at most 100 characters, e.g. `fix(service): reject NUL in parameters`. The same
`core.hooksPath` enables a `commit-msg` hook that checks this when you commit;
`python3 tools/check_commits.py --revs origin/main..HEAD` checks a range by hand.


The web UI lives in [`web/`](web/) (React 19, HeroUI v3, TanStack). Run `npm run lint`, `npm test` and
`npm run e2e` there.

## Contributing

amem is built in the open. Issues and discussions are welcome. For a larger change, please open an issue
first so we can agree on the approach. Every pull request runs the `ci` workflow (tests on PostgreSQL 18 and 16)
and the `commits` workflow (Conventional Commits in English); changes to `web/` also run the `web` workflow.

## Built with

[PostgreSQL](https://www.postgresql.org/) ·
[pgvector](https://github.com/pgvector/pgvector) ·
[LinkML](https://linkml.io/) ·
[OCFL](https://ocfl.io/) ·
[PyMuPDF](https://pymupdf.readthedocs.io/) ·
[fastembed](https://github.com/qdrant/fastembed) ·
[React](https://react.dev/) ·
[HeroUI](https://www.heroui.com/) ·
[force-graph](https://github.com/vasturiano/force-graph)

## License

MIT, see [LICENSE.txt](LICENSE.txt). © 2026 Philipp Beloborodov (Филипп Белобородов).

<p align="center"><sub>amem is a tool for remembering well.</sub></p>
