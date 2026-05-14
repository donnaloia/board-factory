# Board token characters — art direction & implementation guidance

**Status:** Product / design notes (not locked engineering spec)  
**Context:** Candy-themed pixel mockup boards (perimeter dessert tiles, centerpiece “marquee,” functional UI panels). Tokens are **full-body characters** that **move along the perimeter** when dice resolve, with **walk / float / fly** locomotion variants.  
**Technical brief (camera angle, frame budgets, AI workflow, smooth loops, idle): §3.**

---

## 1. What to design (character concepts)

### 1.1 Fit the board’s vocabulary

Your mockup already shows three “character” idioms:

- **Anthropomorphic treats** (donut, strawberry, etc.) — round or simple silhouettes, big readable faces, thin limbs. Strong fit for **bouncy walk**, **float**, or **hover**.
- **Humanoid “candy people”** (e.g. dealer / shopkeeper vibe) — closer to **walk cycles** and **direction changes** if you ever show facing.
- **Mascot-scale icons** (crying tooth, small props) — can work as tokens but read more “prop” than “player pawn”; use only if you want comedic or thematic contrast.

**Recommendation:** Default player tokens should read as **peers of the perimeter art**—same kawaii pixel craft, **silhouette readable at ~1/4–1/6 of a tile width** on a 1920×1080 board so they don’t erase the dessert illustration underneath.

### 1.2 One locomotion profile per token (for MVP)

| Profile | Best for | Motion read at a glance |
|--------|----------|-------------------------|
| **Walk** | Grounded creatures, humanoids, anything with feet | 4–8 frame cycle, slight vertical bob |
| **Float** | Round blobs, ghosts, stacked treats, magic | Idle bob + horizontal drift; few frames |
| **Fly** | Wings, drones, small birds, “lifted” sweets | Wing flap or tilt; optional shadow under token |

Avoid assigning **both** walk and fly to the same MVP asset unless you plan **state machine + two clip sets** in engine.

### 1.3 Palette and outline

- Stay inside the board’s **pastel + chocolate + cream** range; reserve **one accent** per player (mint, lemon, berry) for multiplayer readability.
- **Single-pixel outline** (or selective outline on limbs) matches typical mockup tiles and separates the token from busy tile art.

---

## 2. Scale and composition rules

1. **Foot / base contact:** Design a clear **contact point** (shadow oval, feet, or cloud) so programmers can anchor the sprite to “center of tile” or “center of cell rect” without guesswork.
2. **Vertical extent:** Full-body tokens will overlap neighbors. Cap **height** so that on the **smallest perimeter cell** the head/crown does not routinely occlude the **next** cell’s readable zone—unless you want Deliberate “tall pawn” fantasy.
3. **Direction:** Decide early: **only side-view** (flip for left/right), **four-direction**, or **8-direction**. Side-view + flip is cheapest for MVP **only if the perimeter path is treated as purely horizontal on screen**; boards with **vertical** edges between cells need **walk up / walk down** (or full 4-way) clips—see **§3.8**.

---

## 3. Technical specification — camera, frames, smoothness, AI

This section is the **practical animation brief**: angles, frame budgets, how to produce clips (including generative AI), and how to keep motion readable and smooth.

### 3.1 Camera angle (match the token to the board)

Perimeter tiles in typical mocks read as **slightly top-down / isometric** (you see a bit of the dessert’s upper surface). Functional panels often read **more frontal**. For a **single token rig** used on the **path only**:

| Choice | When to use | Notes |
|--------|-------------|--------|
| **Side view (2D, orthographic)** | **Recommended MVP** — one walk/float cycle, **flip X** for direction | Camera is “infinite ortho”: no perspective warp. Easiest to keep pixel scale consistent. |
| **¾ view (oblique)** | Token should “sit” on the same plane as tiles | Body leans **slightly back** (10–20° from pure side) so feet read on the “ground” plane; harder with AI + pixel cleanup. |
| **True isometric** | Rare for small pixel pawns unless whole game is iso | Requires **diagonal** walk or step variant; doubles art cost. |

**Lock one convention per project:** e.g. “token is **side-view**; **shadow ellipse** sells contact with the tile; we do **not** try to match every tile’s micro-perspective.”

### 3.2 Frame counts (rules of thumb)

