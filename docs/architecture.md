# Architecture

Board Factory is built around three observations about pixel-art board games that don't hold for generic asset pipelines:

1. **The board layout is a known grid, not a thing to be discovered.** AI vision models are unreliable at detecting dense small tiles like a Monopoly perimeter; arithmetic is reliable. So Board Factory's catalog is declarative — you describe the grid once and the pipeline computes positions.
2. **Style discipline matters more than coverage.** A style-locked palette extracted once at the start and applied to every later step is more important than getting "the right asset" on the first try. The pipeline assumes you'll iterate; it makes iteration cheap.
3. **The centerpiece is in a category of its own.** It's bigger and the most expensive cell to land. **Generation is split:** the **first** centerpiece (nothing live yet) uses **img2img** from the mockup bbox crop to anchor the sketch; **every regeneration** after that uses **text-to-image** at the catalog target size with the style sheet — same modality as perimeter spaces, not mockup-cropped img2img like functional panels.

## Diagrams

- [Backend pipeline — request to art](diagrams/pipeline.md)
- [Data model — relational tables](diagrams/data-model.md)

## Components

```
docker compose
├── postgres              PostgreSQL 16 (app data: users, catalog, jobs, …)
└── board-factory         FastAPI in app/ (port 8473) + boardfactory pipeline as a library
```

The `**board-factory**` image installs the web app and imports the pipeline from `/repo/pipeline` (bind-mounted in dev). There is no separate "pipeline-only" service: jobs run inside the app process against `data/boards/<id>/` (resolved through the `BoardStore` abstraction).

The whole stack shares the repo: `**board-factory**` mounts `./` as `/repo` so `data/boards/`, `app/`, and `pipeline/` are the same tree you edit on the host. Generation and review write under each board's `workspace/`; the app also keeps relational state in the database (Postgres in Compose by default, or SQLite when configured).

Provider calls are made from the app so the browser drives generation without an extra container hop.

## Layered backend

The backend has four layers; the [pipeline diagram](diagrams/pipeline.md) shows how they fit together. In short:


| Layer                 | What it does                                                                                                                                                                                                                                                               | Files                                     |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| **Routes**            | HTTP entry points. Per-board URLs under `/b/<board_id>/…`. Auth, validation, builds a worker callable, hands it to the runner.                                                                                                                                             | `app/routes/`                             |
| **Job runner**        | One per process. Holds the in-memory job registry, executes worker callables on a thread pool, supports cancel via `threading.Event`, publishes status changes to SSE subscribers, and persists terminal snapshots to `job_runs`.                                          | `app/jobs.py`, `app/services/job_runs.py` |
| **Pipeline adapters** | Plain functions matching the runner's `(job, cancel_event) → cost_usd` shape. They load the catalog, validate the mockup, build the provider, and call the pipeline. Routes bind their parameters via `functools.partial`.                                                 | `app/pipeline_adapters.py`                |
| **Pipeline package**  | The actual image work. `ops.draw_cell` is the atomic generate operation (provider call → cleanup → history push → promote); `ops.orchestrate` loops it for "generate everything missing". `steps/` holds non-per-cell operations (style lock, states, compositor, export). | `pipeline/boardfactory/`                  |


`assets.py` writes PNGs into `history/` and `live/` and **emits a `history_push` event** on every write. The web app registers `services.asset_index.on_asset_event` at startup so each push also lands as an `asset_versions` row in SQL — but the pipeline package itself has no database knowledge.

## Provider abstraction

```
PixelArtProvider (abstract)
├── PixelLabProvider      hosted img2img/generate/inpaint
├── OpenAIImageProvider   OpenAI Images API (when configured)
└── MockProvider          offline placeholders
```

Per-board provider settings live in the catalog's `generation` block (provider, model, quality / preset, palette size). The defaults come from `BOARDFACTORY_PROVIDER` in compose; per-board edits override. To add a new provider (local SDXL, ComfyUI, etc.), implement `PixelArtProvider` in `pipeline/boardfactory/providers/pixel/yourname.py` and add a branch to `factory.get_provider`.

## Pipeline steps

The user-facing pipeline is **eight steps**. Steps 1, 2, and 4–8 each map to a single function in `app/pipeline_adapters.py`; step 3 fans out to three orchestrators that share the same atomic `draw_cell`.


