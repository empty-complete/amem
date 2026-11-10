# amemo web — polish, part 2: writing, editing and the editor

**Goal:** a person can fix any record, write a new one quickly with suggestions, and work with text the way a
Markdown notes app does. No new features — the existing editor, quick write and history are finished.

**Decision (owner, 11.11):** a person may edit any record, including records written by models and entities. An
edit is a new revision under the person's name; history stays. Editing a model's record **keeps its status** — a
small fix does not confirm the content; confirming goes through Review. The person's own records stay verified at
once, as before.

## Order and PRs

| PR | Items | What |
|---|---|---|
| A | Edit any record | Service: `check._decide` keeps the status when a person revises a record whose current revision is a model's; the review item follows the kept status (`semantic` for a draft), stale items close as before. Web: the pencil on every record and entity; «Поставить на проверку» and «Записать своё рядом» move to «Ещё»; a line in the editor says the status stays. Mocks accept such edits and keep the status |
| B | Suggestions | Quick write gets the body editor with `[[`, `@`, `#` suggestions (records and objects by search, tags from the tag vocabulary with counts); the tags field gets the same suggestions as «о чём»; the kind chip says why the kind was inferred |
| C | Note from an object, history | «Добавить заметку» on an object opens the editor with the title, the object and the kind instead of writing a bare title; an unfinished note stays a draft. History rows get «Сравнить с текущей» and «Вернуть эту ревизию» (the old body as a new revision) |
| D | One surface | «Суть» becomes a property row; reading and editing share one layout; a context menu with formatting on a selection |
| E | Live preview | Markup hidden except on the cursor line; formulas and links rendered (CodeMirror 6 decorations) |

Each PR: service tests where the service changes, unit and e2e on mocks, checks in CI only.

## PR A — tests

- Service: a person's edit of a model draft keeps `draft`, moves the `semantic` question to the new revision and
  closes the old one; a record under review stays under review; a person's edit of their own record stays
  verified; a person's edit of a verified model record stays verified with no queue item (existing test).
- Web: the editor opens on a model's record with the status note; «Поставить на проверку» is in «Ещё»; e2e — edit
  a model's record title, a new revision, the status unchanged.