These assume **pixel art** at modest size (e.g. **64–128 px tall** token, **12–24 fps** in-game; can show at 2× scale).

| Animation | Frames (loop) | FPS (typical) | Notes |
|-----------|----------------|---------------|--------|
| **Walk** — minimal | **4** | 10–14 | “video-game cheap”; good for chibi; reads as **march** more than walk |
| **Walk** — solid | **6** | 12–16 | Common sweet spot for indies |
| **Walk** — polished | **8** | 12–18 | Full contact / passing poses; more AI/cleanup work |
| **Float / hover move** | **4–6** | 10–14 | Often **2–3 unique drawings** + slight offset reuse; vertical bob is the main read |
| **Fly** (flap) | **4–6** | 12–16 | Wing symmetry allows mirroring half-cycle |
| **Idle — breathing** | **4–8** or **2** (ping-pong) | 8–12 (slow) | Subtle: **1–2 px** vertical shift of whole body + **1 px** chest squash; slower than walk |
| **Idle — hover** | **4–6** | 8–12 | Sine-like **Y** motion ±2–4 px; optional **shadow** scale 95–100% |

**Seamless loop:** walk cycle frame 0 and last frame should be **near identical** (often duplicate key or interpolation target). For pixel, artists often use **frames 1–N** with frame **N** merging into frame **1** on twos.

### 3.3 Walk cycle structure (what each frame is doing)

For a **6-frame** side-view walk (example):

1. **Contact** — front foot down, back foot off ground  
2. **Passing** — legs cross, body highest  
3. **Contact** — opposite foot down  
4–6. Mirror or complement of 1–3  

**Bob:** body **lowest** at double-contact (both feet grounded), **highest** at passing—about **1–3 px** amplitude for small sprites.

### 3.4 “Resting on space” (idle)

- **Breathing (grounded):**  
  - **Scale:** width ±0–1%, height **98–102%** over cycle (very subtle in pixel—prefer **translate Y** + **manual pixel nudge**).  
  - **Timing:** **longer** than walk (e.g. **0.8–1.4 s** per full breath loop).  
  - Optional: **blink** every 3–5 s (2-frame) sold separately so loop stays calm.

- **Hovering (float token):**  
  - **Position:** smooth **vertical oscillation** (engine can drive with `sin(t)` on **1 axis** using a **single static sprite**—no art needed—or **4–6** hand-drawn heights for organic pixel feel).  
  - **Shadow:** softer oval, **scale or opacity** tied to height (higher = smaller/dimmer shadow).

Use **a different idle** than **move loop**: if walk and idle are too similar, the pawn looks “jittery” when stopped.

### 3.5 Smoothness (art + engine)

**On the art side**

- **Consistent silhouette** per frame (limb lengths don’t grow/shrink between frames unless deliberate exaggeration).  
- **Single pivot** (ankles / shadow center): register all frames to the **same anchor** in the canvas (sprite sheet packed with **transparent padding** is fine).  
- **Color stability:** avoid per-frame hue shifts from denoise unless intentional.  
- **Pixel cleanup pass** after AI: unify outlines, remove **flickering** single-pixel islands (use onion-skin / difference overlay in Aseprite, Photoshop Timeline, or Pixelorama).

**On the engine side**

- **Integer positions** for final draw where possible (crisper than subpixel drift); or **round** draw position when camera is static.  
- **Easing:** movement between cells often looks best as **ease-in-out** on **position**, while **animation playback** stays **linear** (constant frame rate).  
- **Sync:** either **N fixed steps** per cell (play **one full loop** per hop) or **loop until** arrival (time-based)—pick one and document it.

### 3.6 Generating with AI (workflow that stays on-model)

AI is strong for **exploration**; **smooth loops** usually need **a locked reference + manual/slight edit pass**.

1. **Establish “source of truth”**  
   - One **T-pose or idle** orthographic turn (~side). Same **aspect ratio** as final export.  
   - Written **style lock**: “pixel art, N-bit palette, black outline, chibi, no depth of field, no motion blur.”

2. **Generate key poses first** (not 8 random frames)  
   - Ask for **contact / passing / contact** silhouettes **side view**.  
   - Or generate **short video** and **pull 4–6 stills** at consistent intervals—**risk**: perspective drift; **mitigate** by **img2img** with high strength lock to frame 1.

