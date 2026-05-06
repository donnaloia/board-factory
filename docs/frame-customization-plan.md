# Frame customization — planning notes

This document captures direction for improving **house frames**: smarter data
modeling, UX, and AI-backed extraction pipelines. It builds on the current
implementation (`pipeline/boardfactory/frames.py` nine-slice house frame,
compositor overlay on panels in `steps/compositor.py`).

---

## Problem with today’s approach

- **Geometry**: Adoption effectively crops a **square** from mockup or panel;
  real UI/card frames are rarely square; forcing a square wastes information or
  warps the asset.
- **Semantics**: Frames are stored as **sprites + full overlay** pasted on
  top of panel composites. When panel art **already includes baked-in chrome**,
  stacking another frame causes **double borders**, clipping conflicts, and
  wrong layering.
- **Operations**: There is no first-class separation between **rim** (chrome you
  reuse) and **hole** (content window). Everything downstream assumes a
  rectangle footprint.

**Goal:** represent frames as **explicit structure** (masks / parameters +
provenance), optionally **proposed by vision AI**, with **deterministic**
validation and snapping before anything hits preview or export.

---

## North star

**AI proposes** boundaries / masks / parameters → **code validates**
(constraints, pixel grid, invariants) → **user confirms or edits** → committed
artifacts drive compositing.

Randomness is confined to the **proposal** step; preview and export remain
**replayable** given stored `FrameInstance` data.

---

## Decisions (agreed)

These are the working assumptions for implementation planning.

### Initial frame — end-user flow

1. User opens a **Frame** flow on the board (exact placement TBD: board menu vs setup).
2. They choose **where the chrome comes from**:
   - **Mockup** (strong signal before most tiles exist),
   - **One generated cell** (perimeter space or panel — “use the rim from this tile”), or
   - **Upload** (optional fallback).
3. **Infer frame** runs as a **job** (vision → masks / parameters → deterministic cleanup).
4. **Refine** (handles, inset, candidate pick), then **Commit**.

Board generation otherwise proceeds **as it does today**; defining the house frame is **not** a prerequisite for generating spaces/panels. Users can also adopt the frame **after** bulk generation by selecting a cell whose rim they like.

### Scope after commit — functional panels vs perimeter spaces

The committed house frame follows **catalog `frame` intent** (`enabled`,
`apply_to_panels`, `apply_to_spaces`, etc. — exact flags match the assembled
catalog).

**Functional UI (feature panels):** When frames are enabled for panels
(`apply_to_panels`), the house frame applies **board-wide** to **all** functional
panel cells of that kind — same compositing rules for every panel tile, and the
same **Approach D** “rewrite interiors + consistent rim” batch scope covers
**every panel** that catalog intent includes. Selecting or committing a frame for
this category is intentionally **not** a single-cell override.

**Perimeter board spaces:** We **do not** mirror that “apply to **all** spaces of
this type” workflow for the track. **Approach D** must **not** enqueue a bulk
regeneration across every perimeter space / space-design id when the user
commits a frame. Perimeter assets may still use **preview overlay** or other
behaviors **without** treating the perimeter catalog like “N panels to batch-fix.”
If `apply_to_spaces` remains in the schema, treat it as **explicitly narrower**
than panel bulk apply (e.g. overlay-only or a separate product decision), not as
“same as panels but for the loop.”

Per-template / multiple concurrent frame packs remain **out of scope** until
productized.

### `FrameInstance` ownership

- **Required:** `board_uuid` → `board_games.id`.
- **Optional provenance:** `source_cell_id` / `source_asset_version_id` when
  inference used a specific tile or PNG.

### Baked-in chrome — Approach **D** (chosen)

We **do not** rely on messaging alone or compositing tricks as the long-term fix.

**Approach D — one-time “re-apply frame” job:** when the user **commits** a new
`FrameInstance`, enqueue a **batch regeneration job** for **functional panels
only** when `apply_to_panels` (and frame intent) says they participate — i.e.
**every applicable panel asset**, not “every cell on the board.” **Perimeter
spaces are excluded** from this bulk job; we do **not** fan out Approach D across
all track tiles / space designs.

The job uses the stored **hole vs rim** definition so regenerated pixels **fill
the content hole** without re-baking obsolete chrome; the **new** house frame rim
is applied consistently in compositing afterward.

- **UX:** clear progress (“Updating N panels for the new frame…”), cancellation
  policy TBD, cost visibility if provider-backed.
- **Implementation:** ties into existing job runner + `draw_cell` /
  orchestration patterns; mask-aware prompts / inpaint scope are design details
  for the engineering pass.

Interim **preview** may still use improved compositing (hole mask) before the
batch finishes; **disk truth** aligns after Approach **D** completes.

---

## Data modeling — three layers

Keep **intent**, **committed artifact**, and **raw model output** separate.

### 1. `FrameSpec` (catalog intent)

What the board **should** do — typically columns or JSON aligned with the
existing catalog `frame` block (`enabled`, `apply_to_panels`, etc.), extended as
needed:

- Application scope: **panels** (board-wide when enabled) vs **perimeter**
  (explicitly **not** the same bulk-apply semantics as panels unless product
  revisits overlay-only rules).
- Constraints (min/max rim thickness, symmetry assumptions).
- Pointer to **which committed frame pack** is active (after adoption).

### 2. `FrameInstance` (board-level fact)

What was **actually** extracted or generated for **this board** — versioned
workspace / DB row:

- **Raster pack**: nine-slice PNGs (today’s shape) **and/or** alpha masks +
  derived rim sprites.
- **Optional params**: reserved for future non–nine-slice (mesh, control points).
- **Provenance**: model id, prompt hash, resolutions, approval timestamp.

#### Ownership and foreign keys

- **Primary anchor:** **`board_uuid` → `board_games.id`** (required). The house
  frame is **one pack per board**, reused wherever catalog rules apply — not
  owned by a single perimeter cell.
- **Optional provenance only:** **`source_cell_id` → `cells.id`** and/or
  **`source_asset_version_id` → `asset_versions.id`** when inference ran from a
  specific panel or history PNG. These answer “where we sampled from,” not
  “who owns the frame.”
- Do **not** require **`FrameInstance` → board-space / single cell** as the only
  parent unless the product explicitly becomes **per–space-design** frames.

### 3. `FrameSegmentation` (optional — AI scratch)

Raw model outputs before commit (polygons, RLE masks, scores). Lets you debug,
re-run, and compare **without** overwriting committed `FrameInstance`.

---

## UI / UX — three phases

| Phase | User intent | System behavior |
|-------|-------------|-----------------|
| **Propose** | “Guess my frame” | Run vision job → overlay **rim vs hole** on mockup/preview; show confidence and ambiguity (multiple candidates). |
| **Refine** | “Almost” | Drag corners / inset, pick candidate, optional snap-to-grid; never overwrite committed state silently. |
| **Commit** | “Use this” | Persist `FrameInstance` + update catalog pointer; **enqueue Approach D** (batch regen for **functional panels** in scope — **not** bulk perimeter spaces); show job progress; invalidate previews as assets complete. |

UX must make **hole vs rim** obvious (two-tone overlay or sliders). Until batch
regen finishes, preview may use **hole-mask compositing**; after Approach **D**,
on-disk assets match the new frame semantics without double chrome.

---

## AI + pipelines

**Batch job (reproducible):** mockup or chosen panel → model → mask(s) →
deterministic cleanup (grid snap, morphology) → derive nine-slice or masks →
write candidate `FrameInstance`.

**Optional agent:** same steps orchestrated interactively; **same artifacts** as
batch — no second source of truth.

**Compositor contract:** evolve from **full-rectangle overlay** toward **rim-only
composite using an inner hole mask**. Approach **D** is the primary answer to
**baked-in old chrome**; compositor improvements handle **preview** and **export**
correctness while jobs run.

### Vision / extraction phasing (model quality)

1. **Phase A:** Single **binary mask** + human bbox; derive slices from mask
   (better than square crop).
2. **Phase B:** **Outer + inner** masks or distance fields for stable rim
   thickness → cleaner sprites.
3. **Phase C:** Non–nine-slice only if the product needs perspective or warped
   frames (higher cost).

### Regeneration job (Approach D)

On commit, submit work items for each affected **panel** `(category, asset_id)`
when panels are in scope — **omit** perimeter space designs from this fan-out.
Each item should receive **frame geometry** (hole / rim) so the pipeline can
**regenerate interior content** without legacy chrome and apply the **new**
house frame at composite time. Exact mechanism (inpaint vs full regen vs
strength-controlled img2img) is an implementation choice; the contract is
**rewrite pixels** for scoped **panel** cells, not only overlay.

---

## Repository layout (convention)

Use the repo’s existing split so generation code stays testable without FastAPI
and HTTP stays thin:

- **`pipeline/boardfactory/`** — raster math, nine-slice / mask compose,
  compositor changes, vision-inference adapters, and any new **batch steps**
  called from jobs (same pattern as `frames.py`, `steps/compositor.py`,
  `ops/draw_cell.py`). Do **not** put pipeline algorithms under `app/` unless
  they are glue only.

- **`app/domains/`** — persistence, routes, and orchestration that touches the DB
  and job runner. **Frames** are a good fit as a **sub-area of `cells`** (e.g.
  extra modules alongside `domains.cells` routes/services/repository): frames
  apply to **cells** (panels/spaces) at composite time, even though
  `FrameInstance` is keyed by **board**. If the surface grows large, promoting
  to `domains.frames` is an optional later split — start aligned with **cells**
  unless boundaries get noisy.

---

## Risks

- **Ambiguous frames** (multiple rings): multi-candidate UI + explicit pick.
- **Cost / latency:** vision **and** Approach **D** batch regen run as **jobs**
  with progress, not blocking HTTP.
- **Batch scope:** accidental “regen everything” — tie Approach **D** to **panel**
  inventory only for bulk work; confirm when N is large. Perimeter spaces must
  not inherit panel-scale batch scope by mistake.
- **Palette:** rim pixels may need **quantize** to board palette where required.
- **Evals:** small gold set of boards + mask IoU or visual regression snapshots.

---

## References (code)

- `pipeline/boardfactory/frames.py` — house frame storage, nine-slice compose.
- `pipeline/boardfactory/steps/compositor.py` — panel paste + frame overlay.
- Catalog `frame` block on `board_games` / assembled catalog — intent flags today.

---

## Next artifact

When implementing: ADR or ticket breakdown covering **`FrameInstance` schema**,
**first vision infer job**, **compositor hole-mask preview path**, and **Approach
D job** (enqueue from commit handler, per-cell work units, progress UX,
interaction with `draw_cell` / orchestrate).
