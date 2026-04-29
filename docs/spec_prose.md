# Damnation Board — layout spec

## intro

This document is the source of truth for the damnation board's geometry — every coordinate, dimension, and tile classification used by the Board Factory pipeline. The pipeline reads `catalog/board.yml` and uses these dimensions for every step: style lock, generation, cleanup, composition, and export.

**The catalog *is* the spec.** Every diagram, table, and number on this page is generated live from `catalog/board.yml`. If you want to change the board, edit the catalog — this page will update automatically. There is no longer a way for the docs to drift.

## battle-tiles

Five perimeter spaces are designated as **battle tiles** — landing on one triggers a combat encounter. They're scattered across all four edges so battles aren't clustered geographically. For prototype purposes they're rendered as deep purple stone with a "BATTLE" label.

Battle tiles span two different sizes (160 × 180 on top/bottom, 180 × 144 on left/right), so they live as two designs in the catalog (`battle_space_top_bottom`, `battle_space_side`). Both share the same prompt; only the dimensions differ. This is required by the catalog schema's "all positions for one design must share size" rule.

## geometry-derivation

### Why 1920 × 1080 native

16:9 covers ~70% of modern displays. Native 1920 × 1080 integer-scales 1× on 1080p screens and 2× on 4K. 1440p users get 1× with letterbox (standard practice for pixel-art games on that resolution).

### Why asymmetric perimeter tiles

1920 / 12 = 160 forces top/bottom width. With top/bottom tile height of 180 px, the inner area is 1080 − 2×180 = 720 px tall. 720 / 5 = 144 forces side tile height. The result is taller-than-wide top/bottom tiles (160 × 180) and slightly wider-than-tall side tiles (180 × 144), all of which divide cleanly into the 16:9 canvas with no gaps.

### Why 260 × 240 functional cells

Inner area is 1560 wide. The middle column is 2× the width of the side columns (4 × s + 2 × s = 6s = 1560), giving s = 260 for side columns and 520 for the centerpiece column. Inner area is 720 tall, divided into 3 equal rows of 240 each.

## mockup-handling

The mockup file (`mockup/board.png`) is a **stylistic reference**, not the dimensional source of truth. The catalog defines every dimension. The mockup just tells the model what the visual world looks like.

### Coordinate spaces

Every bbox in `catalog/board.yml` lives in **canvas coordinates** (0–1920 × 0–1080). When the pipeline needs to crop a reference region from the mockup for img2img conditioning, it reads the mockup file's actual dimensions at runtime and scales each bbox into the mockup's coordinate space using `canvas_to_mockup` in `geometry.py`. Both axes scale independently.

Result: the same catalog works whether the mockup is 1024 × 583, 1920 × 1080, 1500 × 844, or anything in between, with no manual adjustment.

### Aspect-ratio sanity check

Pipeline startup (style, generate, preview, and full run) calls `validate_mockup_dimensions`, which compares the mockup's aspect ratio to the canvas. The tolerance is **5%**. Within tolerance, a note is printed but the run continues. Beyond tolerance, the run aborts with a clear error — img2img reference crops would be visibly stretched and that's almost never what you want.

For the canonical 1920 × 1080 (1.778) canvas, the acceptable mockup ratio range is roughly **1.689–1.867**. That covers all common 16:9 outputs from AI image generators (1024 × 576 = 1.778, 1024 × 583 = 1.756, 1280 × 720 = 1.778, 1536 × 864 = 1.778, etc.) plus some tolerance for off-by-a-few-pixels rendering.

### What the mockup is used for

| Pipeline step | Mockup usage |
|---|---|
| Style Lock | Palette extraction (median-cut on full mockup) + 4×4 style sheet |
| Generate (panels + centerpiece) | Per-asset img2img seeding via `crop_region` with canvas → mockup translation |
| Generate (board spaces) | None — perimeter spaces use text-to-image only with the style sheet as reference |
| Compositor | Faded backdrop, aspect-preserving fit (letterboxed if needed) |
| Cleanup / States / Export | None — operate on candidates only |

## display-behavior

| Display | Scale | Letterbox? | Notes |
|---|---|---|---|
| 1080p (1920 × 1080) | 1× | none | Pixel-perfect native |
| 1440p (2560 × 1440) | 1× | 320 + 360 px | Centered with letterbox; standard for the resolution |
| 4K (3840 × 2160) | 2× | none | Each source pixel becomes a 2 × 2 block |
| 16:10 (e.g. 1920 × 1200) | 1× | 120 px top/bot | ~6% letterbox; visually invisible |
| 21:9 ultrawide | 1× | ~480 px sides | Pillarbox; expected for non-native content |

## changelog

- **0.5** — Spec page rewritten as a live render of `catalog/board.yml`. Geometry, cell tables, summary stats, legend, and battle-tile coords are all generated. Prose moved to `docs/spec_prose.md`.
- **0.4** — Decoupled mockup dimensions from canvas. Pipeline now scales canvas-space bboxes into mockup-space at crop time. Added aspect-ratio sanity check at pipeline startup (5% tolerance, hard-fails beyond).
- **0.3** — Added 5 battle tiles (top.3, bottom.7, left.2, right.0, right.4). Reframed doc as a tech spec.
- **0.2** — Fixed inner-grid math (260 × 240 functional cells, 520 × 720 centerpiece). Pulled per-row size into schema.
- **0.1** — Initial Option 2.5 layout: 1920 × 1080 native, 34 perimeter, 12 functional, 1 centerpiece.
