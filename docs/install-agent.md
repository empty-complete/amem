# Install amemo: instructions for a coding agent

You are a coding agent (Claude Code, Codex or similar) with a shell on the user's machine. The user asked you to
install amemo, a verifiable shared memory for AI agents and people: <https://github.com/empty-complete/amemo>.
Follow these steps in order. They work from a bare machine: no Python, no Docker, no WSL, no PostgreSQL.

When you are done, the machine has:

- PostgreSQL 16 or newer with the pgvector extension, and a database for amemo;
- the `amemo` command (Python package `amemo` from PyPI, with the web UI);
- amemo connected to the user's coding agents (Claude Code, Codex): MCP server, hooks and skills;
- `amemo doctor` with no `FAIL` lines.

## Ground rules

- Talk to the user in the language they wrote to you in.
- Look before you install. Reuse what is already there: Python, uv, Docker, a PostgreSQL server with pgvector.
- Ask the user before anything that needs administrator rights (`sudo`, an elevated PowerShell), a reboot or a
  large download, and say why. If they say no, stop and tell them which steps are left.
- Never drop, overwrite or re-initialise an existing database, data directory, Docker container or volume. Never
  stop or reconfigure a PostgreSQL server that other programs use: create a separate role and database on it.
- Install Docker or WSL only when a step below needs it, never "just in case".
- Generate a random database password: `python3 -c "import secrets; print(secrets.token_hex(16))"` or
  `openssl rand -hex 16`; on Windows, in PowerShell, `[guid]::NewGuid().ToString('N')`. It ends up in amemo's
  config file only; don't show it in your final report.
- Check every step worked before you go on. If a step fails, read the error, fix the cause and repeat the step.

## 1. Find out where you are

Note the answers; later steps depend on them.

- **System.** Linux, macOS or Windows. On Linux, also `cat /etc/os-release`, and check for WSL with
  `grep -qi microsoft /proc/version && echo WSL`.
- **Tools present:** `python3 --version` (on Windows `python --version`), `uv --version`, `pipx --version`,
  `docker info`, `psql --version`, `claude --version`, `codex --version`, `amemo --version`; on Windows also
  `winget --version`.
- **An earlier install:** `~/.config/amemo/amemo.toml` (on Windows `%USERPROFILE%\.config\amemo\amemo.toml`). If it
  exists, amemo was installed before: tell the user and ask whether to repair that install or start over in a new
  database. Never delete the old one.

## 2. Windows only: native or WSL2

amemo runs natively on Windows 10 and 11. Skip this step on Linux and macOS, and when you already run inside WSL.

