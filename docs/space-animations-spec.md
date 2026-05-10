# Space animations — technical specification

**Status:** Draft (planning)  
**Related product:** Board Factory — looping clips for **space** (today: *cell*) static art after commit  
**Last updated:** 2026-05-09

### Naming

- **Product:** space animations (short loops for functional board spaces).  
- **Codebase:** the **cells** domain is planned to be renamed **spaces**; this spec uses **space** in prose and keeps **cell** only where it matches current IDs (`cell_id`, paths, DB).  
- **Pipeline sandbox:** isolated package under **`pipeline/`**, parallel to `pipeline/boardfactory/` and `pipeline/cardfactory/` — see **§9**. Stakeholders may say **`pipeline/space-animations`**; the importable Python package directory **SHOULD use underscores** (e.g. **`pipeline/space_animations/`**) so job adapters can `import space_animations` the same way they `import boardfactory`. If a hyphenated folder is required for non-Python assets only, document an explicit import path strategy.

### Domain ownership (application layer)

All **backend** work (FastAPI routes, services, repositories, DB rows linking animations to board spaces and `asset_versions`) should live with the **spaces/cells** domain — today **`app/domains/cells/`**, later **`app/domains/spaces/`** after rename. The **`pipeline/space_animations/`** (or agreed directory name) package stays **image/video pipeline only** and must not grow HTTP handlers — same boundary as Card Factory’s pipeline.

---

## 1. Summary

**Space animations** add an optional second life to **already committed, live** static art for a board space: a **short looping animation** derived from that image, suitable for export and game-engine import.

**Gates:** Animation generation is **opt-in per space** (product explicitly enables the affordance for a given space; all **space types** may participate). It is allowed **only after** that space’s **live** static art is committed — no animation jobs against drafts or non-live versions.

**Exploration pattern:** Match Board Factory’s proven pattern: generate **three** candidate loops per request; user **selects one** as **live**; history and cost attribution follow existing board patterns where applicable.

**Motion continuity:** Prefer workflows where playback **appears** to grow out of the static asset (first frames low-drift from the source PNG) so engine triggers do not feel like a hard cut to unrelated motion. **Slight pixel drift** on early frames versus the static PNG is **acceptable** for MVP.

---

## 2. Motivation

- Boards increasingly ship as **interactive** or **engine-ready** kits; subtle motion on key spaces improves perceived quality without redrawing layouts.
- Keeping animation in a **separate sandbox pipeline** avoids coupling video/I2V concerns to `boardfactory`’s grid, vision, and frame orchestration.
- Reusing the **three-candidate + pick live** pattern reduces new UX risk and matches mental models from space art and frames.

---

## 3. Goals

| ID | Goal | Notes |
| --- | --- | --- |
| **G1** | **Post-commit only** | No animation jobs until the target space has **live** static art committed. |
| **G2** | **Explicit scope** | Only spaces the product **explicitly** allows for animation (any **type** of space may be included; nothing is implied for “all spaces everywhere”). |
| **G3** | **Bounded exploration** | Generate **three** candidates; user picks **one** live loop (proposals + commit, parallel to other asset flows). |
| **G4** | **Engine-friendly motion** | Target perception: **static → fluid motion** when a clip is started from rest; seamless loop **if pipeline allows** (see **§6**). |
| **G5** | **Technical targets** | **~3 s** duration, **30 fps** when the chosen provider/export path supports it; resolution aligned with **source static asset** for that space (exact pixel policy TBD — see **§7**). |
| **G6** | **Acceptable formats** | **GIF** and/or **APNG** (or other common web/game-friendly formats) — **standard formats are acceptable**; final primary format may be chosen during implementation. |
| **G7** | **Isolated pipeline** | Implementation under **`pipeline/space_animations/`** (or hyphenated sibling folder with import strategy); **must not** import from `boardfactory` or `cardfactory` — copy shared primitives or lift to neutral `app/` / future `pipeline/common/` only if both teams agree. |
| **G8** | **Shared platform** | Reuse **app-level** jobs runner, SSE/progress, cost ledger, auth — same spirit as other pipelines. |

---

## 4. Non-goals (initial phase)

- Full **timeline editor**, skeletal animation, or particle systems inside Board Factory.
- **Audio** sync or sound design.
- **Real-time** multi-user co-editing of animation parameters.
- Guaranteeing **pixel-identical** frame 0 to the static PNG (explicitly out of scope for MVP; **slight drift OK** per product).
- Replacing static PNGs; static art remains the **authoritative** still for layouts and catalogs unless product later says otherwise.

---

## 5. User journey (MVP sketch)

1. User finishes static art for a space; asset is **live** and committed.  
2. UI exposes **“Animate this space”** (or equivalent) only for spaces on the **allow list** and only when **live** art exists.  
3. User starts an animation job → pipeline produces **3** candidate loops (files + manifest metadata).  
4. User previews candidates (in-browser preview; format depends on **§8** decision).  
5. User **commits** one candidate → that file becomes the **live animation** for the space; others remain in history.  
6. Export / engine bundle includes the chosen clip alongside static assets according to export rules (TBD).

---

## 6. Loop quality and continuity

### 6.1 Seamless loop

- **Target:** **Seamless** loop (last frames blend visually into the first) **when the provider and post-process stack allow it**.  
- **Fallbacks (to specify in implementation):** short crossfade **last → first**, ping-pong, or gentle **dissolve to static** at the boundary — document which is acceptable for MVP in the same ticket that locks the provider.