3. **Interpolation (optional)**  
   - Some tools interpolate between key images; for pixel, export to sheet and **redraw** ambiguous middle frames.

4. **Palette merge**  
   - **Reduce** to a shared palette (e.g. 16–32 colors + transparency) across **all** frames so nothing “sparkles” frame-to-frame.

5. **Quality bar**  
   - Play loop at **target fps** at **target zoom** next to a **static tile**; reject loops where feet **slide** on the ground (slide = bad contact frames or wrong spacing).

**Providers / tools (non-exhaustive):** image models for keys + editor; video models for reference only; **ControlNet** / pose sticks if you need stricter limbs; local **pixel editors** for final authority.

### 3.7 Deliverable checklist (technical)

- [ ] **Canvas size** per frame (fixed W×H, e.g. 96×128).  
- [ ] **Pivot** `(px_x, px_y)` from top-left, stable across all frames of a clip.  
- [ ] **Frames** + **fps** per clip (`walk`, `idle_breath`, `idle_hover`, …).  
- [ ] **Loop points** (start/end frame indices; confirm seamless).  
- [ ] **Direction policy** (flip-X allowed? need back-facing set?).  
- [ ] **Shadow** art or engine-drawn ellipse (size relative to token).

### 3.8 Vertical perimeter steps — walk up & walk down

The doc already recommends **side view + flip-X** for **horizontal** moves along the path. That **does not** cover steps where the **next cell is above or below** the current one on screen: the same side-view cycle will look like the character is **walking sideways** along a vertical track, which reads wrong for most full-body rigs.

**When you need separate clips**

- **Grid / lattice boards** with **up** and **down** edges (orthogonal steps along screen Y).  
- **Irregular perimeters** where two adjacent tiles differ mainly in **Y** in board pixel space (e.g. a column of “battle” cells along one edge).

**What to author**

| Clip (logical) | Typical pixel read | Frame budget |
|----------------|-------------------|--------------|
| **walk_horizontal** (or `walk_side`) | Side view; **flip X** for left vs right | Same as §3.2 (e.g. **6–8** frames) |
| **walk_up** | **Back** or **¾-back** (player sees crown of head, shoulders up) | Same count as horizontal **or** slightly fewer if you **reuse** bob with new angle |
| **walk_down** | **Front** or **¾-front** (face toward camera) | Same |

**Cheapest compromises (MVP)**

1. **Hybrid:** keep **one** side-view walk for **horizontal** hops; use **dedicated short clips** (even **4 frames**) only for **vertical** hops, or  
2. **Translate only:** keep a **single** side walk and slide along the edge—cheap but **weak** for full-body characters; better for **float** tokens where facing is ambiguous.  
3. **No bespoke art:** **rotate** the whole sprite ±90° for vertical steps—not true pixel orthodox but sometimes acceptable at **tiny** sizes (usually ugly for outlined pixel art).

**Float / fly tokens** often get away with **one** move loop for all directions (bob + world-space motion carries the read); **grounded** walkers benefit most from **up/down** (or full **4-direction**) sets.

**Engine note:** pathfinding should tag each hop with **`edge_kind`: horizontal | vertical_up | vertical_down** (or angle bins) so the animator picks the right clip.

### 3.9 Color, palette, and visibility on a designed board

Tokens sit **on top of** art you already tuned (perimeter tiles, centerpiece, chrome). **Reusing the board palette as the token’s only colors** often makes the pawn **disappear**—same hue range, same value band, same candy pastels. Treat the **board palette as harmony, not a copy-paste**.

**Principles**

1. **Separate “figure” from “ground” in value** — Perimeter tiles are usually **mid** lightness with busy detail. Give the token body a **clearly different average luminance** than the dominant tile it stands on (often **slightly darker** body + **lighter** face/highlight, or the reverse), so it reads at thumbnail scale.
2. **One controlled accent** — Use the **decided policy in §3.9.1** so a **primary accent ramp** is **computed** from the board (not invented in prose by an LLM). The rest of the token stays **lower chroma** so it doesn’t noise the board.
3. **Warm/cool offset** — Often **falls out of §3.9.1** automatically (split-complement vs mean hue). If the board is extremely **warm**, optionally **bias** the primary-accent candidate set toward **cooler** octants before the distance test.
4. **Outline and rim light** — A **1–2 px** outline (or **keyline** only on silhouette breaks) is the cheapest visibility win on busy tiles. Optional **1 px** inner highlight on the sun side sells volume without full rim light passes.
5. **Multiplayer = read shape first** — **P2–P4** should differ by **silhouette accessory** (hat, scarf, prop) or **trim strip**, not only hue—**color-blind** safety and zoom-out readability.
6. **Test on real composites** — Place the token over (a) **busiest** perimeter tile, (b) **centerpiece** edge, (c) **functional panel** corner. If it survives all three without “is that part of the tile?”, the palette is working.

