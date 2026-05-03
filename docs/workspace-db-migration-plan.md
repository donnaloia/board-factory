# Workspace ↔ database — decisions log

This doc was originally a **plan** for moving more of `workspace/` into
the database. The migrations it proposed have all been performed (some
exactly, some inverted). It is kept here as a **historical record** of
what moved, what didn't, and why.

For the current shape, see [diagrams/data-model.md](diagrams/data-model.md)
and [architecture.md](architecture.md#data-model).

---

## What moved into the database

### `workspace/history/.../*.meta.json` → `asset_versions.meta_json`

**Done.** Every history push fires a `history_push` event on
`pipeline/boardfactory/assets.py`; the web app registers
`services.asset_index.on_asset_event` at startup, which inserts the
`(board_id, category, asset_id, basename, rel_path, sha256, ts_ms,
meta_json)` row.

Sidecar `.meta.json` files are **no longer written** by `push_to_history`
for new entries. Older sidecars on disk are still tolerated by
`asset_index.backfill_board`, which reads them when the DB row is missing.

### Style-lock palette → `board_games.palette_json` / `palette_gpl_text`

**Partially done.** The palette is now persisted to **both** disk and DB:

- `workspace/style/palette.{json,gpl}` is what the pipeline reads at
  runtime (`palette.load_palette`).
- `board_games.palette_json` / `palette_gpl_text` /
  `style_lock_updated_ms` is the DB copy. `services.workspace_palette`
  re-materializes the DB copy onto disk at job start when needed (e.g.
  on a fresh clone).

The pipeline was deliberately **not** refactored to load the palette
from the DB directly — keeping disk as canonical means the pipeline
package stays usable without the web app and without an active SQL
connection.

### Catalog body → `board_games.body_json`

**Done, then redone.** The catalog spec moved through three shapes:

1. `board_catalogs.body_json` (revision 0003): a single JSON blob keyed
   by `board_id`.
2. `board_games` + three child tables (revision 0004): a normalized
   layout with `board_space_layout_rows`, `board_space_designs`, and
   `board_feature_panels`, plus per-field scalar columns on
   `board_games`. `board_catalogs` was kept in sync as a transitional
   mirror.
3. `board_games.body_json` (revision 0011): collapsed back to a single
   Pydantic-validated JSON blob; child tables and the
   `board_catalogs` mirror were dropped.

The collapse happened because the catalog is an **aggregate root** with
strong cross-field invariants, the UI always edits the whole aggregate,
and there were never any cross-board sub-entity queries. The normalized
layout added schema-evolution cost without unlocking any granular query.
See [architecture.md → tradeoffs](architecture.md#tradeoffs-that-were-considered)
for the full reasoning.

---

## What did **not** move into the database

### `workspace/live/<cat>/<id>.png` — kept on disk, **canonical**

**Reverted.** Revision 0006 added an `asset_live` table that pointed at
the history row currently considered "live" for each cell. Revision
0009 dropped it.

The reason: the `live/` PNG is what gets served to browsers and what a
fresh clone needs to reproduce the board grid. Tracking it in git makes
"clone the repo, see the same board" trivial, and removes a class of
bugs where the pointer in the DB and the bytes on disk disagreed.
"Which history row is live?" is now detected at read time by SHA
equality in `assets.list_history`.

### Generated PNGs — kept on disk

`history/*.png`, `style_sheet.png`, `palette_swatch.png`,
`preview/board_idle.png` and friends, and the engine `export/` are all
files. The DB stores **rows** (index + metadata); bytes stay on the
filesystem so `pg_dump` stays small and Postgres isn't asked to be a
blob store.

### `workspace/frames/house/*.png` and `frame.json` — kept on disk

The frame is enabled / disabled per board through the catalog's `frame`
block (which lives in `body_json`). The actual 9-slice tiles + their
`frame.json` sidecar stay under `workspace/frames/house/` so the
compositor can read them with `PIL.Image.open`.

---

## What was removed entirely

### `candidates/` / `cleaned/` / `approved/` legacy CLI dirs

The pre-web-app CLI staged generations in three folders before approval.
The web app uses `live/` + `history/` only. The migration code that
seeded `live/` from old `approved/` trees was removed once all known
checkouts had been migrated. The defensive `.gitignore` rules that used
to hide the old layout were dropped along with `workspace/.costs.jsonl`
(see below).

### `workspace/` flat tree (incl. `.costs.jsonl` ledger)

The pre-multi-board layout kept everything in a single top-level
`workspace/` directory and recorded provider costs to
`workspace/.costs.jsonl`. Both moved into per-board state long ago
(`data/boards/<id>/workspace/`) and SQL (`cost_entries`) respectively.
The directory and the JSONL file were deleted; the `.gitignore` no
longer carries rules for them.

---

## Suggested next moves (still open)

| Artifact | Possible next step |
|----------|--------------------|
| `style_sheet.png`, `palette_swatch.png` | Optional: store SHA + relpath in DB for cache busting; bytes still on disk. |
| `frames/house/*.png` + `frame.json` | Same shape as palette: bytes on disk, optional DB-side metadata. Only worth doing if multi-frame libraries become a feature. |
| Object storage for PNGs | A second-stage move worth considering only if multi-VM deployment becomes a goal. The current single-VM deployment plan keeps PNGs on local disk. |

---

## Verification (still relevant for any future migration)

- `pytest app/tests/` after each phase.
- Style lock → generate → history strip shows correct operation/prompt without sidecars.
- Cleanup / regen still reads palette after DB-only style lock.
- Compositor + export + board UI show the same pixels as before; no reliance on a directory that the migration was supposed to retire.
