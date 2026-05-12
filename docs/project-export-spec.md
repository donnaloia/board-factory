# Project export — technical specification (skeleton)

**Status:** Skeleton — **`app/exporter/`** + **GET** ``…/export/project-bundle.zip`` (authenticated; zip bytes from a **temp dir** only, no board-store artifacts). **Land triggers**: **§10** (**implemented**).  
**Related product:** Board Factory — ship a **portable bundle** (directory, optionally **zip**) of **assets + a single project JSON** for engines, tools, and **LLM-assisted codegen**.  
**Last updated:** 2026-05-12

---

## 1. Summary

Export produces a **self-contained folder** (or `.zip` of that folder) containing:

1. **Binary assets** — still images, optional **space animations** (see `docs/space-animations-spec.md`), frames, mockups, etc., laid out in a **stable relative path** scheme.  
2. **One canonical `project.json` (name TBD)** — maps **logical game objects** (board, spaces, links, rules hints) to **file paths** inside the bundle, plus **game-level metadata** (title, dimensions, palette references, export version).

**Intent:** A developer or **LLM** can read the JSON, discover **what exists** and **where files live**, and emit **engine-specific** code (Godot, Unity, custom WebGL, etc.) without reverse-engineering the Board Factory DB or workspace layout.

**Example relationship (product goal):**  
*Landing on a given **perimeter** space that has a **hidden link** to a **functional UI** space should **trigger that functional space’s animation** (when an animation asset exists).*  
The JSON must be able to express **that graph** (perimeter id → linked functional space id → animation asset path, plus trigger semantics). **Authoring** those links is **live**: perimeter cells expose a **Land trigger** control in the sidebar; persistence is **`cells.triggers_functional_cell_id`** — see **§10**. The **export job** still has to read that FK and emit **`interaction_graph`** when `app/exporter/` lands.

---

## 2. Goals (draft)

| ID | Goal | Notes |
| --- | --- | --- |
| **G1** | **Portable bundle** | Directory or zip; relative paths only inside JSON so the bundle is relocatable. |
| **G2** | **Stable mapping** | Every referenced asset has a deterministic path and a stable **id** in JSON (space id, asset version id, or export-local surrogate — **TBD**). |
| **G3** | **Game + navigation graph** | JSON includes enough structure for **inter-space relationships** (e.g. perimeter → functional link, **animation trigger** on land). |
| **G4** | **LLM-friendly** | Human-readable keys, explicit types/enums, **schema version** field; avoid implicit conventions that require reading Python. |
| **G5** | **Versioned format** | `export_schema_version` (or similar) so consumers can branch on format evolution. |

---

## 3. Non-goals (initial skeleton)

- Replacing live Board Factory APIs or real-time sync.  
- Shipping a **reference runtime** for every engine — export is **data + assets**, not a player.  
- Specifying every **export-button** interaction detail (inline spinner vs job polling) beyond the sketch in **§9.4**.

---

## 4. Bundle layout (illustrative only)

Exact names are **TBD**; shape is indicative:

```text
<bundle>/
  project.json          # canonical manifest + graph + game info
  assets/
    spaces/
      <space_id>/
        live.png
        animation_live.apng   # optional; absent if none
    board/
      preview.png
      ...
```

Consumers resolve paths as **`path relative to bundle root`** (or a documented `assetsRoot` key).

---

## 5. JSON responsibilities (sketch)

- **Meta:** `export_schema_version`, optional `bundle_assets_root`, board id / slug; optional **`game_engine_instructions`** (string or structured) — human- and LLM-oriented handoff text for the target engine (replaces burying that only inside nested export metadata).  
- **Game:** title, author-facing description, board geometry summary (size, cell grid if applicable — align with existing catalog concepts).  
- **Spaces:** list of space records: id, type/role, paths to **live still**, optional **live animation**, labels, z-order or layer hints if needed.  
- **Graph / triggers:** explicit objects or edges, e.g. `{ "from": "perimeter:...", "to": "functional:...", "kind": "hidden_link", "on": "land", "play_animation": true }` — **field names and enum set are placeholders** until a schema pass.  
- **Provenance (optional):** pointers back to internal `asset_version` ids for support/debug (may be stripped in “public” export mode).

### 5.1 Implementation status