**What not to do**

- **Don’t** average the board palette and recolor the whole token to that mean—you’ll recreate the blend problem.  
- **Don’t** rely on **glow** alone for separation (expensive, inconsistent export); prefer **value + outline**.

**Pipeline note:** You can still **quantize** the token to a **small custom palette** (e.g. **dozen–ish colors**) so every frame shares the same **style lock** as the board—without painting the pawn in the **same** colors as the desserts.

#### “Board neutrals + a dedicated token accent ramp” — spelled out

**Board neutrals** (in this phrase) are **low-chroma, shared “infrastructure” colors** that already **feel** like they belong on *this* board, but are **not** the loud, decorative colors of individual tiles:

- Examples: **warm gray** or **wheat** for “dough” or fur; **soft cocoa** or **taupe** for shadows; **cream** or **ivory** for highlights; **dusty rose** or **mushroom** for mid-tones—not the **saturated** pinks, mints, and sprinkles that cover each perimeter illustration.  
- Think: **the paper the illustrations sit on**, not **the ink of every sticker**. Those neutrals **harmonize** with the board (same temperature family as your mockup) so the token still feels **on-theme**, but they **don’t compete** with tile art pixel-for-pixel.

**Dedicated token accent ramp** is a **short ladder of one hue** (often **4–6** swatches from **dark** → **mid** → **light**) reserved for **small, intentional accents** on the pawn only:

- Examples: a **computed** hue family (see **§3.9.1**) for a **ribbon, collar, or trim**; **“Ramp”** means **shadow / base / highlight** of *that one hue family* so folds read 3D without opening the full rainbow.  
- **Rule of thumb:** **most** of the token’s pixel count stays on **neutrals**; **ribbon / trim / props** use **`accent_primary`**; **eyes / tiny glints** use **`highlight_neutral`** (§3.9.1)—so the pawn **pops** as a **figure** without becoming a second busy tile.

**Why not “just use the board palette”?** The exported **board palette** often includes **every** loud tile color. If the token uses those same swatches across its whole body, it **inherits the same visual noise** as a macaron tile. **Neutrals + one ramp** deliberately **withhold** the loudest tile colors from the body mass and **spend** chroma only where the eye should go.

#### 3.9.1 Decided policy — agent-safe accent colors (math, not color names)

**Problem:** Asking an LLM for “butter-yellow catchlights” is **not reproducible** and it has **no grounded link** to your board. **Decision:** **compute** a small allowed swatch list in code from **board palette / style data**, then **inject** that list into the prompt (or **quantize** outputs back to it). The model **chooses placement**, not **hex values**.

**Color space:** Prefer **OKLch** (or **Oklab** → sRGB) so **L** and **C** steps look even to the eye. HSL is an acceptable fallback if documented the same way.

**Inputs (per board)**

- `H_mean` — circular mean of **hue** from **lower‑chroma** swatches (e.g. exclude the top fraction of palette entries by chroma so “sprinkle pinks” don’t drag the mean).  
- `Forbidden` — hues of **high‑chroma** swatches (tile “inks”). Used only to **penalize** collisions for the **primary** accent.

**Slot A — `accent_primary[]` (ribbon / trim ramp)**

1. Candidate hues (tunable constants): e.g. **split‑complement band** `H_mean + 165° … H_mean + 195°`, plus **triad** `H_mean + 120°`.  
2. **Score** each by **minimum circular hue distance** to every `Forbidden` hue; pick the **winner** → `H_accent`.  
3. Build **4–6** steps: fix `H_accent`, vary **L**, cap **C** at `C_max` → export **`accent_primary[]`** as hex.

This uses **hue‑wheel geometry + separation**, not **RGB invert** (unstable for art direction).

