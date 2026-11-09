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
| `agent` | — | A real MCP session against `amem mcp`: `amem_search` → `amem_get` → `amem_helpful`, drawn as a terminal |

## Retaking the screenshots

Nothing heavy runs locally: the `readme-shots` workflow seeds each sample into a fresh PostgreSQL, starts
the service, records the MCP session (`tools/readme_agent_session.py`) and shoots the screens with
`web/tools/readme-shots.mjs`. It runs on pull requests that touch the samples or the scripts, and by hand:

```bash
gh workflow run readme-shots --ref <branch>
gh run download <run-id> -n readme-shots-en -D docs/assets/readme/en
gh run download <run-id> -n readme-shots-ru -D docs/assets/readme/ru
```

Only the samples are shot: no real bases, paths, or names of people and companies.
