# Workspace → database migration plan

This document tracks **what can leave `boards/<id>/workspace/`** and **where it lives in the relational database**, without storing large PNG blobs in the database.

---

## What is `workspace/frames/house/`?

**“House frame”** is a **single shared 9-slice decorative border** (ornate frame) that the compositor can paste **around functional panels** so they look consistent.

On disk it is **not one PNG** — it is:

- **Eight small PNG sprites** under `workspace/frames/house/`: `corner_tl.png`, `corner_tr.png`, …, `edge_top.png`, … (see `pipeline/boardfactory/frames.py`).
- A **`frame.json`** sidecar next to them with `FrameMeta`: ring thickness in pixels, where the frame was cut from (`source_kind` / `source_id` / `source_size`), timestamps, etc.

At composite time the frame is **reassembled at the panel’s target size** by pasting corners and **tiling** edges so pixel art stays crisp (scaling a single full-frame image would blur the grid).

**Scope:** One active house frame **per board**; per-panel frame overrides are out of scope today. Enable/disable and high-level options still live in the board **catalog** `frame` block (`board_games.frame_json`).

---

## Goal: move `palette.json` and `.meta.json` into the DB

### 1) `workspace/style/palette.json` (and `palette.gpl`)

**Today:** `style_lock` writes JSON + GPL text to fixed paths; `draw_cell`, `states`, etc. open `config.STYLE_DIR / "palette.json"` by path.

**Store in DB (suggested shape):**

| Option | Table / column | Notes |
|--------|----------------|--------|
| **A (minimal)** | `board_games` add nullable `palette_json TEXT`, `palette_gpl_text TEXT`, `style_lock_updated_ms BIGINT` | One row per board already; keeps style data next to `style_prompt` / `generation_json`. |
| **B (normalized)** | New `board_style_locks(board_id PK FK → board_games, palette_json, gpl_text, updated_ms)` | Clearer if style-lock grows (e.g. multiple profiles later). |

**Pipeline / app work:**

1. **Write path:** After `do_style_lock`, persist the same dict / GPL string that today goes to disk into the DB columns (via `services` + `persist` or a small `board_style` service).
2. **Read path:** Either  
   - **2a)** On job start / `scope_board`, **materialize** `palette.json` (and optionally `.gpl`) from DB into a temp dir or `STYLE_DIR` for compatibility, *or*  
   - **2b)** Refactor pipeline steps to accept **in-memory** palette (load JSON from DB, pass into cleanup / draw — larger change, fewer temp files).
3. **Migration:** One-shot job: for each board with `palette.json` on disk and missing DB fields, read file → upsert DB → then delete disk file (behind a feature flag if desired).
4. **Git / ignore:** Once stable, stop tracking `palette.json` / `.gpl` if they are no longer committed; `.gitignore` already allows forcing track — align with “DB is source of truth”.

**Risk:** Anything that shells out or assumes a literal path must be updated or given a thin sync layer.

---

### 2) `workspace/history/.../*.meta.json` (history sidecars)

**Today:** `push_to_history()` writes `<basename>.meta.json` beside each history PNG (`operation`, `prompt`, `ts_ms`, `seq`, optional `extras`). The same payload is already sent to SQLite as **`asset_versions.meta_json`** on `history_push` (`asset_index.on_asset_event`).

**Store in DB (canonical):**

- **`asset_versions.meta_json`** — already the right column; treat it as **source of truth** for the fields today duplicated on disk.

**Work:**

1. **`read_meta()`** (`assets.py`): resolve `board_id` + `rel_path` (or basename) → load `meta_json` from `asset_versions` **first**; fall back to `.meta.json` on disk for legacy rows missing DB meta.
2. **`push_to_history()`**: stop writing `.meta.json` once backfill proves `meta_json` is populated for all new pushes (listener must remain reliable).
3. **Backfill:** SQL or script: for each history PNG with a sidecar file and null/empty `meta_json`, read JSON from disk → update row → delete sidecar.
4. **`asset_index.backfill_board`:** Optionally enrich rows from sidecars where `meta_json` is empty.

**Risk:** Any code that reads sidecars directly (grep `.meta.json`) must go through `read_meta` or DB.

---

## Consolidating `live/` + `history/` — two designs

**Today:** Each cell keeps a **fixed-path “live” PNG** (`workspace/live/...`) that is a **copy** of one history file; `promote()` uses `shutil.copy2` from `history/` → `live/`. “Which history entry is live?” is inferred by **byte comparison** in `list_history()`, not stored in SQLite.

**Goal:** One canonical tree of versioned PNGs on disk, and the **database names which version is live** for each `(board_id, category, asset_id)` — no duplicate bytes in `live/` (unless we explicitly keep a cache; see Design 2).

