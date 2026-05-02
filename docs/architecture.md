# Architecture

Board Factory is built around three observations about pixel-art board games that don't hold for generic asset pipelines:

1. **The board layout is a known grid, not a thing to be discovered.** AI vision models are unreliable at detecting dense small tiles like a Monopoly perimeter; arithmetic is reliable. So Board Factory's catalog is declarative — you describe the grid once and the pipeline computes positions.

2. **Style discipline matters more than coverage.** A style-locked palette extracted once at the start and applied to every later step is more important than getting "the right asset" on the first try. The pipeline assumes you'll iterate; it makes iteration cheap.

3. **The centerpiece is in a category of its own.** It's bigger and most likely to need iterative refinement, so it gets dedicated tooling (mask-and-refine). **Generation is split:** the **first** centerpiece (nothing live yet) uses **img2img** from the mockup bbox crop to anchor the sketch; **every regeneration** after that uses **text-to-image** at the catalog target size with the style sheet — same modality as perimeter spaces, not mockup-cropped img2img like functional panels.

## Components

```
docker compose
├── postgres              PostgreSQL 16 (app data: users, catalog, jobs, …)
└── board-factory         FastAPI in ``app/`` (port 8473) + ``boardfactory`` pipeline as a library
```

The **`board-factory`** image installs the web app and imports the pipeline from `/repo/pipeline` (bind-mounted in dev). There is no separate “pipeline-only” service: jobs run inside the app process (and related workers) against `boards/<id>/`.

The whole stack shares the repo: **`board-factory`** mounts `./` as `/repo` so `boards/`, `app/`, and `pipeline/` are the same tree you edit on the host. Generation and review write under each board’s `workspace/`; the app also keeps relational state in the database (Postgres in Compose by default, or SQLite when configured).

Inpainting and provider calls are made from the app so the browser can refine the centerpiece without an extra container hop.

## Provider abstraction

```
PixelArtProvider (abstract)
├── PixelLabProvider      hosted img2img/generate/inpaint
├── OpenAIImageProvider   OpenAI Images API (when configured)
└── MockProvider          offline placeholders
```

Set `BOARDFACTORY_PROVIDER` in `docker-compose.yml` to swap. To add a new provider (local SDXL, ComfyUI, etc.), implement `PixelArtProvider` in `pipeline/boardfactory/providers/pixel/yourname.py` and add a branch to `factory.get_provider`.

## Pipeline steps

| # | Step | Module | Tools |
|---|---|---|---|
| 1 | Style Lock | `steps/style_lock.py` | PIL median-cut quantizer |
| 2 | Catalog | `schemas/catalog.py` | Pydantic v2 |
| 3a | Generate spaces | `ops/orchestrate.py:generate_missing_spaces` | Provider.generate |
| 3b | Generate panels | `ops/orchestrate.py:generate_missing_panels` | Provider.img2img or inpaint |
| 3c | Generate centerpiece | `ops/orchestrate.py:generate_centerpiece` → `ops/draw_cell.py:spec_for_centerpiece` | First pass (no live asset): Provider.img2img from mockup crop. Regenerations: Provider.generate (txt2img + style sheet) |
| 4 | Cleanup | `steps/cleanup.py` | PIL palette quantize + grid snap |
| 5 | Review | `app/` (FastAPI) | Browser |
| 6 | States | `steps/states.py` | PIL filters (procedural, palette-preserving) |
| 7 | Compositor | `steps/compositor.py` | PIL paste |
| 8 | Export | `steps/export.py` | shutil.copy + JSON manifest |

## Workspace layout

Today’s on-disk model centers on **live** + **history** per cell (see `pipeline/boardfactory/assets.py`). Older trees may still have legacy `candidates/`, `cleaned/`, or `approved/` folders from pre–web-app runs; those are migration-only.

```
workspace/
  style/
    palette.json           shared palette used by every later step
    palette.gpl            same palette, art-tool format
    palette_swatch.png     visual reference of the palette
    style_sheet.png        style reference for generation
  live/<category>/<id>.png          current promoted asset per cell
  history/<category>/<id>/          timestamped PNGs — full version history
  refinements/                      centerpiece inpainting iterations
  preview/
    board_idle.png         composited board, base state
    board_active.png       composited board, active states on
  logs/run.log             one line per pipeline run (when enabled)
  frames/house/             optional 9-slice house frame tiles + frame.json
```

## Safety

- API keys are typically set in `docker-compose.yml` or a `.env` file. `make protect-keys` runs `git update-index --skip-worktree` on `docker-compose.yml` so local key edits don’t show up in `git status`.
- Workspace files live under each board’s `boards/<id>/workspace/` and `boards/<id>/export/`. The app is scoped to the repo root configured by `BOARDFACTORY_REPO`.
- Asset routes resolve files under the board workspace and reject path traversal.

## Tradeoffs that were considered

**Why not use Aseprite for cleanup?**
Aseprite's CLI quantizer produces marginally better dithering than PIL, but adds an external binary dependency and a license. PIL gets you 90% of the way and works in any container.

**Why provider calls from the web app instead of a separate pipeline worker process?**
Fewer moving parts for interactive flows: batch generation runs in-process via the job runner; refinement needs low-latency single-image calls. A subprocess-per-click model would add latency without clear benefit for local dev.

**Why procedural state generation instead of AI?**
Active variants (glow, pulse, flicker) need to look identical to the base except for one specific lighting change. AI generators introduce drift on every call — a "glowing" version often comes back with subtle composition changes that break the alignment. Procedural transforms guarantee pixel-perfect alignment.