**Slot B — `highlight_neutral[]` (eyes, sugar glints, foil pixels)**

**Decision (default):** **no second saturated hue** from the model.

- Build **2–3** colors: **high L**, **very low C**, hue **nudged** toward `H_mean` (e.g. **±15°**) so it isn’t dead gray if the board is warm.  
- Use **only** on **tiny** areas (catchlights, glints). **Visually:** bright “wet sugar” dots, not a second costume color.

**Optional “loud” second ramp** (`accent_micro[]`, off by default)

- Only if product enables it: `H_micro = H_mean + 25°` (short **analogous** step), **`C ≤ 0.7 × C_max`**, and **area budget** (e.g. under ~8% of sprite pixels in post‑check). Still **computed**, not LLM‑picked.

**What the agent receives**

A **`token_palette.json`** (or equivalent prompt block) **before** image gen:

```json
{
  "body_neutral": ["#…", "…"],
  "accent_primary": ["#…", "…", "…", "…"],
  "highlight_neutral": ["#…", "#…"]
}
```

Instruction: **“Use only these hexes: body → body_neutral; ribbon/trim → accent_primary; eye/glint pixels → highlight_neutral.”** Optional: remap any out‑of‑palette pixel to nearest allowed swatch.

**Why not “complement” or “inverse” as the only rule?**

- **180° complement** of a warm board is often **cyan** — it **can** win the candidate **if** it scores best against `Forbidden` and **`C` is capped**; do **not** use complement **alone** without the distance test or you get clashing neon.  
- **Per‑pixel RGB inverse** of the background is **out of scope** — undefined for a character and not style‑stable.

**Tuning:** If every candidate loses against `Forbidden`, widen the candidate list (e.g. add `H_mean + 90°`) or shrink `Forbidden` to top‑**K** chroma swatches — ship as **pipeline config constants**.

#### What it looks like on the board (visual read)

Imagine your **candy perimeter**: lots of **pastel pinks, creams, sprinkles, and brown crust** in each cell.

- **Without this approach:** A pawn colored like a **mini macaron** (same pink as the tiles) reads as **another decoration on the dessert**—easy to lose at a glance.  
- **With board neutrals + accent ramp:** The character’s **body** is mostly **warm cocoa / cream / soft gray-brown** (still “edible” and on-theme, but **calmer** than the tile behind it). The **primary accent** (ribbon, sash, etc.) uses **3–4 steps** along the **computed** hue from **§3.9.1**. **Eyes / catchlights** use the **highlight slot** (§3.9.1 — usually **high L, low C**, not a second random hue). A **dark outline** separates the silhouette from the busy frosting behind it.

**At a distance:** you see a **small, darker/cleaner silhouette** with **one stripe of controlled chroma** (the computed **`accent_primary`**) on a **louder** tile—the pawn reads as **“object in front”**, not **“part of the pattern.”** Zoomed in, it still **belongs** to the same candy world; it just **doesn’t paint with the tile’s loudest inks**.

#### Louder without looking “wrong” (still candy / board-native)

Use **one or two** non‑hue tricks, or enable **`accent_micro`** from §3.9.1 — do **not** ask the model for new color names.

| Idea | What it is | Tie to §3.9.1 |
|------|------------|----------------|
| **“Foil” or sugar specular** | **2–4 px** glints | Use **`highlight_neutral`** only. |
| **Toy-plastic rim band** | **2–3 px** ring on silhouette | May use **darkest `accent_primary`** or **outline** swatch — still from JSON. |
| **Orderly pattern vs organic tile** | Stripes / dots / knit | Geometry, not extra hue. |
| **Player base / standee ring** | Disc under feet (P1–P4) | **Preset** player colors outside token JSON, or **desaturated** triad from `H_mean`. |
| **Bumped chroma on neutrals only** | Slightly richer body neutrals | Recompute **`body_neutral[]`** with higher **C**, same **H** band as board. |
| **One-sided rim light** | **3–5 px** limb read | **Lightest** `accent_primary` or `highlight_neutral` strip. |
| **Slightly larger eyes** | Bigger catchlight read | **`highlight_neutral`** + dark outline. |

**Engine (non-art) helpers:** soft **drop shadow** under pawn; **1 px** contact ring (not in sprite).

---

## 4. Animation deliverables (what to ask artists for)