- **Today:** **GET** ``/users/{username}/board-games/{path_slug}/export/project-bundle.zip`` (same auth as the board UI) builds the bundle in a **process-local temp directory**, zips it, returns bytes — **nothing is written** under the board’s store for this download. Code: **`app/exporter/`** + ``domains.boards.routes_api``.
- **Future:** streaming / background zip for very large boards; optional **palette** file in bundle; **§9.4** UI hook from the board page.

### 5.2 Geometry parity with the live board SVG

Export **`spaces[].rect_canvas`** must use the **same math** as the inline board SVG so Godot (or any engine) can stack sprites on the same pixels as **`app/frontend/views/board_svg.py`**.

| Catalog region | Source fields | Pixel rect `(x, y, width, height)` |
| --- | --- | --- |
| **Perimeter cell** | Each `board_spaces.designs[]` entry has `positions[]` strings like `top_row.3`. Layout row defs live in `board_spaces.layout`. | For each `(design, position_ref)`, call **`domains.cells.geometry.resolve_position`** (`layout` dict, `position_ref`). Same behavior as pipeline `BoardSpacesSpec.resolve_position`. |
| **Feature panel** | `feature_panels.panels[].bbox` is **`[x1, y1, x2, y2]`** (canvas coords). | `x = x1`, `y = y1`, `width = x2 - x1`, `height = y2 - y1` (matches `board_svg` conversion). |
| **Centerpiece** | `centerpiece.bbox` is **`[x1, y1, x2, y2]`**. | Same conversion as panels. |
| **Canvas size** | `board_size` | `[width, height]` for the root view / `canvas_pixels`. |

**Reference code (repo):**

- Default catalog skeleton (new boards): **`pipeline/boardfactory/boards.py`** — `default_catalog_dict`.
- Layout math (raw dict): **`app/domains/cells/geometry.py`** — `resolve_position`.
- SVG placement (authoritative consumer): **`app/frontend/views/board_svg.py`** — `render_board_svg`.
- Human-readable geometry prose: **`docs/spec_prose.md`**.

**Note:** boards edited in the UI may **differ** from `default_catalog_dict`; the exporter must always read **that board’s persisted catalog**, not the default template.

---

## 6. Dependencies on other work

| Dependency | Why |
| --- | --- |
| **Space animations spec** | Export must reference animation files and trigger semantics consistently. |
| **Data model for links** | **Shipped:** perimeter → functional **land triggers** via **`cells.triggers_functional_cell_id`** (nullable FK); sidebar **Land trigger** when a perimeter design is selected. **§10** is the normative description. **Export** must still project FK → **`interaction_graph`** when the exporter runs. |
| **Cells → spaces rename** | JSON may use `spaces` array naming even if DB still says `cells` internally — align in one naming pass. |

---

## 7. Open questions (for next revision)

1. **Zip vs directory only** — always both, or user-selectable?  
2. **Single `project.json` vs split files** (e.g. `graph.json` + `manifest.json`) for large boards.  
3. **JSON Schema** — ship `docs/project-export/project-export.schema.json` alongside examples?  
4. **Public vs full export** — strip internal ids / cost metadata for external handoff?  
5. **Animation absent** — omit key, null path, or explicit `"animation": null` for LLM clarity?  
6. **Catalog as source of truth** — how much of `project.json` is a **projection** of existing catalog YAML/JSON vs new export-only sections?

---

## 8. Success criteria (MVP — loose)

- A tool (or human) can unzip a bundle, open **one** JSON file, and list **all spaces** with **resolved asset paths**.  
- The schema has a **documented place** for **perimeter → functional** relationships and **animation-on-land** intent; bundles may still emit an **empty** `interaction_graph` when no triggers are set or export has not yet read the FKs.  
- **Schema version** is present and incremented when breaking changes occur.

---

## 9. Code placement — `app/exporter/` (not a business domain)

Export is treated like **`auth/`** or **`home/`**: **important, cross-cutting functionality** that is **not** a core business noun in the same sense as boards or cells. Implementation lives under **`app/exporter/`** (package name `exporter`).

| Decision | Rationale |
| --- | --- |
| **`app/exporter/`** | Holds **projection + packaging** (catalog → `project.json`, optional zip / `assets/` tree). Keeps “export” out of `domains/` until it grows its own persisted lifecycle worth a bounded context. |
| **`domains/boards/`** (or jobs) **orchestrates** | Board ownership, authz, and HTTP entry (“export this board”) stay on the **boards** domain; it **calls into** `exporter` with catalog data (or narrow callbacks), similar to how other domains call `auth` without `auth` owning board rules. |
| **Cross-domain call is intentional** | Boards loads the catalog / resolves paths; exporter stays **testable** and avoids importing board repositories if data is passed **in** as plain structures. |