| #   | Step                 | Adapter                                    | Pipeline entry point                                                  | Tools                                                                                                                        |
| --- | -------------------- | ------------------------------------------ | --------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| 1   | Style Lock           | `style`                                    | `steps/style_lock.do_style_lock`                                      | PIL median-cut quantizer                                                                                                     |
| 2   | Catalog              | (loaded by every adapter)                  | `schemas.Catalog.model_validate_json`                                 | Pydantic v2                                                                                                                  |
| 3a  | Generate spaces      | `generate_missing(category="spaces")`      | `ops/orchestrate.generate_missing_spaces` → `ops/draw_cell.draw_cell` | `Provider.generate`                                                                                                          |
| 3b  | Generate panels      | `generate_missing(category="panels")`      | `ops/orchestrate.generate_missing_panels` → `ops/draw_cell.draw_cell` | `Provider.img2img` (with optional `Provider.inpaint` for frame interiors)                                                    |
| 3c  | Generate centerpiece | `generate_missing(category="centerpiece")` | `ops/orchestrate.generate_centerpiece` → `ops/draw_cell.draw_cell`    | First pass (no live asset): `Provider.img2img` from mockup crop. Regenerations: `Provider.generate` (txt2img + style sheet). |
| 3*  | Per-cell regenerate  | `generate_one(category, asset_id, …)`      | `ops/draw_cell.draw_cell` directly                                    | Same as 3a–3c, scoped to one cell                                                                                            |
| 3*  | Re-clean live        | `clean_one(category, asset_id)`            | `assets.reclean_live`                                                 | PIL palette quantize + grid snap                                                                                             |
| 4   | Cleanup              | (inlined into `draw_cell`)                 | `palette.quantize_to_palette` + `geometry.grid_snap`                  | PIL                                                                                                                          |
| 5   | Review               | (HTTP routes)                              | `app/routes/board.py`                                                 | Browser                                                                                                                      |
| 6   | States               | `states`                                   | `steps/states.do_states`                                              | PIL filters (procedural, palette-preserving)                                                                                 |
| 7   | Compositor           | `preview`                                  | `steps/compositor.do_preview`                                         | PIL paste                                                                                                                    |
| 8   | Export               | `export`                                   | `steps/export.do_export`                                              | `shutil.copy` + JSON manifest                                                                                                |


`analyze` is a parallel UI-only adapter that calls GPT-4o vision on the mockup and writes the suggested per-cell prompts back into the catalog blob. It is not part of the numbered pipeline.

## Data model

Single source of truth per concept; no mirrors. See [diagrams/data-model.md](diagrams/data-model.md) for the full ER diagram.


| Concept                                                                                                 | Where it lives                                                                                               | Why there                                                                                                                                                                                                                                                                                                                                                     |
| ------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Catalog spec (project, board_size, style, centerpiece, board_spaces, feature_panels, frame, generation) | `board_games.body_json` (one Pydantic-validated JSON blob per board)                                         | The catalog is an **aggregate root** with strong cross-field invariants (e.g. every space-design id mentioned in `positions` must exist; bbox must be inside the board canvas). One blob lets a `Catalog.model_validate` enforce the whole graph atomically. There are no granular `PATCH /board/<id>/space/<i>` queries — the UI always edits the aggregate. |
| Style-lock palette                                                                                      | `board_games.palette_json` / `palette_gpl_text`, materialized to `workspace/style/palette.json` on job start | Disk is what the pipeline reads (`palette.load_palette`); the DB copy lets a fresh clone re-materialize without re-running style_lock.                                                                                                                                                                                                                        |
| Per-cell history                                                                                        | `asset_versions` rows + `workspace/history/<cat>/<id>/<ts>__<seq>.png` files                                 | Index in DB, bytes on disk. The DB row makes "list history newest-first with provider/prompt metadata" a SQL query instead of a directory scan + sidecar parse.                                                                                                                                                                                               |
| The "live" image for a cell                                                                             | `workspace/live/<cat>/<id>.png`                                                                              | Single canonical file on disk, tracked by git so a fresh clone reproduces the board grid. There is no `asset_live` pointer table — `assets.list_history` detects which history entry matches live by SHA.                                                                                                                                                     |
| Job state (queued / running / done / failed / killed, log, cost)                                        | `job_runs` rows persisted on completion                                                                      | The runner keeps running jobs in memory; only terminal snapshots persist so the tray survives restarts.                                                                                                                                                                                                                                                       |
| Cost ledger                                                                                             | `cost_entries` rows, written by `cost_ledger.record` from inside each adapter                                | Aggregated by `cost_ledger.summary` for the header UI.                                                                                                                                                                                                                                                                                                        |


## Workspace layout (per board)