### 4.1 Minimum clips for “move N spaces”

- **Locomotion loop** (walk / float / fly) — seamless loop, **fixed duration per cell** or **normalized** so engine can scale speed.
- **Idle** on a space — subtle motion so the board doesn’t feel frozen.
- **Optional:** “land” / “arrive” squash (1–2 frames) for juice when movement ends.

### 4.2 Technical formats (to decide)

- **Sprite sheet + JSON** (frame rects, pivot, fps) — common for pixel art pipelines.
- **Single PNG strips** per animation — simple but easy to mis-align pivots.
- **Skeletal 2D** — flexible but may fight strict pixel grid unless disciplined.

**Recommendation for Board Factory–style boards:** **Pixel art → raster sprite sheets**, **integer scaling**, **shared pivot** at feet/shadow center.

---

## 5. Implementation questions (answer these for “best possible” integration)

### 5.1 Engine and runtime

- Which **runtime** consumes exports (e.g. Godot 4, Unity, custom Web)? That dictates clip naming, pivot, and z-sorting.
- Is movement **grid-snapping** only, or **smooth interp** between cell centers? (Affects whether loops must sync to **time** or **distance**.)

### 5.2 Data model

- Are tokens **per player**, **per board**, or **catalog assets** (like spaces/panels)? Do you need **Cosmetic-only** vs **Gameplay** stats on the token?
- Should **token choice** be stored in **catalog JSON**, **player profile**, or **save game** only?

### 5.3 Art pipeline

- Will tokens be **generated** (model + provider) or **authored** (Aseprite / commissioned)? If generated, do you require **consistent size** and **palette lock** per board theme?
- Do you need **normal maps / lights** or strictly **flat pixel**?

### 5.4 Perimeter geometry

- Perimeter cells can differ in **aspect ratio** and **position**. Does the token **scale per cell**, **stay fixed world size**, or **scale to shortest edge**?
- When the camera **zooms** (device preview, editor), should token scale follow **UI scale** or **world scale**?

### 5.5 Multiplayer and readability

- Max **simultaneous tokens** on one cell? (Stacking offset vs single-cell rule.)
- **Color-blind** cues beyond hue (shape, outline pattern, hat accessory)?

### 5.6 Audio / VFX (optional)

- Footsteps vs “sparkle” vs “whoosh” per locomotion profile—worth specifying if animation is sold on **sound**.

---

## 6. Suggested MVP scope

1. **One locomotion profile** per token type (walk *or* float *or* fly).  
2. **Side view + horizontal flip** for **horizontal** path steps; add **walk_up / walk_down** (or full 4-way) if the board has **vertical** perimeter hops (§3.8).  
3. **Single shadow ellipse pivot** shared across clips (or per clip if you must).  
4. **One idle + one move loop** (per direction set); optional 2-frame arrival squash.  
5. Export contract: **frame size**, **fps**, **pivot in pixels**, **cells traversed per second** baseline.  
6. **Player tints** or **small accessory** for P2–P4 instead of four fully unique rigs at first.

---

## 7. Open questions checklist (fill in before locking spec)

- [ ] Target engine and resolution policy (integer scale, max zoom).
- [ ] Grid model: **center-to-center** movement vs path following **waypoints** on irregular perimeters.
- [ ] Can multiple pawns share a cell? If yes, **fan-out offset** algorithm?
- [ ] Token catalog: **how many unique characters** at launch vs recolors?
- [ ] **Perimeter topology:** does the play path include **vertical** adjacency on screen? If yes, budget **walk_up / walk_down** (or 4-way) art and **edge_kind** in the path format.
- [ ] Should tokens **respect frame rim / mask** (draw under/over chrome) in final composite?

---

## 8. Relation to Board Factory

Today the app builds **static** board mockups and exports **layout + assets**. Token systems usually need:

- A **stable cell identity** for each perimeter step (your `cells.kind = perimeter` rows and catalog positions are the right abstraction).
- An **export or runtime bundle** that lists **ordered path nodes** and **pixel centers** so the engine can animate along that polyline.

When you are ready to implement, a follow-on spec should define: **path graph**, **token anchor transform**, and **clip manifest** next to `interaction_graph` / project export.

---

*This document is guidance only. Product answers to §5 and §7 should be folded into a technical export or engine spec when you commit to a runtime.*
