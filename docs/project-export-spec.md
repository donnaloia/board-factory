# Project export — technical specification (skeleton)

**Status:** Skeleton (planning)  
**Related product:** Board Factory — ship a **portable bundle** (directory, optionally **zip**) of **assets + a single project JSON** for engines, tools, and **LLM-assisted codegen**.  
**Last updated:** 2026-05-09

---

## 1. Summary

Export produces a **self-contained folder** (or `.zip` of that folder) containing:

1. **Binary assets** — still images, optional **space animations** (see `docs/space-animations-spec.md`), frames, mockups, etc., laid out in a **stable relative path** scheme.  
2. **One canonical `project.json` (name TBD)** — maps **logical game objects** (board, spaces, links, rules hints) to **file paths** inside the bundle, plus **game-level metadata** (title, dimensions, palette references, export version).

**Intent:** A developer or **LLM** can read the JSON, discover **what exists** and **where files live**, and emit **engine-specific** code (Godot, Unity, custom WebGL, etc.) without reverse-engineering the Board Factory DB or workspace layout.

**Example relationship (product goal):**  
*Landing on a given **perimeter** space that has a **hidden link** to a **functional UI** space should **trigger that functional space’s animation** (when an animation asset exists).*  
The JSON must be able to express **that graph** (perimeter id → linked functional space id → animation asset path, plus trigger semantics). **Authoring** those links in the side panel is likely **follow-up work**; this spec assumes the **export schema** can carry such edges once they exist in the data model.

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
- Fully defining **side-panel UI** for link authoring in this document (tracked as dependency for populating some edges).

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

- **Meta:** `export_schema_version`, generator app version, exported-at timestamp, board id / slug.  
- **Game:** title, author-facing description, board geometry summary (size, cell grid if applicable — align with existing catalog concepts).  
- **Spaces:** list of space records: id, type/role, paths to **live still**, optional **live animation**, labels, z-order or layer hints if needed.  
- **Graph / triggers:** explicit objects or edges, e.g. `{ "from": "perimeter:...", "to": "functional:...", "kind": "hidden_link", "on": "land", "play_animation": true }` — **field names and enum set are placeholders** until a schema pass.  
- **Provenance (optional):** pointers back to internal `asset_version` ids for support/debug (may be stripped in “public” export mode).

---

## 6. Dependencies on other work

| Dependency | Why |
| --- | --- |
| **Space animations spec** | Export must reference animation files and trigger semantics consistently. |
| **Data model for links** | Perimeter → functional **hidden links** (and “on land” behavior) must be **persisted** before export can emit them; side panel or catalog authoring **TBD**. |
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
- The schema has a **documented place** for **perimeter → functional** relationships and **animation-on-land** intent, even if many bundles emit **empty graphs** until authoring ships.  
- **Schema version** is present and incremented when breaking changes occur.

---

*Skeleton for discussion; expand §4–§6 into tables, schema, and examples as the export job and link model are designed.*
