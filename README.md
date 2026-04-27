# Board Factory

A pipeline for generating pixel-art board game assets from a single mockup. Purpose-built for game-board layouts that combine three asset categories — small repeating perimeter spaces, large illustrated feature panels, and a single complex centerpiece. Outputs a coherent, palette-locked, game-ready asset set in pixel art.

## Why this exists

Most AI asset pipelines assume "UI screen → many small isolated assets." Board Factory assumes "fixed board layout → tiles that must visually integrate, in pixel art, with state changes." The differences matter:

- **Style discipline matters more than coverage.** All assets share one quantized palette extracted from a reference image, so they look like they came from one artist.
- **Three asset categories, three generation strategies.** Board spaces are batch-generated for coverage. Feature panels are per-asset with rich prompts. The centerpiece uses image-to-image translation from your existing mockup with iterative inpainting refinement.
- **Pixel cleanup is a first-class step.** AI generators produce smooth gradients pretending to be pixel art; Board Factory snaps everything to a shared palette and pixel grid so the output is real pixel art, not "AI's idea of pixel art."
- **Geometry is declarative, not detected.** Your board layout is a known grid; you describe it once in YAML and the pipeline computes positions arithmetically. No vision-AI bbox detection that fails on dense small tiles.

## How it works

The pipeline is eight steps. You start it with one command and a catalog file; the only steps that require you to be present are the review steps.

### 1. Style Lock

| | |
|---|---|
| **Input** | Your mockup PNG + a written style brief in `catalog/board.yml` |
| **Powered by** | PIL palette extraction (median-cut quantization to 16–32 colors) |
| **Output** | `workspace/style/palette.json` (the shared palette) and `workspace/style/style_sheet.png` (visual reference) |

### 2. Catalog Validation

| | |
|---|---|
| **Input** | `catalog/board.yml` |
| **Powered by** | Pydantic schema validation |
| **Output** | A normalized catalog with all board space positions resolved and all panel bboxes verified against the mockup dimensions |

### 3. Generate (branched by category)

| Category | Strategy | Candidates |
|---|---|---|
| **Board spaces** | Batch generation per unique design, conditioned on the style sheet | 3 per design |
| **Feature panels** | Per-panel img2img from the cropped mockup region | 6 per panel |
| **Centerpiece** | Img2img from the cropped centerpiece region with high strength | 12 candidates |

### 4. Pixel Cleanup

| | |
|---|---|
| **Input** | All raw candidates from step 3 |
| **Powered by** | PIL — palette quantization + grid snapping |
| **Output** | `workspace/cleaned/` — every candidate downscaled to native resolution, locked to the shared palette, edges snapped to the pixel grid |

### 5. Review

Three view modes at `http://localhost:8473`:

| Mode | Asset type | Interaction |
|---|---|---|
| **Grid** | Board spaces | All ~12 unique designs visible simultaneously, click candidate to approve |
| **Carousel** | Feature panels | One panel at a time, all candidates side-by-side |
| **Mask-and-refine** | Centerpiece | Single large preview, drag to mark regions, click Refine to regenerate masked regions only via inpainting |

### 6. State Generation

| | |
|---|---|
| **Input** | Approved feature panels with `needs_active: true` |
| **Powered by** | Procedural shader-style transforms (glow, pulse) — deterministic, palette-preserving |
| **Output** | `workspace/approved/panels/<id>_active.png` for every panel that needs an active state |

### 7. Board Compositor

| | |
|---|---|
| **Input** | All approved assets + board geometry |
| **Powered by** | PIL `Image.paste()` |
| **Output** | `workspace/preview/board_idle.png` and `workspace/preview/board_active.png` — the assembled board for visual coherence check |

### 8. Export

| | |
|---|---|
| **Input** | All approved assets + animation configs |
| **Output** | `board_assets/` — individual PNGs organized by category, plus `board_manifest.json` for engine import |

## Requirements

