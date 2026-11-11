# amemo for Windows (Tauri 2)

The desktop app from the [installer spec](../docs/superpowers/specs/2026-11-10-amemo-desktop-installer-design.md):
one program that is the installer wizard, the amemo window and the tray icon.

- **First start — the wizard** (`web/src/setup`, built into `web/dist-setup`; Rust side — `src-tauri/src/setup.rs`):
  it downloads the runtime and the semantic search model of this version from the GitHub release (resumes a broken
  download, checks SHA-256), unpacks the runtime into `runtime\<version>` and runs `amemo setup --progress` from it —
  PostgreSQL in the chosen data folder, the base, semantic search, OCR languages, agents. The wizard checks that
  PostgreSQL can open the data folder (8.3 short names for paths outside the ANSI code page) and offers
  `C:\amemo-data` otherwise. "Finish" sets the desktop shortcut and autostart and opens amemo.
- **Claude** (part D6): when the wizard has the Claude app checked, `amemo setup` connects Claude Code directly and
  builds the plugin zip (`Downloads\amemo-plugin.zip`: MCP server, hooks, skills, all through `bin\amemo.exe`). The
  "Plugin" step tells where to upload it (Customize → Plugins → Add → Upload plugin), opens the Claude app and
  shows the file. Once the plugin from the account shows up in Claude Code (`amemo@synced`), the app removes the
  direct install there — at the plugin step, at start and hourly (`amemo install claude-code --unless-synced`).
- **Background** (`src-tauri/src/service.rs`): PostgreSQL (`amemo pg start`) and `amemo serve` run as child processes
  of the app; the window switches to the web UI of the service (`http://127.0.0.1:8767/ui/`) once `/health` answers.
  A service that exits by itself is restarted (more than three times in 10 minutes — an error on the start screen).
  Tray: `Open amemo`, `Pause` / `Resume` (stops and starts the service and PostgreSQL), `Quit`.
- Closing the window hides it — agents keep using amemo; before the wizard is finished, closing quits.
- `--background` — start without a window (autostart at Windows sign-in, enabled by the wizard; `HKCU\…\Run`, no
  administrator rights). `--quit` — stop the running app with its service and PostgreSQL and wait for it (the
  uninstaller does this first, `src-tauri/windows/hooks.nsh`).
- `bin\amemo.exe` (`launcher/`) — the permanent path to amemo for agents and the terminal: it runs amemo of the
  current runtime (`runtime\current`) with the same arguments, input, output and exit code.
- A second start (desktop or Start menu shortcut) only brings the window forward (single-instance plugin); window
  size and position are remembered.
- The NSIS installer installs for the current user into `%LOCALAPPDATA%\amemo` — no administrator rights, no UAC;
  WebView2 comes from the bootstrapper when Windows lacks it.
- **Updates** (`src-tauri/src/update.rs`, `upgrade.rs`): at start and every 6 hours the app reads
  `releases/download/updates/latest.json` (`latest-pre.json` for a pre-release app) and installs a newer version at
  once (NSIS passive, the app restarts with the same arguments). The new version then moves amemo to its runtime:
  `amemo backup create`, a copy of the cluster folder and `amemo.toml`, `amemo setup` with the new runtime
  (migrations), start; if the service does not come up, the copy is put back and the previous runtime runs. Tray:
  `Update automatically`.
- **Uninstall** stops the background, removes the Claude Code and Codex connections, the runtime, logs and state;
  the data folder and `amemo.toml` stay.
- Commands of the app are allowed to its own pages only (`capabilities/main.json`, `build.rs`); the amemo web UI on
  `http://127.0.0.1:*` may use window commands only (`capabilities/service.json`) — it draws the window buttons in its
  top bar (`web/src/app/shell/WindowControls.tsx`).

Releases with the runtime attached and the update manifests (D8) come next.
Until D8 a release has no runtime to download: CI serves the runtime of the branch from a local server
(`AMEMO_RELEASE_BASE`).

## Build

CI builds it on every change (`.github/workflows/desktop.yml`): icons from `web/public/favicon.svg`, the version
from `amemo/__init__.py` (`python tools/release.py semver`, Tauri needs semver), `tauri build` (its
`beforeBuildCommand` builds the wizard pages and the launcher). Then, with the runtime and the model built by
`runtime.yml` for the same branch: a silent install, the wizard install without a window
(`amemo.exe --setup-unattended choices.json`, a data folder with Cyrillic letters), a background start until
`/health` answers, the launcher, a second start, `--quit` and a silent uninstall. Locally, with Rust and Node on
Windows:

```powershell
cd ..\web; npm ci; cd ..\desktop
npm ci
npx tauri icon ../web/public/favicon.svg -o src-tauri/icons
npx tauri build
```

The wizard pages alone run in a browser with a mock of the app (`cd web; npm run dev:setup`, parameters in
`web/src/setup/mock.ts`).

## Update signing key (repository owner, once)

Updates must be signed with a Tauri key pair. The public key of the pair is in `plugins.updater.pubkey` of
`src-tauri/tauri.conf.json`. The private key and its password belong in the repository secrets
`TAURI_SIGNING_PRIVATE_KEY` and `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`; until they are set, CI signs with a throwaway
key per run, which checks the signing step but is useless for releases.

Keep the private key outside the repository: losing it means installed apps can no longer be updated. A new pair
(`npx tauri signer generate -w amemo-updater.key`) replaces both the secrets and the public key, and apps installed
with the old public key will not accept updates signed with the new one.