**Guardrails**

- Prefer **`exporter`** modules that are **mostly pure**: given a catalog dict + hooks to resolve live asset paths, return JSON or write a tree — easier to unit test and avoids import cycles.  
- If export later gains **persisted runs**, quotas, or admin-only UX, **revisit** promoting **`domains/exports/`** with `models.py` / `repository.py`; until then, **`app/exporter/`** stays the home.

### 9.1 HTTP — routes live on boards, not on `exporter`

- **`exporter/`** does **not** register FastAPI routes — it is a **library** invoked from elsewhere.  
- **User-facing export** needs an HTTP entry somewhere: default is **`domains/boards/routes_api.py`** (e.g. `GET …/export` returning a zip, or `POST` enqueueing work then downloading when ready).  
- **Alternatives:** a **job** kind that runs exporter code in the worker and serves the artifact via an existing file/job URL; or a **CLI** for ops/dev with **no** route.  
- Add a **dedicated `/api/exports/...` router** only if export becomes a standalone product surface; not required for MVP.

### 9.2 Orchestrator + staged functions

Export implementation is a **linear sequence of small steps** driven by **one orchestrator** (e.g. `run_board_export(...) -> ExportResult`), not a second long-lived “pipeline” package alongside `pipeline/boardfactory/` — in prose call them **export stages** to avoid naming collision.

- **Orchestrator** — single entrypoint: build **`BoardExportState`**, run stages in order, handle hard failures and logging.  
- **`BoardExportState`** (dataclass or similar) — carries catalog snapshot, board id, mutable `project` dict, output paths, accumulated errors — avoids long parameter lists across stages. Prefer this name over bare **`BoardState`**, which collides with “live board / UI / session” usage elsewhere.  
- **`ExportDeps`** (optional) — narrow injection for DB, `BoardStore`, asset URL resolvers so stage functions stay unit-testable with fakes.  
- **Stages (illustrative order, align with delivery milestones):**  
  1. **Geometry** — fill `board` + each space’s `rect_canvas` from catalog (§5.2).  
  2. **Asset wiring** — resolve live still / animation paths; copy into `assets/` when bundling.  
  3. **Bundle packaging** — write `project.json` + tree; optional zip.  
  4. **`interaction_graph`** — emit when link data exists in the persistence model; else empty.  
  5. **Polish** — `game_engine_instructions`, schema validation, manifest fields.  

**Implemented order** in `app/exporter/orchestrate.py`: geometry → **`interaction_graph`** → asset wiring → **polish** → write `project.json`, so the graph and handoff fields are present before stills are resolved and the manifest is written last (zip still TBD).

Each stage is a **plain function** (`stage_geometry(state) -> None` mutating `state`, or returning a patch — pick one convention). Keep **one** orchestrator module under `exporter/` (e.g. `exporter/orchestrate.py`); avoid duplicating orchestration in both `boards` and `exporter`.

### 9.3 Layout / geometry — no duplicate service

- Perimeter pixel rects: use existing **`domains.cells.geometry.resolve_position`** (same as SVG / §5.2).  
- Do **not** introduce a parallel “geometry service” that re-implements row math; the catalog + `resolve_position` path is already shared with **`app/frontend/views/board_svg.py`**.  
- Panel/centerpiece: apply **`bbox` `[x1,y1,x2,y2]` → `x,y,width,height`** in an export stage (same rule as §5.2). Boards may precompute rects and pass them into `exporter` if you want `exporter` to avoid importing `cells` — either wiring is acceptable as long as **one** implementation of the math exists.

### 9.4 End-user UX — export / Godot button (board page)

The **last action control above the board** (working label: **Export** or **Godot**) triggers download of the bundle (or `project.json` + assets, per implementation).

**Preferred behavior (MVP):** **inline** feedback on the control — **no blocking modal**.

- **Idle** — button shows default label (e.g. “Export” / “Godot”).  
- **In progress** — button **disabled**, **spinner** (or busy icon) + short copy such as **“Preparing export…”** on or beside the same control. Prevents double-submits without taking over the screen.  
- **Success** — start the **browser download** automatically: e.g. `GET` with `Content-Disposition: attachment`, or **`fetch` → `Blob` → temporary `<a download>`** so the tab stays on the board. The OS/browser **save dialog** is the expected end state; no extra “click here to download” step unless the API returns a **separate signed URL** (then a single follow-up click or same-tab navigation is acceptable).  
- **Failure** — show error **inline** (subtitle under the button, `title` tooltip, or a small non-blocking toast); **re-enable** the button.  