- Docker + Docker Compose
- A [PixelLab API key](https://www.pixellab.ai) (recommended; ~$0.03/image, ~$5 per full board run)
- Optionally: a local Stable Diffusion install for the offline path (Apple Silicon recommended)

You can also run end-to-end with the **mock provider** to test the pipeline structure without spending anything — useful for validating your catalog and seeing the review UI before plugging in the real model.

## Setup

1. Fill in your API key in `docker-compose.yml` near the top of the `boardfactory-cli` service:

   ```yaml
   PIXELLAB_API_KEY: "your-pixellab-key-here"
   ```

   Or skip this and use `BOARDFACTORY_PROVIDER: mock` to test the pipeline shape without an API.

2. (Optional but recommended) Stop git from tracking your edits to that file:

   ```bash
   make protect-keys
   ```

3. Drop your mockup PNG into `mockup/` and edit `catalog/board.yml` to describe your board.

4. Bring everything up:

   ```bash
   make up
   ```

## Usage

End-to-end run on one mockup:

```bash
make run
```

That runs steps 1–4 (style lock, catalog validation, generate, cleanup) and stops. Then open the review UI:

```bash
open http://localhost:8473
```

Approve assets in each of the three view modes. When everything is approved, finish:

```bash
make states     # generate active variants for panels
make preview    # composite the board for visual review
make export     # copy approved assets to board_assets/
```

## Folder Overview

```text
pipeline/                 Python pipeline code
  boardfactory/
    providers/            Pluggable image-gen providers (PixelLab, mock)
    schemas/              Pydantic models for catalog + manifest
    steps/                One module per pipeline step
services/
  review-ui/              Local web UI for approve/refine
catalog/
  example.yml             Sample catalog file
  board.yml               Your catalog (you create this)
mockup/                   Source mockup PNG (you provide)
workspace/                All intermediate pipeline artifacts
  style/                  Palette + style sheet
  candidates/             Raw generated candidates
  cleaned/                Palette-quantized + grid-snapped candidates
  approved/               Candidates promoted via the review UI
  refinements/            Centerpiece inpainting iterations
  preview/                Composited board preview
  logs/                   Run logs
board_assets/             Final exported asset set (engine-ready)
docs/
  architecture.md         Design notes
```

## Make Targets

| target | what it does |
|---|---|
| `make up` | Build images and start review-ui in the background |
| `make down` | Stop all services |
| `make logs` | Tail logs |
| `make shell` | Open a bash shell inside the pipeline container |
| `make run` | Steps 1–4: style + catalog + generate + cleanup |
| `make style` | Just the style lock step |
| `make catalog` | Validate the catalog |
| `make generate` | Just the generate step |
| `make cleanup` | Just the cleanup step |
| `make states` | Generate active state variants for approved panels |
| `make preview` | Composite the assembled board |
| `make export` | Copy approved assets to board_assets/ |
| `make clean` | Wipe workspace/ subdirectories |
| `make protect-keys` | Stop git from tracking your edits to docker-compose.yml |
| `make unprotect-keys` | Reverse of protect-keys |

## Configuration

All configuration lives in `docker-compose.yml` under the `boardfactory-cli` service's `environment` block. Useful knobs:

- `BOARDFACTORY_PROVIDER: pixellab|mock` — image gen provider. Use `mock` for offline testing.
- `BOARDFACTORY_PALETTE_SIZE: 24` — number of colors in the locked palette
- `BOARDFACTORY_SPACE_CANDIDATES: 3` — candidates per board space design
- `BOARDFACTORY_PANEL_CANDIDATES: 6` — candidates per feature panel
- `BOARDFACTORY_CENTERPIECE_CANDIDATES: 12` — candidates for the centerpiece

After changing values, run `make down && make up`.

## Costs

With PixelLab provider on a typical board (~12 unique board space designs + 8 panels + 1 centerpiece):

| Step | Calls | Cost |
|---|---|---|
| Generate spaces | 12 designs × 3 candidates | ~$1.10 |
| Generate panels | 8 panels × 6 candidates | ~$1.45 |
| Generate centerpiece | 12 candidates | ~$0.40 |
| Centerpiece inpainting | ~5 refinements typical | ~$0.20 |
| **Total per full board run** | | **~$3.15** |

State generation, compositing, cleanup, and export are all free (local compute).

## Troubleshooting

**`PIXELLAB_API_KEY is not set`**
Add it to `docker-compose.yml` under the `boardfactory-cli` service, then `make down && make up`. Or set `BOARDFACTORY_PROVIDER: mock` to bypass.

**`segment` produces poor cutouts on detailed assets**
Edit the bbox in `catalog/board.yml` to tighten the region around the asset.

**Generated assets don't match the original mockup style**
Tighten `style.prompt` in `catalog/board.yml` and re-run `make style && make run`. The style sheet is regenerated each run from your reference and prompt.

**I accidentally committed my API keys**
Run `git rm --cached docker-compose.yml`, rotate the key at the PixelLab dashboard, paste the new key, then `make protect-keys`.
