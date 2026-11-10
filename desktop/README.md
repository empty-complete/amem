# amemo for Windows (Tauri 2)

The desktop app from the [installer spec](../docs/superpowers/specs/2026-11-10-amemo-desktop-installer-design.md):
one program that is the installer wizard, the amemo window and the tray icon. This folder is part **D3** — the
skeleton:

- a window without the system frame and its own title bar (`ui/`, `decorations: false`); closing the window hides it,
  the tray icon (`Open amemo`, `Pause`, `Quit`) keeps amemo running for agents;
- a second start (desktop or Start menu shortcut) only brings the window forward (single-instance plugin);
- `--background` starts without a window (autostart, part D5);
- window size and position are remembered (window-state plugin);
- the NSIS installer installs for the current user into `%LOCALAPPDATA%` — no administrator rights, no UAC;
  WebView2 comes from the bootstrapper when Windows lacks it;
- the updater checks `releases/latest/download/latest.json` at start (installing updates is part D7);
- `capabilities/service.json` lets the amemo web UI on `http://127.0.0.1:*` use window commands only.

The wizard (D4), starting PostgreSQL and the service from the runtime (D5), the Claude plugin (D6) and updates (D7)
come next.

## Build

CI builds it on every change (`.github/workflows/desktop.yml`): icons from `web/public/favicon.svg`, the version
from `amemo/__init__.py` (`python tools/release.py semver`, Tauri needs semver), `tauri build`, then a silent install,
a background start, a second start and a silent uninstall. Locally, with Rust and Node on Windows:

```powershell
cd desktop
npm ci
npx tauri icon ../web/public/favicon.svg -o src-tauri/icons
npx tauri dev
```

## Update signing key (repository owner, once)

Updates must be signed with a Tauri key pair. Until the owner creates it, CI signs with a throwaway key per run, which
checks the signing step but is useless for releases.

```powershell
npx tauri signer generate -w amemo-updater.key
```

Put the content of `amemo-updater.key` and its password into the repository secrets `TAURI_SIGNING_PRIVATE_KEY` and
`TAURI_SIGNING_PRIVATE_KEY_PASSWORD`, and the content of `amemo-updater.key.pub` into `plugins.updater.pubkey` of
`src-tauri/tauri.conf.json`. Keep the private key outside the repository: losing it means installed apps can no longer
be updated.
