# Board plate — incremental cell updates (planned)

**Status:** Design note — not implemented  
**Relates to:** Bulk generation (`generate.all` / `generate.spaces`), `side-panel.js`, `jobs.js`, SSE job stream

## Problem

Today the board refreshes by **replacing the entire `#board-plate`** HTML (full board page fetch + parse) on a throttle, or by **full page reload** after certain jobs. That is heavy, interacts badly with an **open sidebar** (deferral logic tries to avoid starving `/api/cell`), and still fails to give **per-cell** feedback as each asset lands.

**Goal:** Update **only** the cells whose assets changed, **without** relying on full-plate swaps or mandatory reloads — especially **while the sidebar stays open**.

## Approach (step 4 — incremental DOM updates)

1. **Single source of truth for “what changed”**  
   When a space/panel/centerpiece finishes generating, the client needs a stable **`(category, asset_id[, position]) → live asset URL`** (with optional cache-bust). Sources could include:
   - enriched **SSE job payloads** (last-completed cell + URL), and/or  
   - a small **`GET /api/...`** that returns only dirty cells since `revision`, if we want strict polling.

2. **Targeted SVG / DOM patch**  
   Find the corresponding `<image>` (or equivalent) in the **existing** board SVG and set **`href`** / **`xlink:href`** with a cache-busting query param. No full `#board-plate` replacement for those updates.

3. **Fallback**  
   Keep full-plate refresh or reload as a **fallback** when structure changes (new cells, layout edits) or when incremental patch fails.

4. **Sidebar coexistence**  
   Incremental updates avoid large HTML refetches, so they **should not** compete with `/api/cell` the way full-plate refresh does — reducing the need to defer updates when the panel is open.

## Pipeline boundaries (non-negotiable)

**Any change that touches `pipeline/boardfactory/` (or future pipeline packages) requires extra scrutiny.**

- The pipeline owns **image generation, promotion to live, catalog/workspace semantics**, and **cost/accounting**.  
- **Frontend convenience must not drive pipeline design.** Do not add hooks, fields, or coupling in the pipeline solely because the browser wants a prettier update cadence — unless the same contract is justified for **CLI**, **tests**, and **other callers**.

Prefer:

- **Stable domain events** already emitted today (e.g. asset promoted → URL known), surfaced through **app layer** (`domains/cells`, `jobs`, SSE) to the browser; or  
- **Thin adapters** in **`app/`** that subscribe to existing outcomes and forward minimal facts (`asset_id`, `live_url`, `version`) to SSE.

The pipeline stays **UI-agnostic**; the web tier translates outcomes into **incremental patch instructions** for the plate.

## Open questions (for later iterations)

- Exact shape of SSE enrichment vs dedicated lightweight API.  
- Matching SVG nodes reliably (`data-asset-id`, `data-category`, position refs).  
- Interaction with frame overlay, centerpiece, and preview composite jobs.  
- Rate limiting / batching when many cells finish per second.