**If export becomes slow or variable** (large zip, background job): keep **inline** as the default — e.g. button switches to **“Preparing…”** then **“Download ready”** when polling completes, or a slim **toast** with a download link. Escalate to a **modal** only if product needs explicit “do not close tab” copy or multi-step choices; not the default.

*(See also `app/ARCHITECTURE.md` — auxiliary top-level packages.)*

---

## 10. Perimeter → functional land triggers (persistence + UI) — **implemented**

This section documents the **shipped** model the exporter must read to fill **`interaction_graph`** (e.g. land on perimeter **A** → play or focus functional **B**). **§9.2** stage 4 is the wiring step inside `exporter/` once the bundle pipeline exists.

### 10.1 Product / UX (as shipped)

- User selects a **perimeter** cell on the board.  
- The **sidebar** includes **Land trigger**: a **dropdown** of **functional** panel targets (**single** optional link).  
- Clearing the selection = **no trigger** (same as never setting it).

### 10.2 Persistence (**locked**, implemented)

- **Model:** **nullable foreign key** on the **perimeter-side** row (the cell that can initiate the trigger), pointing at the **target functional** row. Both endpoints are rows in **`cells`** (`CellRecord`). **`NULL`** means “no land trigger / no linked functional.”  
- **Discriminator:** use **`cells.kind`** (not `space_kind` — that field is only for **`standard` / `event`** flavor on space rows and does **not** distinguish perimeter vs functional UI).  
  - **Source row** must be a **perimeter / board-space** cell: **`cells.kind = 'space'`** in the DB today; planned rename to **`'perimeter'`** (see **`docs/TODO-issues.md`** §13).  
  - **Target row** must be a **functional UI** cell: **`cells.kind = 'panel'`** today; planned rename to **`'functional'`** (same TODO).  
  - Reject pairs where `kind` does not match those roles (and reject **`centerpiece`** as source or target unless product later allows it).  
- **Not** a many-to-many link table for MVP: one optional target per perimeter cell matches the single dropdown. Revisit a **link table** later if product needs **multiple** actions per land or rich per-edge metadata.  
- **Validation (server):** both rows share the same **`board_uuid`**; enforce **`cells.kind`** rules above; reject self-loops (`from_id == to_id`).  
- **Granularity (locked):** the link is **per space design**, not per physical grid slot. The source row is the **`cells`** row whose **`slug`** matches the catalog **`board_spaces.designs[].id`** (same identifier as **`asset_id`** in **`/api/cell/spaces/{asset_id}`**). **`position_ref`** on the SVG is **not** part of persistence for this feature — all tiles that share a design share one trigger. This matches future layouts where designs can be **moved** on the board without breaking the link.  
- **HTTP `PATCH`:** accept **partial** JSON — update **`space_kind`** only if present, update **`triggers_functional_cell_id`** only if present (same endpoint as today’s space metadata PATCH). Omitting a key leaves that field unchanged.  
- **Authorization:** same rules as **editing the board** (nested board route guards / ownership used for other cell mutations).  
- **Column:** **`triggers_functional_cell_id`** (nullable UUID FK → **`cells.id`**, `ON DELETE SET NULL`).  
- **Catalog note:** `board_games.body_json` still carries **`board_spaces`** / **`feature_panels`** for layout and prompts; the **FK always references `cells.id`**. Materialized `cells` rows are the authority for “which row is this slot” once the app has consolidated catalog into the table.

### 10.3 Export projection

- When the FK is **non-null**, export stage **`interaction_graph`** emits the corresponding edge (e.g. `play_space_animation` / future action types).  
- When **null** or feature **off**, omit the edge or emit an **empty** `interaction_graph` array — both remain valid per **§8**.

---

**Starter example (iterate freely):** `docs/project-export/example-starter-board.json` — illustrative bundle-relative paths, `spaces[]`, `interaction_graph[]` with land → play animation, top-level **`game_engine_instructions`** for engine/LLM handoff, and optional **`consumer_hints.godot`**.

---

*Skeleton for discussion; expand §4–§6 and §9 as bundle export lands. §10 reflects shipped land-trigger behavior.*
