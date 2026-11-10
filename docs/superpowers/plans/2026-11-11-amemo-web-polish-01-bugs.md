# amemo web — polish, part 1: bugs with a known cause

**Goal:** fix nine interface bugs found while using the alpha. Each cause was found by reading the code; each fix
comes with a test that would have caught it.

**Rule of the period:** no new features; finish what exists.

| # | Bug | Cause | Fix | Test |
|---|---|---|---|---|
| 1 | A record dragged onto a folder is back without a folder after a reload | The move waited out the 6 s undo window; on unload the queue flushed it without `keepalive`, and the request was cut | A move is reversible: it is sent at once, and «Отменить» moves the record back to the folder it came from (read from the service before the move) | unit: the move is at the service at once, undo restores; e2e: move, reload at once, the record is in the folder; undo puts it back |
| 2 | The record list stops at 50 rows | `/records` was asked once with the default `limit` | Pages by `cursor` (`limit` 200), loaded on scroll and by «Показать ещё»; the count is the service's `total` | unit: 260 records — every row arrives, then no «Показать ещё» |
| 3 | `@object` in quick write rarely binds | Objects were taken from those first 50 records | Each `@word` is looked up with the entity search (`/search?target=entity`), the best hit binds | unit: `@word` binds a record to an object found by search |
| 4 | `⌘` on Windows and Linux | Hard-coded in the search field, the settings command and the editor hints | `ui/platform.ts`: `⌘` on macOS, `Ctrl` elsewhere; i18n strings use `{{mod}}` | unit: not on macOS — `Ctrl` |
| 5 | The graph is dark in the light theme | The sky tokens were dark in both themes | Light values for `--sky`, `--sky-2`, `--sky-ink`, `--sky-muted` in the light theme; the dark theme keeps the night sky | e2e: sky lightness in each theme |
| 6 | Links are invisible in 3D | A muted colour at opacity 0.35 | Higher opacity; the selected star's links in the ink colour and thicker; repainted on selection and theme change | — (WebGL, checked by eye) |
| 7 | The record source has no `about` and `tags` when they are empty | Only non-empty keys were written | Atoms always get both keys; empty values survive the round trip | unit: round trip of a bare note |
| 8 | Settings say «person:…» | The raw agent id was shown | `agentName()` | — |
| 9 | Long names break the layout | No wrapping or clamping | Record title wraps anywhere; pills clamp with an ellipsis and a `title`; list rows and search hits clamp to two lines; the kind drawer scrolls only vertically | — (CSS) |

Mocks follow the service: `/records` pages by `limit` and `cursor`; `/search?target=entity` searches every entity.

Checks run in CI only.