### 6.2 Static → motion

- **Intent:** In a game engine, triggering the clip should read as **the same illustration beginning to move**, not a unrelated video.  
- **MVP tolerance:** **Slight drift** from the static PNG in early frames is OK; avoid large composition changes or camera reframing unless explicitly requested later.

### 6.3 Style lock and palette (optional conditioning)

- **Hypothesis:** Feeding **style lock / palette** (or equivalent board-level constraints) **may** improve temporal consistency with the source still.  
- **Spec position:** Treat as **experimental** — implementation should allow passing resolved palette/style **parameters** into the animation pipeline **when cheap**, but **must not** block MVP on proving measurable gain. A/B or qualitative review can decide whether conditioning stays on by default.

---

## 7. Duration, frame rate, and resolution

| Parameter | Target | Notes |
| --- | --- | --- |
| Duration | **~3 s** | Per clip; exact frame count = `duration_s × fps` (e.g. 90 frames at 30 fps). |
| Frame rate | **30 fps** | If export or API forces a different rate, document conversion (dupe/drop) in manifest. |
| Resolution | **Match static space art** | Default assumption: clip dimensions match the **live PNG** (or canonical export size) for that space; downscaling for preview-only is allowed if **committed** asset stays full-res — **confirm in implementation**. |

---

## 8. Provider and generation strategy (**decisions pending**)

The following are **explicitly not decided** in this draft; implementation tickets must pick options and update this section.

| Topic | Options to evaluate (non-exhaustive) |
| --- | --- |
| **Primary API** | Image-to-video (I2V), video diffusion with image conditioning, multi-frame img2img, third-party animation APIs, etc. |
| **First-frame anchoring** | Strong image conditioning vs explicit “frame 0 = resize(static)” composite vs hybrid. |
| **Loop closure** | Model-native loop vs post crossfade vs trim to best cycle. |
| **Output encoding** | GIF vs APNG vs both; color quantization for GIF; alpha preservation needs for spaces with transparency. |
| **Cost / latency** | 3× ~3 s clips per user action vs sequential; provider limits on length and resolution. |

**Requirement:** The chosen approach must be described in **ARCHITECTURE.md** (or this doc) once locked, including **failure modes** (e.g. provider returns shorter clip) and **manifest fields** (`provider`, `model`, `fps`, `frame_count`, `source_asset_version_id`, etc.).

---

## 9. Repository layout and isolation

- **`pipeline/space_animations/`** — **sandbox** animation pipeline only (`ops/`, `steps/`, `providers/` as needed). **No** `from boardfactory import …` or `from cardfactory import …` inside this tree.  
- **`app/domains/cells/`** (future **`spaces/`**) — routes, services, repository, models for “which spaces may animate,” job enqueue, linking **live animation** to `asset_versions` / space rows.  
- **`app/jobs/`** — new adapter functions that invoke the sandbox pipeline with the same progress/cost patterns as existing adapters.

**Rationale:** Pipelines sit **in parallel** as explicit sandboxes rather than nesting under a shared `pipeline/boardfactory/...` subtree — matches stakeholder direction for this feature.

---

## 10. Data model sketch (follow-up ER pass)

Expected relationships (exact columns TBD):

- **Space** (cell) → optional pointer to **live animation asset** (new `asset_versions` kind or sibling table).  
- **Proposal set** — batch id tying **three** candidates to one job + source `live_asset_version_id` of the static still.  
- **Manifest** on disk (workspace) — candidate paths, hashes, fps, duration, encoder, `proposal_index`, `committed` flag.

---

## 11. API / UX sketch (non-binding)

- **HTML:** from space sidebar or detail — “Animate” after live still exists; gallery of 3 → commit.  
- **JSON / SSE:** consistent with existing job polling for board pipelines.  
- **Authorization:** same as editing the board; animation uses the board’s style inputs only if the user could already view that board.

---

## 12. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Loops not seamless | Post-process crossfade or accept soft seam for MVP; document in UX. |
| Large files (APNG/GIF at full res × 90 frames) | Preview downscale; optional WebM later if product wants. |
| Drift breaks “same asset” feel | Keep motion subtle; optional strength slider later. |
| Provider inconsistency across 3 candidates | Same seed / conditioning where API supports it; manifest records parameters. |
| Code duplication vs `boardfactory` | Accepted trade for isolation; extract **only** battle-tested neutral helpers if duplication hurts. |

---

## 13. Open questions

1. **Allow list** — Who sets “this space type / this space may animate”: catalog flag, UI toggle, or both?  
2. **Multiple loops per space** — MVP = **one** live animation per space, or allow variants (e.g. idle vs active)?  
3. **Export** — Single format in ZIP vs multiple; engine-specific sidecars.  
4. **Rename timeline** — Does **cells → spaces** land before or after animation MVP (affects route and import paths)?  
5. **Downscaled preview** — Always generate full-res only, or dual outputs?

---

## 14. Success criteria (MVP)

- User **cannot** start animation generation for a space without **live** static art.  
- For an enabled space, user receives **three** candidates and can **commit one** as live.  
- Output plays as a **short loop** with targets **~3 s** and **30 fps** when technically feasible.  
- **Provider and encoding decisions** are recorded after implementation kickoff (**§8** cleared).  
- Pipeline lives in **`pipeline/space_animations/`** (underscore import path) with **no** imports from other pipeline sandboxes.

---

*This document is the starting point for implementation tickets; revise §8 and §13 as decisions land.*