### Design 1 — Single on-disk tree + DB “live pointer” (**recommended**)

- **On disk:** Keep versioned files under the existing **`history/<category>/<asset_id>/`** layout (or rename to a neutral `versions/` later — same idea).
- **In DB:** Add a **live pointer** per cell, for example:
  - **`asset_live`** table: `(board_id, category, asset_id)` as primary or unique key → `asset_version_id` FK to `asset_versions.id` (or store `rel_path` that must match `asset_versions.rel_path`).
- **Resolver:** “Path for the live image for compositor / export / HTTP” = join pointer → `asset_versions` row → open file at `workspace/<rel_path>` (still under board root). **No second copy** in `live/`.
- **Work:** Replace every `live_path()` consumer with a resolver that reads SQLite (with caching inside `scope_board` if needed). Migrate existing boards: set pointer to the history row whose bytes match current `live/*.png`, then delete `live/` files (or one-time copy into history if missing).

**Pros:** No duplicate PNGs; clear semantics; aligns with `asset_versions` you already index.  
**Cons:** All hot paths must go through DB-backed resolution (touched modules: `assets.py`, compositor, export, draw_cell promotion, static asset routes, tests).

### Design 2 — DB pointer + `live/` as optional **materialized cache**

- Same DB pointer as Design 1, but a job or `promote()` **refreshes** `live/<...>.png` from the pointed history file for fast `FileResponse` / dumb PIL `open(live_path)`.

**Pros:** Fewer refactors short term.  
**Cons:** Still duplicates bytes; cache invalidation rules.

**Recommendation:** **Design 1** for the long-term shape; use a thin compatibility shim only if you need a phased rollout.

---

## Deprecate `candidates/`, `cleaned/`, `approved/`

**What they are:** Legacy **CLI-era** staging directories (`config.CANDIDATES_DIR`, `CLEANED_DIR`, `APPROVED_DIR`). The web app uses **`history/` + `live/`** only; `ensure_dirs()` does **not** create these dirs anymore.

**Today’s code:** Startup / migration still **reads** them to **seed** `live` + `history` from `approved/` (`seed_from_legacy_approved`) and then **purge** empty legacy trees.

**Deprecation plan:**

1. **Announce a cutoff** (release note): repos must run the app once on an old tree so migration runs, *or* run a documented one-shot migration command.
2. **Remove or gate** `seed_from_legacy_approved` / purge paths behind `if legacy_dirs_exist()` once metrics show zero need, or keep read-only migration for one more major version then delete.
3. **Delete** `CANDIDATES_DIR` / `CLEANED_DIR` / `APPROVED_DIR` from `config._path_for` and all call sites **after** migration code is removed (grep `APPROVED_DIR`, `CANDIDATES_DIR`, `CLEANED_DIR`).
4. **Docs / `.gitignore`:** Drop references to legacy dirs; keep ignores harmless for old checkouts until dirs are gone.

---

## Out of scope for this plan (but related)

| Artifact | Recommendation |
|----------|------------------|
| `style_sheet.png`, `palette_swatch.png` | Keep as **files** or object storage; store **hash + optional relpath** in DB if needed. |
| `frames/house/*.png` + `frame.json` | Same pattern as palette: **`frame.json` → DB** (e.g. column `house_frame_meta_json` or reuse/extend `frame_json` + blob paths table); **slice PNGs** stay files until a blob store exists. |
| `live/` vs `history/` | **Covered above** — implement **Design 1** (`asset_live` + resolver); **Design 2** only if you need a transitional cache. |

---

## Suggested implementation order

1. **`.meta.json` → `asset_versions.meta_json`** (smallest win; data often duplicated already).  
2. **`palette.json` / `.gpl` → `board_games`** (or `board_style_locks`).  
3. **Legacy dirs:** finish **candidates / cleaned / approved** deprecation (migrate → remove config paths + dead code).  
4. **`live/` + `history/`:** add **`asset_live`** (or equivalent) + **resolver**; migrate pointers from current `live/` bytes; **remove `live/`** writes and eventually the directory convention.  
5. Remove disk writes / migrate old palette & meta files / adjust `.gitignore` and docs.  
6. Later: `frame.json` for house frame; then PNG blob storage strategy (S3, etc.).

---

## Verification

- `pytest app/tests/` after each phase.  
- Manual: style lock → generate → history strip shows correct operation/prompt without sidecars.  
- Manual: cleanup / regen still reads palette after DB-only style lock.  
- After **live pointer** work: compositor + export + board UI show the same pixels as before migration; no reliance on `live/` once cut over.  
- After **legacy dir** removal: opening an old repo without `approved/` still passes tests; one migrated sample board still loads.
