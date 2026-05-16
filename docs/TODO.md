# Product & platform backlog

Tracked improvements and specs not yet implemented. For live architecture, see [architecture.md](architecture.md). Feature specs live under [tech-spec/](../tech-spec/).

---

## Token Factory

- [ ] **Dynamic token palettes from board schema** — Token color palettes appear hardcoded today rather than derived from the linked board’s style/schema (OKLch palette, `style.json`, catalog colors). Investigate wiring `linked_board_id` → board palette pipeline end-to-end so token generation and UI swatches reflect the board the token belongs to.

---

## Cost & time display

The underlying estimates and ledger math are fine; the gap is **how totals are shown**. Today users often see line items or partial figures and have to add things up themselves. We need a consistent, app-wide pattern that always surfaces **rolled-up totals** (cost and time) in plain language.

- [ ] **Session cost refinement** — Clarify what “this session” includes, how it rolls up, and where it appears (tray, board header, factory pages). Users should see one session total, not a puzzle of fragments.
- [ ] **Total cost reset** — Explicit control to reset accumulated totals (define scope up front: current session, per-board, or broader — document in spec).
- [ ] **Standardized cost & time presentation (new tech spec)** — Author `tech-spec/cost-display/spec.md` for **communicating** cost and time across the app (boards, cards, tokens, animations, jobs). Not a rethink of how we *predict* cost — a rethink of how we *display* it. Spec should define:
  - When to show **subtotals vs grand totals** (e.g. one action, one board, whole session)
  - Required **total fields** on every surface that mentions cost or duration (no “add these three numbers” UX)
  - Shared components / copy patterns (labels, placement, currency + duration together)
  - Relationship to the cost ledger (actuals vs pre-run estimates) without forcing mental arithmetic
  - Examples per surface: pre-job confirm, running job, tray, side panel, factory pages

---

## AI providers & keys

- [ ] **Universal AI API key & model management UI** — Single settings surface for API keys and provider/model selection, usable app-wide (not buried per pipeline).
  - Provider toggles (e.g. **OpenAI**, **PixelLab**) with enable/disable per provider when a key is present.
  - **Recommended** badges on models the product prefers for each provider.
  - Per **action category** mapping — which model is default (or recommended) for each class of work, for example:
    - Still images (space/cell draw, card art, token candidates, …)
    - Animation (space loop clips, token clip frames, …)
    - Analysis / vision (if applicable)
    - Other categories as the app grows
  - Persist keys, provider enablement, and per-category model choices in the **database** (per user or per deployment — decide in spec); fail fast when a required provider is off or missing a key.

---

## Specs to write

| Item | Target path | Notes |
|------|-------------|--------|
| Standardized cost & time presentation | `tech-spec/cost-display/spec.md` | Display/communication only; see Cost & time display |