**Native Windows** is the default: the agents run on Windows too, and step 6 gives them the MCP server, hooks and
skills. Where the commands differ, the steps below have a **Windows** part; its commands are PowerShell. If your
shell is Git Bash (Claude Code's Bash tool on Windows), run them as `powershell -NoProfile -Command "…"` or with your
PowerShell tool. CI runs the native path on every push: PostgreSQL 18 from the EDB installer, pgvector built from
source, amemo from uv, `amemo install claude-code`, `amemo doctor`, the service and a backup.

**WSL2** only if the user already works inside WSL or asks for it:

1. `wsl -l -v`. If a version 2 distribution (Ubuntu or Debian) is listed, use it.
2. Otherwise ask the user, then run in an elevated PowerShell: `wsl --install -d Ubuntu`. Restart Windows if it
   asks. The user then opens Ubuntu from the Start menu once and creates a Linux user name and password; you can't
   do that part, so wait until they say it's done.
3. Pick how to continue and remember the choice for step 6:
   - **Recommended:** the user installs the agent inside Ubuntu (Claude Code or Codex both run on Linux), starts
     it there and gives it the same one-line request. Everything below then runs natively in WSL.
   - **Agent stays on Windows:** run every command below inside the distribution as
     `wsl -d Ubuntu -- bash -lc '<command>'`.

With WSL2, "Linux" below includes WSL.

## 3. PostgreSQL with pgvector

amemo needs PostgreSQL 16 or newer (18 is what CI tests first) with the `vector` extension. Use the first option
that fits.

### A. A server the user already has

If the user wants an existing server (local or hosted, for example Neon or Supabase), check that pgvector is
there: `SELECT default_version FROM pg_available_extensions WHERE name = 'vector';`. No row means pgvector is
missing: use option B or C instead of changing their server. With the row present, create the role and the
database as in [Role and database](#role-and-database). On a hosted server, create the extension from its console.

### B. Docker is installed and running

Only if `docker info` succeeds. Don't install Docker for this; option C works without it.

```bash
docker ps -a --filter name=amemo-db      # an old container: ask the user and reuse it, don't remove it
PW=$(openssl rand -hex 16)
docker run -d --name amemo-db --restart unless-stopped \
  -e POSTGRES_USER=amemo -e POSTGRES_PASSWORD="$PW" -e POSTGRES_DB=amemo \
  -p 127.0.0.1:5435:5432 -v amemo-pg:/var/lib/postgresql \
  pgvector/pgvector:0.8.1-pg18
until docker exec amemo-db pg_isready -h 127.0.0.1 -U amemo -d amemo; do sleep 1; done
```

On Windows (Docker Desktop with Linux containers), in PowerShell:

```powershell
$PW = [guid]::NewGuid().ToString('N')
docker run -d --name amemo-db --restart unless-stopped `
  -e POSTGRES_USER=amemo -e POSTGRES_PASSWORD=$PW -e POSTGRES_DB=amemo `
  -p 127.0.0.1:5435:5432 -v amemo-pg:/var/lib/postgresql `
  pgvector/pgvector:0.8.1-pg18
do { Start-Sleep 1; docker exec amemo-db pg_isready -h 127.0.0.1 -U amemo -d amemo } until ($LASTEXITCODE -eq 0)
```

If port 5435 is taken, pick another free one. The `amemo` user is a superuser inside the container, so skip
[Role and database](#role-and-database). The connection string is
`postgresql://amemo:$PW@127.0.0.1:5435/amemo`.

### C. Native install

**Debian, Ubuntu, WSL** (with `sudo`):

```bash
sudo apt-get update
sudo apt-get install -y postgresql-common ca-certificates
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y     # the PostgreSQL project's own repository
sudo apt-get install -y postgresql-18 postgresql-18-pgvector
pg_lsclusters                                                      # the line "18 main" and its port
```

If there is no `18 main` line (some systems turn off the automatic cluster), create it with
`sudo pg_createcluster 18 main --start`. If it is `down`, start it with `sudo pg_ctlcluster 18 main start` (works
with and without systemd; in WSL without systemd, repeat it after each restart of WSL). Note its port: it is 5432,
or 5433 and up when another PostgreSQL already holds 5432. Superuser commands are `sudo -u postgres psql -p PORT`.

**Other Linux distributions:** use the PostgreSQL repository for the distribution
(<https://www.postgresql.org/download/linux/>), packages `postgresql18-server` and `pgvector_18` on Fedora and
RHEL, `postgresql` and `pgvector` on Arch, then initialise and start the server as that page says.

**macOS** (with Homebrew; if `brew` is missing, ask the user and install it from <https://brew.sh>):

```bash
brew install postgresql@18 pgvector
brew services start postgresql@18
export PATH="$(brew --prefix postgresql@18)/bin:$PATH"
```

`postgresql@18` is keg-only: add that `export PATH=…` line to the user's shell profile (`~/.zprofile` for zsh) so
`psql` and `pg_dump` stay on PATH. The server listens on 5432; if another PostgreSQL already holds that port, set
`port` in `$(brew --prefix)/var/postgresql@18/postgresql.conf` and restart the service. The superuser is the
current macOS user: `psql -d postgres`.

**Windows** (both parts need administrator rights; ask the user first):

1. PostgreSQL 18 from the EDB installer, through winget (the same installer as on
   <https://www.postgresql.org/download/windows/>):

   ```powershell
   $SUPER = [guid]::NewGuid().ToString('N')     # password of the superuser postgres; keep it for this session
   winget install -e --id PostgreSQL.PostgreSQL.18 --override "--mode unattended --unattendedmodeui minimal --superpassword $SUPER --serverport 5432 --disable-components stackbuilder"
   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" --version
   ```

   It goes to `C:\Program Files\PostgreSQL\18` and runs as the Windows service `postgresql-x64-18`. If another
   PostgreSQL holds port 5432, pass another `--serverport`. If PostgreSQL 16 or newer is already installed, reuse it
   (ask the user for its `postgres` password) and go on with pgvector.

2. pgvector has no official Windows build: build it with the Visual Studio C++ build tools (a download of about
   2–3 GB; skip the install if Visual Studio with C++ is already there):

   ```powershell
   winget install -e --id Microsoft.VisualStudio.2022.BuildTools --override "--quiet --wait --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
   ```

   Then in an elevated `cmd.exe` (`vcvars64.bat` sets up the compiler; with full Visual Studio, `vswhere.exe
   -latest -property installationPath` in `C:\Program Files (x86)\Microsoft Visual Studio\Installer` gives the
   folder to use instead of `…\2022\BuildTools`):

   ```bat
   call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
   set "PGROOT=C:\Program Files\PostgreSQL\18"
   cd /d %TEMP%
   curl.exe -fsSL -o pgvector.zip https://github.com/pgvector/pgvector/archive/refs/tags/v0.8.1.zip
   tar -xf pgvector.zip
   cd pgvector-0.8.1
   nmake /F Makefile.win
   nmake /F Makefile.win install
   ```

Superuser commands are `& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -h 127.0.0.1 -U postgres` after
`$env:PGPASSWORD = $SUPER`.

### Role and database

For options A and C. As a superuser, with your generated password:

```sql
CREATE ROLE amemo LOGIN CREATEDB PASSWORD 'GENERATED_PASSWORD';
CREATE DATABASE amemo OWNER amemo;
\c amemo
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS btree_gist;
```

amemo's migrations need both extensions, and only a superuser can create `vector`. `CREATEDB` lets
`amemo backup verify` restore a backup into a throwaway database. On a server installed in option C, also run
`\c template1` and `CREATE EXTENSION IF NOT EXISTS vector;` so that throwaway database gets the extension too.
Skip that on a server other programs share: there `amemo backup create` works, but `amemo backup verify` can't
create `vector` in its throwaway database. If the role or the database already exists, don't drop it: ask the
user whether it is from an earlier amemo install, and reuse it.

On Windows, pipe the same SQL into psql (on a server other programs share, leave out the last two lines):

```powershell
@'
CREATE ROLE amemo LOGIN CREATEDB PASSWORD 'GENERATED_PASSWORD';
CREATE DATABASE amemo OWNER amemo;
\c amemo
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS btree_gist;
\c template1
CREATE EXTENSION IF NOT EXISTS vector;
'@ | & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -h 127.0.0.1 -U postgres -v ON_ERROR_STOP=1
```

The connection string is `postgresql://amemo:GENERATED_PASSWORD@127.0.0.1:PORT/amemo`.

## 4. Install amemo

Use uv: it brings its own Python, so the system Python doesn't matter.

```bash
command -v uv || curl -LsSf https://astral.sh/uv/install.sh | sh     # installs into ~/.local/bin, no sudo
uv tool install --python 3.12 'amemo[web]'
amemo --version
```

- `[web]` adds the web UI at `/ui`. Exact and full-text search work out of the box.
- Local semantic search (by meaning, across languages) is optional: the `[embed]` extra and a multilingual model of
  about 250 MB. Ask the user. If they want it, install `'amemo[web,embed]'` instead, and after step 5 ask them to
  run `amemo embed enable` in their own terminal, outside your session: only a person can turn it on (from an agent
  it exits with code 2). It asks before downloading the model, embeds every record and switches the channel on;
  `amemo embed status` (you may run it) shows the result. Otherwise leave it out.
- If `amemo` is not found, run `uv tool update-shell` and open a new shell, or call `~/.local/bin/amemo`.
- With pipx instead of uv: `pipx install 'amemo[web]'` (needs Python 3.11 or newer).

**Windows** (PowerShell, no administrator rights):

```powershell
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  powershell -NoProfile -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
uv tool install --python 3.12 "amemo[web]"
amemo --version
```

The command is `%USERPROFILE%\.local\bin\amemo.exe`; `uv tool update-shell` puts that folder on PATH for new shells.

## 5. Create the base

```bash
amemo init --dsn 'postgresql://amemo:GENERATED_PASSWORD@127.0.0.1:PORT/amemo'
```

This applies the migrations, creates the object store (`~/.local/share/amemo/objects`) and saves the connection
string to `~/.config/amemo/amemo.toml` with mode `0600`. If that file already existed, `init` leaves it alone and
says so: then set the `dsn = "…"` line in it yourself, after asking the user if it pointed to another database.
On Windows the same paths are under `%USERPROFILE%` (`%USERPROFILE%\.config\amemo\amemo.toml`), a folder only the
user can read; `HOME` doesn't matter there.

Then ask the user two questions:

- **Where are the documents amemo should cite?** Add the folder to `amemo.toml` as `docs = "/absolute/path"`
  (create it if they want a new one, for example `~/amemo-docs`). On Windows write it in single quotes, where a
  backslash is just a character: `docs = 'C:\Users\NAME\amemo-docs'`. In WSL, Windows folders are under
  `/mnt/c/Users/NAME/…`.
- **Are there scanned PDFs?** If yes, OCR needs language data: `amemo ocr install eng rus` with their languages
  as Tesseract codes (`eng`, `rus`, `deu`, …). Only a person may change this: amemo refuses the command from an
  agent's shell, so give it to the user to run in their own terminal, outside the agent.

## 6. Connect the agents

For each agent present in the environment where amemo is installed:

```bash
amemo install claude-code      # Claude Code: MCP server, hooks and skills
amemo install codex            # Codex CLI: MCP server, skills and a block in AGENTS.md
```

`--dry-run` shows the changes first. The installer edits only its own entries and keeps a copy of each file it
changes (`<file>.amemo-backup`). Restart the agent afterwards so it loads the MCP server.

On native Windows the commands are the same. The hooks are written so that no shell is involved: for Claude Code
as a program with arguments (they work with Git Bash and with PowerShell alike), for Codex as a `cmd.exe` line.

**Agent on Windows, amemo in WSL** (the second choice under WSL2 in step 2): register only the MCP server, with
the full path from `wsl -d Ubuntu -- bash -lc 'command -v amemo'`:

```powershell
claude mcp add --scope user amemo -- wsl.exe -d Ubuntu -- /home/USER/.local/bin/amemo mcp --agent model:claude-code
```

For Codex on Windows, add this to `%USERPROFILE%\.codex\config.toml`:

```toml
[mcp_servers.amemo]
command = "wsl.exe"
args = ["-d", "Ubuntu", "--", "/home/USER/.local/bin/amemo", "mcp", "--agent", "model:codex"]
```

Hooks and skills need the agent inside WSL; tell the user that this setup gives the tools but not the automatic
memory hooks.

## 7. Check

```bash
amemo doctor
```

Every line must be `ok` or a warning you can explain; fix each `FAIL` line using its hint and run it again. A
warning that semantic search is unavailable is expected unless the user turned it on (see step 4). Then try the service:

```bash
amemo serve &                                   # http://127.0.0.1:8767; --port changes the port
curl -fsS http://127.0.0.1:8767/health
```

On Windows, in PowerShell (`curl.exe`, not the `curl` alias of PowerShell):

```powershell
$service = Start-Process amemo -ArgumentList serve -WindowStyle Hidden -PassThru
Start-Sleep 5
curl.exe -fsS http://127.0.0.1:8767/health
Stop-Process $service                           # unless the user wants it running
```

Open <http://127.0.0.1:8767/ui/> (from WSL it opens in a Windows browser too). Stop the service afterwards unless
the user wants it running.

Backups (`amemo backup create`, `amemo backup verify`) need the PostgreSQL 18 client (`pg_dump`, `pg_restore`).
Option C has it; with option B, install `postgresql-client-18` from the same PostgreSQL repository on Linux, or
`brew install postgresql@18` on macOS. On Debian and Ubuntu, `pg_dump` in PATH is a wrapper that may pick an older
installed version, so point amemo at version 18: add `export AMEMO_PG_BIN=/usr/lib/postgresql/18/bin` to the
user's `~/.profile`. Check with `amemo backup create`: it refuses a client older than 18. On Windows the EDB install
has it: `setx AMEMO_PG_BIN "C:\Program Files\PostgreSQL\18\bin"` for new shells, and the same in
`$env:AMEMO_PG_BIN` for the current one.

## 8. Report

Tell the user, briefly:

- where PostgreSQL runs (Docker container, system service or their server), its port, the role and the database
  (not the password: it is in `~/.config/amemo/amemo.toml`, on Windows under `%USERPROFILE%`);
- where the config, the object store and the documents folder are;
- which agents are connected, and that they need a restart;
- how to open the web UI: `amemo serve`, then <http://127.0.0.1:8767/ui/>;
- the last `amemo doctor` output, and anything you skipped and why.

To undo: `amemo uninstall claude-code` (or `codex`) and `uv tool uninstall amemo`. Remove the database, the
container or the data only if the user asks for it explicitly.
