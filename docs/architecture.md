# Architecture

Board Factory is built around three observations about pixel-art board games that don't hold for generic asset pipelines:

1. **The board layout is a known grid, not a thing to be discovered.** AI vision models are unreliable at detecting dense small tiles like a Monopoly perimeter; arithmetic is reliable. So Board Factory's catalog is declarative — you describe the grid once and the pipeline computes positions.

2. **Style discipline matters more than coverage.** A style-locked palette extracted once at the start and applied to every later step is more important than getting "the right asset" on the first try. The pipeline assumes you'll iterate; it makes iteration cheap.

3. **The centerpiece is in a category of its own.** It's bigger, more expensive to generate, and most likely to need iterative refinement. So it gets dedicated tooling (mask-and-refine) instead of being treated like a panel.

## Components

```
docker compose
├── boardfactory-cli      Python pipeline (CLI-only, runs on demand)
└── review-ui             FastAPI app, runs continuously, port 8473
```

Both containers share `/repo` (your project directory) as a volume. The pipeline writes intermediate files into `workspace/`; the review UI reads those files and writes user approvals back into `workspace/approved/`.

For centerpiece refinement the review UI talks directly to PixelLab — it doesn't go through the pipeline container — so users can iterate without leaving the browser.

## Provider abstraction

```
PixelArtProvider (abstract)
├── PixelLabProvider     hosted, ~$0.03/image, supports generate/img2img/inpaint
└── MockProvider         offline, deterministic placeholders, $0/image
```

Set `BOARDFACTORY_PROVIDER` in `docker-compose.yml` to swap. To add a new provider (local SDXL, ComfyUI, etc.), implement `PixelArtProvider` in `pipeline/boardfactory/providers/pixel/yourname.py` and add a branch to `factory.get_provider`.

## Pipeline steps

| # | Step | Module | Tools |
|---|---|---|---|
| 1 | Style Lock | `steps/style_lock.py` | PIL median-cut quantizer |
| 2 | Catalog | `schemas/catalog.py` | Pydantic v2 |
| 3a | Generate spaces | `steps/generate.py:do_generate_spaces` | Provider.generate |
| 3b | Generate panels | `steps/generate.py:do_generate_panels` | Provider.img2img |
| 3c | Generate centerpiece | `steps/generate.py:do_generate_centerpiece` | Provider.img2img |
| 4 | Cleanup | `steps/cleanup.py` | PIL palette quantize + grid snap |
| 5 | Review | `services/review-ui/` | Browser |
| 6 | States | `steps/states.py` | PIL filters (procedural, palette-preserving) |
| 7 | Compositor | `steps/compositor.py` | PIL paste |
| 8 | Export | `steps/export.py` | shutil.copy + JSON manifest |

## Workspace layout

```
workspace/
  style/
    palette.json           shared palette used by every later step
    palette.gpl            same palette, art-tool format
    palette_swatch.png     visual reference of the palette
    style_sheet.png        4x4 grid of mockup crops, fed to model as style ref
  candidates/<category>/<id>/v01.png ... v06.png
                          raw model output, before any cleanup
  cleaned/<category>/<id>/v01.png ... v06.png
                          quantized to palette + snapped to pixel grid
  approved/spaces/<id>.png
  approved/panels/<id>.png
  approved/panels/<id>_active.png      (only if needs_active)
  approved/centerpiece.png
  approved/centerpiece_active.png      (only if needs_active)
  refinements/centerpiece_v01.png ...  iterative inpainting outputs
  preview/board_idle.png   composited board, base state
  preview/board_active.png composited board, all active states on
  logs/run.log             one line per pipeline run
```

## Safety

- API keys live in `docker-compose.yml`. `make protect-keys` runs `git update-index --skip-worktree` so local edits to that file don't show up in `git status`.
- Workspace files live entirely under `workspace/` and `board_assets/`, both under the repo root. Nothing is written outside `/repo`.
- The review UI's `/asset/<path>` route resolves paths under `workspace/` only; path traversal is rejected.

## Tradeoffs that were considered

**Why not use Aseprite for cleanup?**
Aseprite's CLI quantizer produces marginally better dithering than PIL, but adds an external binary dependency and a license. PIL gets you 90% of the way and works in any container.

**Why direct PixelLab call from review UI instead of routing through pipeline container?**
Reduces moving parts. Pipeline runs are batch jobs; review-ui needs synchronous single-image inpainting. Spinning up a pipeline subprocess per refinement would add latency and complexity for no benefit.

**Why procedural state generation instead of AI?**
Active variants (glow, pulse, flicker) need to look identical to the base except for one specific lighting change. AI generators introduce drift on every call — a "glowing" version often comes back with subtle composition changes that break the alignment. Procedural transforms guarantee pixel-perfect alignment.
