# README pictures

- `banner-light.svg`, `banner-dark.svg` — the header of `README.md` and `README.ru.md`, drawn by
  `tools/readme_assets.py` in the web UI colours.
- `en/*.png` — screenshots for `README.md`, taken from the real service on the English sample
  `tools/seed_sample_en.py`: a fictional network of four weather stations with a small domain pack
  (`tools/sample_en/pack`).
- `ru/*.png` — screenshots for `README.ru.md`, from the Russian sample `tools/seed_sample.py`.

Every screen has a light (`-light`) and a dark (`-dark`) version, 1600×900; the README picks one by the
GitHub theme with `<picture>`.

| Screen | Page | What it shows |
|---|---|---|
| `sky` | `/` (en) or `/?center=` (ru) | The whole base as a constellation, family filters, folders |
| `record` | `/atom/:ref` | A parameter with its value, body and formula; the PDF page with the quote highlighted |
| `review` | `/review/:itemId` | The queue on the left; the claim, the quote and the neighbourhood; the decision |
| `card` | `/entity/:ref?tab=card` | The entity card: completeness, grouped parameters (known, missing, conflict) |
| `agent` | — | A real MCP session against `amemo mcp`: `amemo_search` → `amemo_get` → `amemo_helpful`, drawn as a terminal |

## Usage GIFs

`en/demo-*.gif` and `ru/demo-*.gif` are short scenes played on the same service and sample by
`web/tools/readme-gifs.mjs`: a 1280×720 Playwright video turned into a GIF with ffmpeg (1200 px wide,
12 fps; the sky 1000 px, 10 fps). A drawn cursor and key badges show clicks and shortcuts. Light theme only.

| Scene | What it shows |
|---|---|
| `write` | <kbd>N</kbd>, one line of text, the kind guessed from it, <kbd>Enter</kbd>, the toast with Undo |
| `source` | Search, the record, the quote highlighted on the PDF page, then the dark theme |
| `review` | The queue from the keyboard: <kbd>J</kbd> to move, <kbd>Y</kbd> to confirm |
| `card` | A required field marked Needed, a value typed in, completeness growing after the undo window |
| `sky` | The constellation laying itself out, arrows to pick a star, <kbd>Enter</kbd> to open its record |

The scenes change the base (a new record, a review decision, a card value), so the workflow runs them after
the screenshots. They come out as the `readme-gifs-<lang>` artifact.

## Retaking the screenshots

Nothing heavy runs locally: the `readme-shots` workflow seeds each sample into a fresh PostgreSQL, starts
the service, records the MCP session (`tools/readme_agent_session.py`) and shoots the screens with
`web/tools/readme-shots.mjs`. It runs on pull requests that touch the samples or the scripts, and by hand:

```bash
gh workflow run readme-shots --ref <branch>
gh run download <run-id> -n readme-shots-en -D docs/assets/readme/en
gh run download <run-id> -n readme-shots-ru -D docs/assets/readme/ru
gh run download <run-id> -n readme-gifs-en -D docs/assets/readme/en
gh run download <run-id> -n readme-gifs-ru -D docs/assets/readme/ru
```

Only the samples are shot: no real bases, paths, or names of people and companies.