Per-board files live under the configured **`BoardStore`** root. The default
`LocalBoardStore` resolves to `<BOARDFACTORY_REPO>/data/boards/`; an
`S3BoardStore` would translate the same relative paths into bucket keys
without any caller changes.

```
data/boards/<id>/
  mockup/
    board.png                    source mockup PNG
  workspace/
    style/
      palette.json               shared palette used by every later step
      palette.gpl                same palette, art-tool format
      palette_swatch.png         visual reference of the palette
      style_sheet.png            style reference for generation
    live/<category>/<id>.png     canonical promoted asset per cell (git-tracked)
    history/<category>/<id>/     timestamped PNGs — full version history
                                   <ts>__<seq>.png (+ optional .meta.json sidecar)
    preview/
      board_idle.png             composited board, base state
      board_active.png           composited board, active states on
    logs/run.log                 one line per pipeline run (when enabled)
    frames/house/                optional 9-slice house frame tiles + frame.json
  export/                        engine-ready tiles + board_manifest.json
```

The path layout is the same for every backend; the store decides where
those keys actually land.

## Safety

- API keys are typically set in `docker-compose.yml` or a `.env` file. `make protect-keys` runs `git update-index --skip-worktree` on `docker-compose.yml` so local key edits don't show up in `git status`.
- Per-board files live under `data/boards/<id>/workspace/` and `data/boards/<id>/export/` (overridable via `BOARDFACTORY_BOARDS_DIR`). The app and pipeline both resolve through the same `BoardStore` so they always agree on the root.
- Asset routes resolve files under the board workspace and reject path traversal.
- Per-board ownership lives in `owned_boards`; routes call `deps.ensure_owned_board` before serving anything board-specific.

## Tradeoffs that were considered

**Why not use Aseprite for cleanup?**
Aseprite's CLI quantizer produces marginally better dithering than PIL, but adds an external binary dependency and a license. PIL gets you 90% of the way and works in any container.

**Why provider calls from the web app instead of a separate pipeline worker process?**
Fewer moving parts for interactive flows: batch generation runs in-process via the job runner, and per-cell regenerate/clean clicks need low-latency single-image calls. A subprocess-per-click model would add latency without clear benefit for local dev.

**Why procedural state generation instead of AI?**
Active variants (glow, pulse, flicker) need to look identical to the base except for one specific lighting change. AI generators introduce drift on every call — a "glowing" version often comes back with subtle composition changes that break the alignment. Procedural transforms guarantee pixel-perfect alignment.

**Why one JSON blob for the catalog instead of normalized child tables?**
The catalog is an aggregate root with strong cross-field invariants (every space-design id mentioned in `positions` must exist; bbox must be inside the board canvas; `frame.apply_to_panels` only makes sense if `frame.enabled`). Pydantic enforces the whole graph atomically on every write. There is no use case for a single-cell SQL `UPDATE` — the UI always sends the full edited aggregate. A normalized 5-table layout was tried (revisions 0003–0010) and removed in 0011 because it added schema-evolution cost without unlocking any granular query.

**Why the pipeline emits asset events instead of writing to the DB directly?**
`pipeline/boardfactory/assets.py` knows nothing about the database; it just writes PNGs and emits `history_push` events. The web app registers a listener at startup that mirrors those events into `asset_versions`. This keeps the pipeline package usable on its own (e.g. for a future CLI) and means removing the listener silently degrades the UI without breaking generation.

**Why one in-process job runner instead of Celery / RQ?**
For a single-VM deployment with bursty per-user usage, a broker is overhead. The runner is ~300 lines, persists terminal state to SQL so the tray survives restarts, and dispatches CPU-bound provider calls onto a thread pool. The cost is that in-flight jobs are lost on restart — that's the price of staying single-process and is acceptable for the target deployment.

**Why a `BoardStore` abstraction instead of `Path` everywhere?**
The pipeline writes 30+ files per generation (per-cell histories, palettes, style sheets, preview composites, export tiles). Forcing every PIL `Image.open` and `Image.save` through a `BinaryIO` interface would balloon the diff for very little gain in the local-disk case. The chosen shape is **bytes-friendly for the app and routes** (where S3 will matter most: serving PNGs to browsers, persisting palette JSON, listing history) and a **`local_path()` escape hatch on the local backend for the pipeline** (which today reads/writes real files). When an `S3BoardStore` lands, the pipeline will materialize the few files it actually needs (palette, style sheet, mockup) to a per-job temp dir at job start — a narrow, well-scoped piece of work compared to refactoring every PIL call. Path math is centralized in `app/storage/fs/workspace.py` so adding a new file type is a one-line change in one place.