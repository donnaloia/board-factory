# TODO issues (backlog)

Tracked UX / product / technical debt items. Open items first; completed items are listed at the end without descriptions.

---

### 1. Read timeout during space generation

Occasionally when generating a space, the UI shows **FAIL: the read operation timed out** (likely client or upstream HTTP timeout vs. job still running). Investigate timeout configuration, retries, and alignment with long-running provider calls.

---

### 2. Translucent backgrounds or elements in generated spaces

Occasionally generated space images have **translucent backgrounds** or **translucent elements**. Tighten post-processing / alpha handling, provider prompts, or cleanup so outputs are consistently opaque where the catalog expects solid pixels.

---

### 4. Frames: product / pipeline overhaul

**Complete rethink of house frames:** today the flow relies on cropping a **perfectly rectangular** frame from panels or mockup slices. Explore whether **the model can infer “what is the frame”** (or other UX) so we are not dependent on brittle rectangular crops and manual frame plumbing.

---

### 5. Clone board

Add **clone / duplicate board** (new board id, copy catalog + assets or defined subset, ownership row, `path_slug`), with clear UX and storage semantics.

---

### 8. AI board review

**AI board review** feature: have the model review the board for:

- **Gameplay ideas** grounded in the current board design, and  
- **Visual design** analysis with actionable feedback,

using the live catalog / mockup / composite as context.

---

### 10. Tech spec: animation for spaces

Author a **technical specification** for introducing **animation** to board spaces (data model, catalog schema, pipeline/export implications, engine consumption, and UI/preview behavior). Scope what “animation” means per space kind (e.g. idle/active, frame strips, timing) and how it composes with existing active-state / export work.

---

### 11. Document “demo board” / how boards attach to users

**Questions to resolve and document:**

- How does a **demo** (or seed) board end up on **each** user’s account — if at all?
- Does it happen **during user registration**?
- Where is the board **copied from** on disk or in the DB?
- Does a row **already exist** in the database and get **cloned** with a new id / user id?

**Known behavior today (code survey — verify against your deployment):**

- **Registration** (`POST /register`) only runs when **`users` is empty** (`is_setup_required()`). After `create_first_user`, the app calls **`assign_all_unowned_disk_boards_to_user(user.id)`** (`auth.py` + `board_ownership.py`).
- That function **does not clone** catalog rows or copy `data/boards/` directories. It scans **`bf_boards.list_boards()`** (on-disk board dirs) and, for each board id **missing** an `owned_boards` row, inserts **`OwnedBoardRecord`** linking that existing **`board_id`** to the new **`user_id`** (with a fresh **`path_slug`**). **One physical tree per `board_id`; ownership is relational.**
- **Startup:** `backfill_owned_boards_if_empty()` assigns **all** unowned disk boards to the **oldest user** if `owned_boards` is empty but users exist (`bootstrap.py`).
- The setup UI **“Demo”** tab is still **placeholder** (“Coming soon”) — no automated demo clone there yet.
- **Second and later users:** `/register` is **closed** once any user exists, so **new accounts do not** currently receive boards via this path unless you add multi-user registration + separate cloning logic.

**TODO:** Confirm against Postgres snapshots / team workflow (e.g. shared dump + `data/boards/`) and update README or architecture docs so expectations match implementation.

---

### 12. Clone “demo cake” board for each new user

Build a **system to clone the demo cake board** (or defined seed template) **for every new user**: new `board_id`, copied `data/boards/<id>/` tree (via `BoardStore`), duplicated / imported catalog (`board_games` / body_json), `owned_boards` row with `path_slug`, and clear UX (e.g. on signup or first login). Depends on opening multi-user registration if new users are created after the first account, and on picking the canonical source board id (“cake”) and keeping it maintained as the clone template.

---

### 13. Unify `cells.kind` terminology: `space` → `perimeter`, `panel` → `functional`

**Goal:** align DB discriminator values and product language — **`cells.kind`** today uses **`space`** (perimeter / board-space designs) and **`panel`** (feature UI regions); rename to **`perimeter`** and **`functional`** (keep **`centerpiece`** or rename in same pass if desired).

**Work:**

- **Migration:** update `cells.kind` CHECK constraint and **rewrite existing rows** (`space` → `perimeter`, `panel` → `functional`); chase any **FKs / CHECKs** that embed the old literals (e.g. `frame_instances.source_kind`, pipeline or job enums, raw SQL).  
- **Codebase sweep:** Python, templates, static JS, routes (`/panels/…` vs future naming), `board_svg` categories, `domains.spaces`, `domains.boards`, `jobs/pipeline_adapters`, pipeline `boardfactory`, docs (`project-export-spec`, ARCHITECTURE), and **any API** that exposes `kind` to the client.  
- **Docs & naming clarity:** document (model docstrings, `ARCHITECTURE.md`, cells README or inline comments) that **`cells.kind`** is the discriminator for **perimeter vs functional UI vs centerpiece** — not **`space_kind`**, which only distinguishes **`standard` / `event`** on **space-type** rows and says nothing about “panel vs perimeter.”** There is **no** `space.kind` column; avoid that label in APIs and specs so it is not confused with **`cells.kind`** or **`space_kind`**. Align any JSON that accidentally used `space.kind` with the real ORM fields.  
- **Compatibility (optional):** short-lived read shim or API version bump if external consumers depend on old strings.

---

## Completed (titles only)

### 3. Side panel scroll position when switching cells

### 6. Sidebar prompt vs. selected history image

### 7. Regenerate: “6 candidates” vs. 3 in history / billing (OpenAI)

### 9. Board SVG reverts after history pick until full reload
