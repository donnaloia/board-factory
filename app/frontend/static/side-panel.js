// side-panel.js
//
// Replaces the per-page experience with an inline side panel docked to the
// right of the board. Clicking any cell on the SVG opens the panel for that
// cell with: live preview, prompt + metadata, regenerate button, and a
//   - Click a history thumbnail → select it (prompt + highlight track that version).
//     Use "Restore to board" on a row to promote it back to live without selecting first.
//
// Selection model:
//   - Click a cell → swap panel content to that cell (with a quick fade)
//   - Click another cell → panel content swaps in place
//   - Click outside the board (background of board-plate) → panel fades out
//   - X button on the panel → panel closes
//   - URL hash #<category>:<asset_id> or #spaces/<asset_id>/<position_ref> deep-links
//
// Job tracking:
//   - When a regen job is enqueued for the currently-open cell, the panel
//     subscribes to that job id and refreshes its state when the job ends.
//   - We don't need full SSE here; jobs.js already broadcasts updates and
//     we hook into a 'bf:job-update' window event it dispatches.

(function () {
  const wrap = document.getElementById("board-with-panel");
  const plate = document.getElementById("board-plate");
  const panel = document.getElementById("cell-panel");
  if (!wrap || !plate || !panel) return;

  // Per-board URL prefix — every API and action call is scoped under here.
  const BOARD_ID = wrap.getAttribute("data-board-id");
  const BOARD_BASE = (wrap.getAttribute("data-board-base") || "").trim();
  if (!BOARD_ID || !BOARD_BASE) return;
  const BPATH = BOARD_BASE;

  // Which history thumbnail is "selected" for the prompt editor / preview. Separate from
  // what's live on the board — user picks a row to inspect its prompt; "Restore" promotes.
  const selectionByCell = {};

  function cellKey(category, assetId) {
    return `${category}:${assetId}`;
  }

  function pickDefaultHistorySelection(data) {
    return (
      data.live_history_filename
      || data.history.find(h => h.is_live)?.filename
      || data.history[0]?.filename
      || null
    );
  }

  function promptForHistorySelection(data, filename) {
    if (!filename) return data.active_prompt || "";
    const row = data.history.find(h => h.filename === filename);
    if (row && row.prompt != null) return row.prompt;
    return data.active_prompt || "";
  }

  // Inline SVG spinner strokes — slightly muted vs pure white on dark boards.
  const SPINNER_STROKE_TRACK = "rgba(118, 128, 145, 0.26)";
  const SPINNER_STROKE_ARC = "rgba(112, 122, 142, 0.9)";

  /** Stable per-cell SMIL timing — similar speeds, different period + phase. */
  function spinnerTiming(category, assetId) {
    const s = String(category) + "\0" + String(assetId);
    let h = 2166136261 >>> 0;
    for (let i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = Math.imul(h, 16777619) >>> 0;
    }
    const u = (h >>> 0) / 0xffffffff;
    const durSec = 0.92 + u * 0.36; // 0.92s … 1.28s — close, not frantic
    const h2 = Math.imul(h ^ 0x9e3779b9, 1103515245) >>> 0;
    const beginSec = -((h2 % 1000) / 1000) * 0.85; // −0.85s … 0 — stagger phase
    return { durSec, beginSec };
  }

  let current = null;            // { category, asset_id, position_ref? }
  let watchedJobId = null;       // job id we're waiting on for a refresh

  // Cached payload from the most recent /api/cell fetch, used by the
  // animation section's incremental re-renders so phase flips don't
  // trigger another HTTP round-trip.
  let _lastPanelData = null;

  // Per-cell animation UI state, keyed by `${category}:${asset_id}`. Each entry:
  //   {
  //     phase: "idle" | "running" | "review" | "error",
  //     jobId: string | null,
  //     proposals: { candidates: [...], provider, model_id } | null,
  //     selectedIndex: number,        // which candidate is selected in the gallery
  //     errorMessage: string | null,
  //   }
  // Volatile (in-memory only): refreshing the page while a job is in flight
  // re-resolves through /jobs/{id} polling, but the candidate gallery is
  // lost — acceptable trade-off for the MVP.
  const animStateByCell = {};

  function animState(category, assetId) {
    const k = cellKey(category, assetId);
    if (!animStateByCell[k]) {
      animStateByCell[k] = {
        phase: "idle",
        jobId: null,
        proposals: null,
        selectedIndex: 0,
        errorMessage: null,
      };
    }
    return animStateByCell[k];
  }

  let _animPromptModal = null;

  function animPromptStorageKey(category, assetId) {
    return `bf-anim-prompt:${BOARD_ID}:${cellKey(category, assetId)}`;
  }

  function ensureAnimPromptModal() {
    if (_animPromptModal) return _animPromptModal;
    const root = document.createElement("div");
    root.className = "bf-anim-prompt-modal is-hidden";
    root.id = "bf-anim-prompt-modal";
    root.setAttribute("aria-hidden", "true");
    root.innerHTML = `
      <div class="bf-anim-prompt-backdrop" data-anim-prompt-backdrop></div>
      <div class="bf-anim-prompt-dialog" role="dialog" aria-modal="true" aria-labelledby="bf-anim-prompt-title">
        <h3 class="bf-anim-prompt-title" id="bf-anim-prompt-title">Animation direction</h3>
        <p class="bf-anim-prompt-lead">Describe the motion you want (subtle works best). We generate three looping previews to compare.</p>
        <p class="bf-anim-prompt-where">After the job finishes, stay in this sidebar: results appear in the <strong>Animation</strong> section (just under <strong>Action</strong>). Hover a preview, then tap <strong>Use</strong> to save that loop to the cell. <em>Sora renders are async and can take several minutes per job.</em></p>
        <textarea class="bf-anim-prompt-textarea" data-anim-prompt-textarea maxlength="2000" rows="5" placeholder="e.g. Soft pulse on the crystal, ember flicker in the torch, gentle shimmer on metal…"></textarea>
        <p class="bf-anim-prompt-err" data-anim-prompt-err></p>
        <div class="bf-anim-prompt-actions">
          <button type="button" class="panel-action is-quiet" data-anim-prompt-cancel>Cancel</button>
          <button type="button" class="panel-action" data-anim-prompt-confirm><span class="arrow">↻</span><span>Generate 3 loops</span></button>
        </div>
      </div>
    `;
    wrap.appendChild(root);
    _animPromptModal = root;
    return root;
  }

  /**
   * @param {string} prefill
   * @param {(prompt: string) => void | Promise<void>} onConfirm
   * @param {() => void} onCancel
   */
  function openAnimPromptModal(prefill, onConfirm, onCancel) {
    const root = ensureAnimPromptModal();
    const ta = root.querySelector("[data-anim-prompt-textarea]");
    const errEl = root.querySelector("[data-anim-prompt-err]");
    const btnCancel = root.querySelector("[data-anim-prompt-cancel]");
    const btnOk = root.querySelector("[data-anim-prompt-confirm]");
    const backdrop = root.querySelector("[data-anim-prompt-backdrop]");
    if (!ta || !errEl || !btnCancel || !btnOk || !backdrop) return;

    ta.value = prefill || "";
    ta.classList.remove("is-invalid");
    errEl.textContent = "";

    root.classList.remove("is-hidden");
    root.setAttribute("aria-hidden", "false");
    ta.focus();

    function cleanup() {
      root.classList.add("is-hidden");
      root.setAttribute("aria-hidden", "true");
      btnCancel.removeEventListener("click", onCancelClick);
      btnOk.removeEventListener("click", onOkClick);
      backdrop.removeEventListener("click", onBackdropClick);
      document.removeEventListener("keydown", onKey);
    }

    function onCancelClick() {
      cleanup();
      onCancel();
    }

    function onBackdropClick(e) {
      if (e.target === backdrop) onCancelClick();
    }

    function onOkClick() {
      const text = ta.value.trim();
      if (!text) {
        ta.classList.add("is-invalid");
        errEl.textContent = "Describe the animation before generating.";
        ta.focus();
        return;
      }
      ta.classList.remove("is-invalid");
      errEl.textContent = "";
      cleanup();
      onConfirm(text);
    }

    function onKey(e) {
      if (e.key === "Escape") {
        e.preventDefault();
        onCancelClick();
      }
    }

    btnCancel.addEventListener("click", onCancelClick);
    btnOk.addEventListener("click", onOkClick);
    backdrop.addEventListener("click", onBackdropClick);
    document.addEventListener("keydown", onKey);
  }

  // Supersede in-flight /api/cell fetches when switching cells (bulk board
  // refresh competes for connections and can complete out of order).
  let _panelFetchSeq = 0;
  let _panelFetchAbort = null;

  // ─── Cell click handling ─────────────────────────────────────────────

  plate.addEventListener("click", (e) => {
    const link = e.target.closest("a.bf-cell-link");
    if (link) {
      e.preventDefault();
      const category = link.getAttribute("data-category");
      const asset_id = link.getAttribute("data-asset-id");
      const position_ref = link.getAttribute("data-position-ref");
      openCell(category, asset_id, position_ref || null);
      return;
    }
    // Click on the plate background (no cell hit) → close.
    if (e.target === plate || e.target.tagName.toLowerCase() === "svg") {
      closePanel();
    }
  });

  // Keyboard support: Esc closes.
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && current) closePanel();
  });

  // ─── Open / close ────────────────────────────────────────────────────

  function openCell(category, asset_id, position_ref = null) {
    const sameSpot =
      current
      && current.category === category
      && current.asset_id === asset_id
      && (category !== "spaces" || current.position_ref === position_ref);
    if (sameSpot) {
      return; // already open
    }
    current = { category, asset_id, position_ref };
    markSelected(category, asset_id, position_ref);
    wrap.classList.remove("is-panel-closed");
    panel.classList.add("is-open");
    panel.classList.add("is-swapping");
    panel.setAttribute("aria-hidden", "false");
    resetCellPanelScroll();
    const openedKey = `${category}:${asset_id}:${position_ref || ""}`;
    refreshPanel().finally(() => {
      // Another cell may have been opened while this fetch was in flight.
      if (!current
          || `${current.category}:${current.asset_id}:${current.position_ref || ""}` !== openedKey) {
        return;
      }
      panel.classList.remove("is-swapping");
      scheduleBulkBoardSvgRefresh();
    });
    // Update URL hash so reload returns to same cell.
    if (category === "spaces" && position_ref) {
      history.replaceState(
        null,
        "",
        `#spaces/${encodeURIComponent(asset_id)}/${encodeURIComponent(position_ref)}`,
      );
    } else {
      history.replaceState(null, "", `#${category}:${asset_id}`);
    }
  }

  function closePanel() {
    current = null;
    _panelFetchAbort?.abort();
    wrap.classList.add("is-panel-closed");
    panel.classList.remove("is-open");
    panel.classList.remove("is-swapping");
    panel.setAttribute("aria-hidden", "true");
    setTimeout(() => { panel.innerHTML = ""; }, 250);
    clearSelected();
    history.replaceState(null, "", window.location.pathname);
    if (_deferredBulkSvgRefresh) {
      _deferredBulkSvgRefresh = false;
      scheduleBulkBoardSvgRefreshCore();
    }
  }

  function markSelected(category, asset_id, position_ref = null) {
    clearSelected();
    if (category === "spaces" && position_ref) {
      plate.querySelectorAll(
        `a.bf-cell-link[data-category="${CSS.escape(category)}"]`
        + `[data-asset-id="${CSS.escape(asset_id)}"]`
        + `[data-position-ref="${CSS.escape(position_ref)}"]`,
      ).forEach(el => el.classList.add("is-selected"));
      return;
    }
    plate.querySelectorAll(
      `a.bf-cell-link[data-category="${CSS.escape(category)}"][data-asset-id="${CSS.escape(asset_id)}"]`,
    ).forEach(el => el.classList.add("is-selected"));
  }
  function clearSelected() {
    plate.querySelectorAll("a.bf-cell-link.is-selected")
      .forEach(el => el.classList.remove("is-selected"));
  }

  /** Side panel scroll container is `#cell-panel` (e.g. narrow viewports). Reset when swapping cells. */
  function resetCellPanelScroll() {
    panel.scrollTop = 0;
  }

  // ─── Fetch + render ──────────────────────────────────────────────────

  async function refreshPanel() {
    if (!current) return;
    _panelFetchAbort?.abort();
    const ac = new AbortController();
    _panelFetchAbort = ac;
    const seq = ++_panelFetchSeq;
    try {
      const r = await fetch(`${BPATH}/api/cell/${current.category}/${current.asset_id}`, {
        cache: "no-store",
        signal: ac.signal,
      });
      if (!r.ok) {
        if (seq !== _panelFetchSeq) return null;
        panel.innerHTML = `<p class="muted">Could not load cell.</p>`;
        resetCellPanelScroll();
        return null;
      }
      const data = await r.json();
      if (seq !== _panelFetchSeq) return null;
      const ck = cellKey(current.category, current.asset_id);
      let sel = selectionByCell[ck];
      if (!sel || !data.history.some(h => h.filename === sel)) {
        sel = pickDefaultHistorySelection(data);
      }
      selectionByCell[ck] = sel;
      const displayPrompt = promptForHistorySelection(data, sel);
      _lastPanelData = data;
      panel.innerHTML = renderPanel(data, displayPrompt, sel);
      resetCellPanelScroll();
      wireActions(data);
      return data;
    } catch (e) {
      if (e && (e.name === "AbortError" || e.code === 20)) return null;
      if (seq !== _panelFetchSeq) return null;
      panel.innerHTML = `<p class="muted">Network error.</p>`;
      resetCellPanelScroll();
      return null;
    }
  }

  // Directly update the SVG <image> href(s) for one cell to the given URL.
  // Returns true if at least one image element was found and updated.
  // Appends a unique bust token so the browser always fetches fresh even if
  // the mtime-stamped URL matches a previously loaded one.
  function updateCellImageOnBoard(category, assetId, liveUrl) {
    if (!liveUrl) return false;
    const svg = plate.querySelector("svg");
    if (!svg) return false;
    // Strip any existing query string and re-stamp with current time so the
    // browser treats this as a new resource regardless of prior caching.
    const base = liveUrl.split("?")[0];
    const bustUrl = `${base}?_=${Date.now()}`;
    const imgs = svg.querySelectorAll(
      `[data-category="${CSS.escape(category)}"][data-asset-id="${CSS.escape(assetId)}"] image`
    );
    imgs.forEach(img => img.setAttribute("href", bustUrl));
    return imgs.length > 0;
  }

  // Swap the SVG <image> href(s) for one cell to a GIF (animation) URL —
  // identical mechanics to ``updateCellImageOnBoard`` but the URL is
  // cache-busted on EVERY call so the GIF restarts at frame 0 each time
  // the user re-enters the hover region.
  function previewAnimationOnBoard(category, assetId, animUrl) {
    if (!animUrl) return false;
    const svg = plate.querySelector("svg");
    if (!svg) return false;
    const bustUrl = `${animUrl.split("?")[0]}?_=${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    const imgs = svg.querySelectorAll(
      `[data-category="${CSS.escape(category)}"][data-asset-id="${CSS.escape(assetId)}"] image`
    );
    imgs.forEach(img => img.setAttribute("href", bustUrl));
    return imgs.length > 0;
  }

  /** Clickable header id for perimeter cells — opens minimal design-id popover. */
  function renderSpaceDesignIdHead(spec, data) {
    const ids = data.space_design_ids || [];
    const others = ids.filter(id => id !== spec.id);
    const noRef = !current || !current.position_ref;
    const listRows = others.length
      ? others.map(id => `
          <button type="button" class="bf-design-pop-row" data-design-adopt="${escapeAttr(id)}">${escapeHtml(id)}</button>
        `).join("")
      : `<p class="bf-design-pop-empty muted">No other designs</p>`;
    const showFilter = others.length > 5;
    return `
      <div class="panel-id-wrap" data-design-id-wrap>
        <button type="button" class="panel-id panel-id-trigger" data-design-id-trigger
          ${noRef ? "disabled title=\"Pick a tile on the board first\"" : ""}
          aria-expanded="false" aria-haspopup="true">${escapeHtml(spec.id)}</button>
        <div class="bf-design-pop" data-design-id-pop hidden>
          ${showFilter ? `<input type="search" class="bf-design-pop-filter" data-design-id-filter placeholder="Filter" autocomplete="off" spellcheck="false" />` : ""}
          <div class="bf-design-pop-scroll" data-design-id-scroll>${listRows}</div>
          <div class="bf-design-pop-divider"></div>
          <div class="bf-design-pop-foot">
            <input type="text" class="bf-design-pop-input" data-design-id-new placeholder="new id" autocomplete="off" spellcheck="false" />
            <button type="button" class="bf-design-pop-action" data-design-id-create>Create</button>
          </div>
        </div>
      </div>`;
  }

  function renderPanel(data, displayPrompt, selectedFilename) {
    const spec = data.spec;
    const sizeStr = spec.size ? `${spec.size[0]} × ${spec.size[1]}` : "—";
    const usesStr = spec.uses === 1 ? "1 position" : `${spec.uses} positions`;
    const eyebrow = ({
      perimeter: "Perimeter",
      functional: "Functional",
      centerpiece: "Marquee",
    })[spec.kind] || "Cell";

    // Large preview: selected history version when browsing; otherwise live asset.
    const selEntry = selectedFilename
      ? data.history.find(h => h.filename === selectedFilename)
      : null;
    const cellImgSrc = selEntry
      ? `${selEntry.url.split("?")[0]}?_=${Date.now()}`
      : (data.live_url ? `${data.live_url.split("?")[0]}?_=${Date.now()}` : null);
    const showFrameOverlay = Boolean(
      cellImgSrc && data.frame_locked && data.frame_url
        && (selEntry ? selEntry.is_live : data.has_live),
    );

    // If the selected history row is not flagged is_live but the filename
    // matches `live_history_filename` from the server, we are still
    // looking at the board's current static art.
    const viewingLiveStatic = !selEntry
      || Boolean(selEntry.is_live)
      || Boolean(
        data.live_history_filename
          && selectedFilename
          && selectedFilename === data.live_history_filename,
      );
    const animLiveUrl = viewingLiveStatic && data.animation?.live?.url
      ? data.animation.live.url
      : null;
    const animClass = animLiveUrl ? " has-anim-hover" : "";

    const liveBlock = cellImgSrc
      ? `<div class="cell-live${showFrameOverlay ? " with-frame" : ""}${animClass}"
              data-cell-live
              data-static-url="${escapeAttr(cellImgSrc.split("?")[0])}"
              ${animLiveUrl ? `data-anim-url="${escapeAttr(animLiveUrl.split("?")[0])}"` : ""}
              ${animLiveUrl ? `aria-label="Hover to preview live animation"` : ""}>
           <img src="${cellImgSrc}" alt="" data-cell-live-img>
           ${showFrameOverlay
              ? `<img class="frame-overlay" src="${data.frame_url}" alt="" aria-hidden="true">`
              : ""}
           ${animLiveUrl
              ? `<span class="cell-live-anim-badge" aria-hidden="true">▶ hover to play</span>`
              : ""}
         </div>`
      : `<div class="cell-live empty">no asset yet</div>`;

    const histBlock = data.history.length === 0
      ? `<p class="cell-history-empty">no history yet — generate to make some.</p>`
      : `<div class="cell-history">${data.history.map(h => renderHistoryRow(h, selectedFilename)).join("")}</div>`;

    const cost = data.regen_estimate_usd > 0
      ? `~$${data.regen_estimate_usd.toFixed(3)} · ${data.candidates_per_regen} variations`
      : `free · ${data.candidates_per_regen} variations`;

    // Compare displayed prompt (selected history row / live) vs catalog default.
    const promptInherited = (displayPrompt || "") === (data.catalog_prompt || "");

    return `
      <div class="cell-panel-head">
        <div>
          <span class="panel-eyebrow">${eyebrow}</span>
          <h3 class="panel-title">${escapeHtml(spec.title)}</h3>
          ${spec.kind === "perimeter"
            ? renderSpaceDesignIdHead(spec, data)
            : `<span class="panel-id">${escapeHtml(spec.id)}</span>`}
        </div>
        <button class="cell-panel-close" type="button" aria-label="Close">×</button>
      </div>

      ${liveBlock}

      <div class="cell-panel-section">
        <h4>Prompt
          <span class="prompt-state" data-prompt-state>
            ${promptInherited
              ? `<span class="prompt-flag inherited">inherited from catalog</span>`
              : `<span class="prompt-flag override">override active</span>`}
          </span>
        </h4>
        <textarea class="prompt-editor"
                  data-prompt-editor
                  data-base="${escapeAttr(displayPrompt || "")}"
                  data-catalog="${escapeAttr(data.catalog_prompt || "")}"
                  spellcheck="false"
                  rows="4">${escapeHtml(displayPrompt || "")}</textarea>
        <div class="prompt-toolbar" data-prompt-toolbar hidden>
          <span class="prompt-hint">edited &mdash; will be used on next generate</span>
          <button type="button" class="quiet-action" data-prompt-revert>Revert</button>
        </div>
      </div>

      <div class="cell-panel-section">
        <h4>Geometry</h4>
        <dl class="cell-meta">
          <dt>Size</dt><dd>${sizeStr} px</dd>
          <dt>Uses</dt><dd>${usesStr}</dd>
          <dt>Category</dt><dd>${data.category}</dd>
          ${spec.kind === "perimeter"
            ? (() => {
                const sk = spec.space_kind || "standard";
                const ft = Array.isArray(data.functional_targets) ? data.functional_targets : [];
                const noneSel = !data.triggers_functional_cell_id ? " selected" : "";
                const opts = ft.map(f => {
                  const sel = data.triggers_functional_cell_id === f.cell_id ? " selected" : "";
                  return `<option value="${escapeAttr(f.cell_id)}"${sel}>${escapeHtml(f.id)}</option>`;
                }).join("");
                return `<dt>Space kind</dt><dd class="space-kind-dd">
                  <select data-space-kind aria-label="Space kind">
                    <option value="standard" ${sk === "event" ? "" : "selected"}>Standard track</option>
                    <option value="event" ${sk === "event" ? "selected" : ""}>Event / special</option>
                  </select>
                  <p class="muted space-kind-hint">Framing for generation — applies to every board cell that uses this design.</p>
                </dd>
                <dt>Land trigger</dt><dd class="land-trigger-dd">
                  <select data-land-trigger aria-label="On land, trigger functional cell">
                    <option value=""${noneSel}>None</option>${opts}
                  </select>
                  <p class="muted land-trigger-hint">Per design — all tiles using this design share the link. Used for project export <code>interaction_graph</code>.</p>
                </dd>`;
              })()
            : ""}
        </dl>
      </div>

      ${data.frame ? renderFrameSection(data) : ""}

      <div class="cell-panel-section">
        <h4>Action</h4>
        <button class="panel-action primary" type="button" data-regen>
          <span class="arrow">→</span>
          <span data-regen-label>${data.history.length > 0 ? "Regenerate" : "Generate"}</span>
          <span class="est">${data.frame_locked ? "interior only · " : ""}${cost}</span>
        </button>
        <button class="panel-action" type="button" data-clean
                ${data.has_live ? "" : "disabled"}>
          <span class="arrow">→</span>
          <span>Cleanup image</span>
          <span class="est">free · ~1s</span>
        </button>
        ${renderAnimateAction(data)}
        <button class="panel-action is-placeholder" type="button" data-download
                aria-disabled="true" title="Coming soon">
          <span class="arrow">→</span>
          <span>Download</span>
          <span class="est">soon</span>
        </button>
      </div>

      ${renderAnimationSection(data)}

      <div class="cell-panel-section">
        <h4>History · ${data.history.length}</h4>
        ${histBlock}
      </div>

      <div class="cell-panel-section cell-panel-advanced">
        <button type="button" class="panel-action is-quiet" data-open-gen-settings>
          <span class="arrow">→</span>
          <span>Advanced</span>
          <span class="est">model &amp; palette</span>
        </button>
      </div>
    `;
  }

  // ─── Frame section: collapsed by default, expands inline ──────────────
  // Rendered for EVERY panel cell. Selection IS the action: clicking a
  // source card immediately adopts it (or, in the case of the "None" card,
  // disables the frame board-wide). Slider changes re-adopt on release so
  // the user can fine-tune ring thickness without an extra button.

  function renderFrameSection(data) {
    // Slim status block — the inline picker has been replaced by the
    // dedicated Frame Atelier (board-level page reachable from the link
    // below). The side panel surfaces status for *this* cell and links into
    // the Atelier; full authoring
    // (Propose / Refine / Commit / Approach D batch) lives there.
    const f = data.frame;

    let summary;
    if (!f.adopted || !f.enabled) {
      summary = `<span class="frame-empty">no frame · open the Atelier to design one</span>`;
    } else if (f.applied_to_this_cell) {
      summary = `<span class="frame-lock">◆ locked</span> from <code>${escapeHtml(f.adopted_meta?.source_id || "—")}</code> · ${f.adopted_meta?.ring_px ?? "—"}px ring`;
    } else {
      summary = `frame adopted board-wide · this panel will pick it up on the next regenerate`;
    }

    const showDisable = f.adopted && f.enabled;

    return `
      <div class="cell-panel-section frame-section" data-frame-section>
        <h4>
          <span>Frame</span>
          <span class="frame-summary-inline">board-level</span>
        </h4>
        <p class="frame-summary">${summary}</p>

        <div class="frame-actions">
          <a class="panel-action" href="${BPATH}/frame">
            <span class="arrow">→</span>
            <span>Open Frame Atelier</span>
            <span class="est">propose · refine · commit</span>
          </a>
          ${showDisable ? `
          <button type="button" class="panel-action is-quiet" data-frame-disable>
            <span class="arrow">×</span>
            <span>Disable on board</span>
            <span class="est">overlay only</span>
          </button>
          ` : ""}
        </div>
      </div>
    `;
  }

  // ─── Animation: action row + section renderer ────────────────────────
  // Cells that aren't animatable (kind != functional or no live static)
  // simply get no Animate button — keeps the action stack clean instead
  // of disabling a row the user can never enable from this panel.

  function renderAnimateAction(data) {
    const a = data.animation;
    if (!a || !a.supported) return "";

    const state = current ? animState(current.category, current.asset_id) : null;
    const inFlight = state && state.phase === "running";

    const blockers = [];
    if (!a.has_live_static) {
      blockers.push("needs a generated image first");
    } else if (!a.provider_ready) {
      blockers.push("connect OpenAI key in Account");
    }
    const disabled = inFlight || blockers.length > 0;
    const est = a.estimate_usd > 0
      ? `~$${a.estimate_usd.toFixed(3)} · ${a.candidates} loops`
      : `free · ${a.candidates} loops`;
    const label = a.live ? "Re-animate" : "Animate";
    const subtitle = inFlight
      ? "generating…"
      : (blockers[0] || est);

    return `
      <button class="panel-action" type="button" data-animate
              ${disabled ? "disabled" : ""}
              ${blockers[0] ? `title="${escapeAttr(blockers[0])}"` : ""}>
        <span class="arrow">↻</span>
        <span>${label}</span>
        <span class="est">${escapeHtml(subtitle)}</span>
      </button>
    `;
  }

  function renderAnimationSection(data) {
    const a = data.animation;
    if (!a || !a.supported) return "";

    const state = current ? animState(current.category, current.asset_id) : null;

    // Decide the section body based on phase. The header is always shown
    // for supported cells so the user can find the affordance even
    // before running anything.
    let body;
    if (state && state.phase === "running") {
      body = renderAnimRunning(a);
    } else if (state && state.phase === "review" && state.proposals) {
      body = renderAnimReview(a, state);
    } else if (state && state.phase === "error") {
      body = renderAnimError(state);
    } else if (a.live) {
      body = renderAnimLive(a);
    } else {
      body = renderAnimEmpty(a);
    }

    return `
      <div class="cell-panel-section cell-anim-section" data-anim-section>
        <h4>
          <span>Animation</span>
          <span class="frame-summary-inline">${escapeHtml(a.provider)} · ${a.fps}fps</span>
        </h4>
        <p class="cell-anim-section-lead muted">Previews and the saved loop for this cell. Under <strong>Action</strong> → <strong>Animate</strong> / <strong>Re-animate</strong>.</p>
        ${body}
      </div>
    `;
  }

  function renderAnimLive(a) {
    const url = `${a.live.url.split("?")[0]}?_=${Date.now()}`;
    const dur = (a.live.duration_ms / 1000).toFixed(1);
    return `
      <div class="cell-anim-live">
        <span class="live-tag">live loop</span>
        <img src="${url}" alt="">
      </div>
      <dl class="cell-anim-meta">
        <dt>Duration</dt><dd>${dur}s · ${a.live.frame_count} frames</dd>
        <dt>Provider</dt><dd>${escapeHtml(a.live.provider)} / ${escapeHtml(a.live.model_id)}</dd>
        <dt>Loop</dt><dd>${escapeHtml(a.live.loop_strategy)}</dd>
      </dl>
      <p class="cell-anim-hint">The preview at the top of this panel is still the static art; the saved loop plays here. Use <strong>Re-animate</strong> in <strong>Action</strong> to generate ${a.candidates} new candidates.</p>
    `;
  }

  function renderAnimRunning(a) {
    const dur = (a.duration_ms / 1000).toFixed(1);
    const providerLower = (a.provider || "").toLowerCase();
    const isSora = providerLower.startsWith("sora");
    const wait = isSora
      ? "may take several minutes (Sora renders are async)"
      : "may take 30\u201360s";
    return `
      <div class="cell-anim-status">
        <span class="status-dot"></span>
        <span class="status-text">generating ${a.candidates} loops · ${dur}s @ ${a.fps}fps</span>
        <span class="status-est">${a.estimate_usd > 0 ? `~$${a.estimate_usd.toFixed(3)}` : "free"}</span>
      </div>
      <p class="cell-anim-hint">${escapeHtml(a.provider)} ${wait}. When it finishes, this panel scrolls to <strong>Animation</strong> below with ${a.candidates} previews \u2014 pick one and tap <strong>Use</strong>.</p>
    `;
  }

  function renderAnimReview(a, state) {
    const items = state.proposals.candidates.map((c, i) => {
      const isActive = i === state.selectedIndex;
      const dur = (c.duration_ms / 1000).toFixed(1);
      const note = (c.notes || `candidate ${i + 1}`).split(" (")[0];
      return `
        <li class="${isActive ? "is-active" : ""}" data-anim-cand="${i}">
          <div class="cand-thumb"><img src="${c.url}" alt=""></div>
          <div class="cand-meta">
            <span class="cand-title">${escapeHtml(note)}</span>
            <span class="cand-sub">${dur}s · ${c.frame_count} frames · ${escapeHtml(c.loop_strategy)}</span>
          </div>
          <button type="button" class="cand-pick" data-anim-pick="${i}">Use</button>
        </li>
      `;
    }).join("");

    return `
      <p class="cell-anim-ready">${state.proposals.candidates.length} loops ready — compare below, then tap <strong>Use</strong> on the one you want. (Nothing is published until you choose.)</p>
      <ul class="cell-anim-candidates">
        ${items}
      </ul>
    `;
  }

  function renderAnimError(state) {
    return `
      <div class="cell-anim-error">
        <p class="err-title">animation failed</p>
        <p class="err-msg">${escapeHtml(state.errorMessage || "unknown error")}</p>
      </div>
      <p class="cell-anim-hint">Tap “Animate” to try again.</p>
    `;
  }

  function renderAnimEmpty(a) {
    if (!a.has_live_static) {
      return `
        <p class="cell-anim-empty">no static art yet — generate first, then animate.</p>
      `;
    }
    if (!a.provider_ready) {
      return `
        <p class="cell-anim-hint">
          Add your OpenAI / ChatGPT key in
          <a href="#" data-open-account>Account → Connections</a>
          to enable animation.
        </p>
      `;
    }
    const dur = (a.duration_ms / 1000).toFixed(1);
    const cost = a.estimate_usd > 0
      ? `~$${a.estimate_usd.toFixed(3)}`
      : "free";
    return `
      <p class="cell-anim-empty">No loop saved yet · ${a.candidates} candidate previews · ${dur}s @ ${a.fps}fps · ${cost}. After you run <strong>Animate</strong> (under Action), results show here.</p>
    `;
  }

  function renderHistoryRow(h, selectedFilename) {
    const date = new Date(h.ts_ms);
    const ts = date.toLocaleString(undefined, {
      month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
    const opLabel = ({
      regen: "generated",
      clean: "cleaned",
    })[h.operation] || h.operation || "";
    const marker = h.is_live ? "live on board" : "older version";
    const isSel = selectedFilename && h.filename === selectedFilename;
    const restoreBtn = !h.is_live
      ? `<button type="button" class="history-restore-btn"
              data-history-promote="${escapeAttr(h.filename)}"
              aria-label="Restore this version to the board">Restore</button>`
      : "";
    return `
      <div class="history-row-wrap">
        <button type="button"
                class="history-row ${h.is_live ? "is-live" : ""} ${isSel ? "is-selected" : ""}"
                data-history-select="${escapeAttr(h.filename)}">
          <div class="thumb"><img src="${h.url}" alt=""></div>
          <div class="meta-col">
            <span class="ts">${ts}</span>
            <span class="marker">${opLabel} · ${marker}</span>
          </div>
        </button>
        ${restoreBtn}
      </div>
    `;
  }

  // Hover-to-play wiring for the sidebar's static thumbnail.
  // When the cell has a saved live animation, hovering the preview at
  // the top of the sidebar swaps both the thumb <img> AND the matching
  // cell on the board SVG to the GIF, then restores the static on
  // mouseleave. Restart-on-each-hover is achieved by cache-busting the
  // GIF URL — browsers always start GIFs at frame 0 on a fresh load.
  function wireCellLiveHoverPreview(data) {
    if (!current) return;
    const wrap = panel.querySelector("[data-cell-live]");
    if (!wrap || !wrap.classList.contains("has-anim-hover")) return;

    const img = wrap.querySelector("[data-cell-live-img]");
    if (!img) return;

    const animUrl = wrap.getAttribute("data-anim-url");
    const staticUrl = wrap.getAttribute("data-static-url");
    if (!animUrl || !staticUrl) return;

    const cat = current.category;
    const aid = current.asset_id;
    let hovered = false;

    const onEnter = () => {
      hovered = true;
      const bust = `${animUrl}?_=${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
      img.setAttribute("src", bust);
      wrap.classList.add("is-anim-playing");
      previewAnimationOnBoard(cat, aid, animUrl);
    };
    const onLeave = () => {
      if (!hovered) return;
      hovered = false;
      const bust = `${staticUrl}?_=${Date.now()}`;
      img.setAttribute("src", bust);
      wrap.classList.remove("is-anim-playing");
      updateCellImageOnBoard(cat, aid, staticUrl);
    };

    wrap.addEventListener("mouseenter", onEnter);
    wrap.addEventListener("mouseleave", onLeave);
  }

  function wireActions(data) {
    panel.querySelector(".cell-panel-close")?.addEventListener("click", closePanel);
    wireCellLiveHoverPreview(data);

    // ─── Prompt editor: dirty-state toolbar + revert ───
    const editor = panel.querySelector("[data-prompt-editor]");
    const toolbar = panel.querySelector("[data-prompt-toolbar]");
    const revert = panel.querySelector("[data-prompt-revert]");
    const stateSlot = panel.querySelector("[data-prompt-state]");
    const regenLabel = panel.querySelector("[data-regen-label]");
    if (editor && toolbar) {
      const hasHistory = data.history.length > 0;
      const refreshDirtyState = () => {
        const dirty = editor.value !== editor.getAttribute("data-base");
        toolbar.hidden = !dirty;
        if (stateSlot) {
          const isCatalog = editor.value === editor.getAttribute("data-catalog");
          stateSlot.innerHTML = dirty
            ? `<span class="prompt-flag dirty">edited &mdash; not yet generated</span>`
            : (isCatalog
                ? `<span class="prompt-flag inherited">inherited from catalog</span>`
                : `<span class="prompt-flag override">override from history</span>`);
        }
        // When the prompt is dirty on a cell that already has assets, the next
        // call won't be a re-generation of "the same thing" — it produces
        // something new. Surface that with a copy change.
        if (regenLabel) {
          regenLabel.textContent = (hasHistory && !dirty) ? "Regenerate" : "Generate";
        }
      };
      editor.addEventListener("input", refreshDirtyState);
      revert?.addEventListener("click", () => {
        editor.value = editor.getAttribute("data-catalog") || "";
        refreshDirtyState();
      });
    }

    // ─── Perimeter space kind (catalog) ───────────────────────────────
    const spaceKindEl = panel.querySelector("[data-space-kind]");
    if (spaceKindEl && current.category === "spaces") {
      spaceKindEl.addEventListener("change", async () => {
        const value = spaceKindEl.value;
        spaceKindEl.disabled = true;
        try {
          const res = await fetch(
            `${BPATH}/api/cell/${current.category}/${current.asset_id}`,
            {
              method: "PATCH",
              headers: { "Content-Type": "application/json", Accept: "application/json" },
              body: JSON.stringify({ space_kind: value }),
            },
          );
          if (!res.ok) {
            alert("Could not save space kind: " + (await res.text()).slice(0, 200));
          }
        } catch (err) {
          alert("Network error: " + err);
        } finally {
          spaceKindEl.disabled = false;
          await refreshPanel();
        }
      });
    }

    const landTriggerEl = panel.querySelector("[data-land-trigger]");
    if (landTriggerEl && current.category === "spaces") {
      landTriggerEl.addEventListener("change", async () => {
        const raw = landTriggerEl.value;
        const value = raw === "" ? null : raw;
        landTriggerEl.disabled = true;
        try {
          const res = await fetch(
            `${BPATH}/api/cell/${current.category}/${current.asset_id}`,
            {
              method: "PATCH",
              headers: { "Content-Type": "application/json", Accept: "application/json" },
              body: JSON.stringify({ triggers_functional_cell_id: value }),
            },
          );
          if (!res.ok) {
            alert("Could not save land trigger: " + (await res.text()).slice(0, 200));
          }
        } catch (err) {
          alert("Network error: " + err);
        } finally {
          landTriggerEl.disabled = false;
          await refreshPanel();
        }
      });
    }

    // ─── Space design id: minimal popover on header id (per layout ref) ─
    const runSpaceReassign = async (body) => {
      const res = await fetch(`${BPATH}/api/spaces/reassign`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 400) || res.statusText);
      }
      return res.json();
    };

    const designWrap = panel.querySelector("[data-design-id-wrap]");
    if (designWrap) {
      const tri = designWrap.querySelector("[data-design-id-trigger]");
      const pop = designWrap.querySelector("[data-design-id-pop]");
      const flt = designWrap.querySelector("[data-design-id-filter]");
      const forkNew = designWrap.querySelector("[data-design-id-new]");
      const forkBtn = designWrap.querySelector("[data-design-id-create]");

      let designDocBound = false;
      let designEscBound = false;

      const closeDesignPop = () => {
        if (!pop) return;
        pop.hidden = true;
        tri?.setAttribute("aria-expanded", "false");
        if (designDocBound) {
          document.removeEventListener("click", onDesignDoc);
          designDocBound = false;
        }
        if (designEscBound) {
          document.removeEventListener("keydown", onDesignEsc);
          designEscBound = false;
        }
      };

      const onDesignDoc = (ev) => {
        if (!designWrap.contains(ev.target)) closeDesignPop();
      };

      const onDesignEsc = (ev) => {
        if (ev.key === "Escape" && pop && !pop.hidden) {
          ev.preventDefault();
          closeDesignPop();
        }
      };

      const openDesignPop = () => {
        if (!pop || tri?.disabled) return;
        pop.hidden = false;
        tri.setAttribute("aria-expanded", "true");
        setTimeout(() => {
          document.addEventListener("click", onDesignDoc);
          designDocBound = true;
          document.addEventListener("keydown", onDesignEsc);
          designEscBound = true;
        }, 0);
        requestAnimationFrame(() => {
          (flt || forkNew)?.focus();
        });
      };

      tri?.addEventListener("click", (ev) => {
        ev.stopPropagation();
        if (!pop || tri.disabled) return;
        if (pop.hidden) openDesignPop();
        else closeDesignPop();
      });

      flt?.addEventListener("input", () => {
        const q = (flt.value || "").trim().toLowerCase();
        designWrap.querySelectorAll("[data-design-adopt]").forEach((btn) => {
          const id = (btn.getAttribute("data-design-adopt") || "").toLowerCase();
          btn.hidden = Boolean(q && !id.includes(q));
        });
      });

      const afterReassign = async (newAssetId) => {
        current.asset_id = newAssetId;
        markSelected(current.category, newAssetId, current.position_ref);
        if (current.category === "spaces" && current.position_ref) {
          history.replaceState(
            null,
            "",
            `#spaces/${encodeURIComponent(newAssetId)}/${encodeURIComponent(current.position_ref)}`,
          );
        }
        closeDesignPop();
        await refreshBoardSvg();
        await refreshPanel();
      };

      designWrap.querySelectorAll("[data-design-adopt]").forEach((btn) => {
        btn.addEventListener("click", async (ev) => {
          ev.stopPropagation();
          const target = (btn.getAttribute("data-design-adopt") || "").trim();
          if (!target || !current?.position_ref) return;
          btn.setAttribute("disabled", "true");
          try {
            await runSpaceReassign({
              from_design_id: current.asset_id,
              position_ref: current.position_ref,
              to_design_id: target,
            });
            await afterReassign(target);
          } catch (err) {
            alert("Could not switch design: " + err);
          } finally {
            btn.removeAttribute("disabled");
          }
        });
      });

      forkBtn?.addEventListener("click", async (ev) => {
        ev.stopPropagation();
        const nid = (forkNew?.value || "").trim().toLowerCase();
        if (!nid || !current?.position_ref) return;
        forkBtn.setAttribute("disabled", "true");
        try {
          const json = await runSpaceReassign({
            from_design_id: current.asset_id,
            position_ref: current.position_ref,
            new_design_id: nid,
            asset_policy: "empty",
          });
          const created = json.design_id || nid;
          await afterReassign(created);
        } catch (err) {
          alert("Could not create design id: " + err);
        } finally {
          forkBtn.removeAttribute("disabled");
        }
      });
    }

    // ─── Regenerate (with optional prompt override) ───
    panel.querySelector("[data-regen]")?.addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      btn.setAttribute("disabled", "true");
      try {
        const fd = new FormData();
        // Always read the prompt field at click time (not a stale closure).
        // Server: empty/whitespace → no override; non-empty → used as the cell prompt.
        const promptEl = panel.querySelector("[data-prompt-editor]");
        fd.append("prompt_override", promptEl?.value ?? "");
        const res = await fetch(`${BPATH}/actions/regen/${current.category}/${current.asset_id}`, {
          method: "POST",
          body: fd,
          headers: { "Accept": "application/json" },
        });
        if (!res.ok) {
          alert("Regenerate failed: " + (await res.text()));
          btn.removeAttribute("disabled");
          return;
        }
        const json = await res.json();
        watchedJobId = json.job_id;
        showCellSpinner(current.category, current.asset_id, current.position_ref);
      } catch (err) {
        alert("Network error: " + err);
        btn.removeAttribute("disabled");
      }
    });

    // ─── Advanced → open generation settings modal ────────────────────
    panel.querySelector("[data-open-gen-settings]")?.addEventListener("click", () => {
      window.dispatchEvent(new CustomEvent("bf:open-gen-settings"));
    });

    // ─── Cleanup image (re-quantize + grid-snap the live image) ───
    panel.querySelector("[data-clean]")?.addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      if (btn.hasAttribute("disabled")) return;
      btn.setAttribute("disabled", "true");
      try {
        const res = await fetch(`${BPATH}/actions/clean/${current.category}/${current.asset_id}`, {
          method: "POST",
          headers: { "Accept": "application/json" },
        });
        if (!res.ok) {
          alert("Cleanup failed: " + (await res.text()));
          btn.removeAttribute("disabled");
          return;
        }
        const json = await res.json();
        watchedJobId = json.job_id;
        showCellSpinner(current.category, current.asset_id, current.position_ref);
      } catch (err) {
        alert("Network error: " + err);
        btn.removeAttribute("disabled");
      }
    });

    // ─── Animation section: animate / pick candidate / commit ───
    wireAnimation(data);

    // ─── Frame section: expand/collapse + live preview + adopt/disable ───
    wireFrame(data);

    // ─── History: select row (prompt tracks that version); Restore promotes to live ───
    panel.querySelectorAll("[data-history-select]").forEach(btn => {
      btn.addEventListener("click", () => {
        const fn = btn.getAttribute("data-history-select");
        selectionByCell[cellKey(current.category, current.asset_id)] = fn;
        refreshPanel();
      });
    });

    panel.querySelectorAll("[data-history-promote]").forEach(btn => {
      btn.addEventListener("click", async (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        const filename = btn.getAttribute("data-history-promote");
        const fd = new FormData();
        fd.append("filename", filename);
        const r = await fetch(`${BPATH}/api/cell/${current.category}/${current.asset_id}/promote`,
                              { method: "POST", body: fd });
        if (r.ok) {
          selectionByCell[cellKey(current.category, current.asset_id)] = filename;
          const fresh = await refreshPanel();
          const updated = updateCellImageOnBoard(current.category, current.asset_id, fresh?.live_url);
          if (!updated) refreshBoardSvg();
        }
      });
    });
  }

  // ─── Frame status wiring ─────────────────────────────────────────────
  // The inline picker has been replaced by the dedicated /frame Atelier
  // (board-level Propose / Refine / Commit + Approach D progress). The
  // side panel keeps a tiny status section so the user can see whether
  // the frame is locked on this cell, link out to the Atelier, or hit
  // the same "Disable on board" affordance that lived in the old block.

  // ─── Animation wiring (action button + candidate gallery) ────────────

  function wireAnimation(data) {
    const a = data.animation;
    if (!a || !a.supported || !current) return;

    panel.querySelector("[data-animate]")?.addEventListener("click", () => {
      const btn = panel.querySelector("[data-animate]");
      if (!btn || btn.hasAttribute("disabled")) return;

      const sk = animPromptStorageKey(current.category, current.asset_id);
      const prefill = sessionStorage.getItem(sk) || "";

      openAnimPromptModal(
        prefill,
        async promptText => {
          sessionStorage.setItem(sk, promptText);
          btn.setAttribute("disabled", "true");
          const cellAnim = animState(current.category, current.asset_id);
          cellAnim.phase = "running";
          cellAnim.errorMessage = null;
          cellAnim.proposals = null;
          cellAnim.jobId = null;
          reRenderAnimationSection();
          try {
            const r = await fetch(a.animate_endpoint, {
              method: "POST",
              headers: {
                Accept: "application/json",
                "Content-Type": "application/json",
              },
              body: JSON.stringify({ animation_prompt: promptText }),
            });
            const rawText = await r.text();
            if (!r.ok) {
              let msg = rawText.slice(0, 240);
              try {
                const j = JSON.parse(rawText);
                if (typeof j.detail === "string") msg = j.detail;
              } catch (_) { /* keep slice */ }
              cellAnim.phase = "error";
              cellAnim.errorMessage = msg || r.statusText || "Request failed";
              reRenderAnimationSection();
              return;
            }
            const json = JSON.parse(rawText);
            cellAnim.jobId = json.job_id;
            watchAnimationJob(current.category, current.asset_id, json.job_id, a);
          } catch (err) {
            cellAnim.phase = "error";
            cellAnim.errorMessage = String(err);
            reRenderAnimationSection();
          }
        },
        () => {},
      );
    });

    // Click anywhere on a candidate row to select it (same UX as Frame
    // Atelier). The "Use" button inside the row is what commits.
    panel.querySelectorAll("[data-anim-cand]").forEach(row => {
      row.addEventListener("click", (ev) => {
        if (ev.target.closest("[data-anim-pick]")) return;
        const i = Number(row.getAttribute("data-anim-cand"));
        const cellAnim = animState(current.category, current.asset_id);
        if (cellAnim.selectedIndex === i) return;
        cellAnim.selectedIndex = i;
        reRenderAnimationSection();
      });
    });

    panel.querySelectorAll("[data-anim-pick]").forEach(btn => {
      btn.addEventListener("click", async (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        const i = Number(btn.getAttribute("data-anim-pick"));
        const cellAnim = animState(current.category, current.asset_id);
        if (!cellAnim.jobId) return;
        btn.setAttribute("disabled", "true");
        const commitUrl = a.commit_url_template.replace("{job_id}", cellAnim.jobId);
        try {
          const r = await fetch(commitUrl, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "Accept": "application/json",
            },
            body: JSON.stringify({ proposal_index: i }),
          });
          if (!r.ok) {
            const txt = await r.text();
            cellAnim.phase = "error";
            cellAnim.errorMessage = (txt || r.statusText).slice(0, 240);
            reRenderAnimationSection();
            return;
          }
          // Commit succeeded — drop the review state so the panel shows
          // the freshly-promoted live loop after refreshPanel.
          cellAnim.phase = "idle";
          cellAnim.proposals = null;
          cellAnim.jobId = null;
          await refreshPanel();
        } catch (err) {
          cellAnim.phase = "error";
          cellAnim.errorMessage = String(err);
          reRenderAnimationSection();
        }
      });
    });

    // Recover review state after a panel refresh that happened while a
    // job was still in flight — keep watching the original job id.
    const cellAnim = animState(current.category, current.asset_id);
    if (cellAnim.phase === "running" && cellAnim.jobId) {
      watchAnimationJob(current.category, current.asset_id, cellAnim.jobId, a);
    }

    panel.querySelector("[data-open-account]")?.addEventListener("click", (ev) => {
      ev.preventDefault();
      window.dispatchEvent(new CustomEvent("bf:open-account"));
    });
  }

  // Re-render only the animation pieces (action button + section body)
  // from cached panel data so flipping phase (idle → running → review →
  // error) doesn't trigger another /api/cell round-trip.
  function reRenderAnimationSection() {
    if (!current || !_lastPanelData) return;

    const oldSection = panel.querySelector("[data-anim-section]");
    if (oldSection) {
      const tmp = document.createElement("div");
      tmp.innerHTML = renderAnimationSection(_lastPanelData);
      const newSection = tmp.firstElementChild;
      if (newSection) oldSection.replaceWith(newSection);
    }

    // The Animate action lives in the Action group above the section;
    // its label flips between "Animate" and "Re-animate" + disabled
    // state so it has to be replaced too.
    const oldAction = panel.querySelector("[data-animate]");
    if (oldAction) {
      const tmp = document.createElement("div");
      tmp.innerHTML = renderAnimateAction(_lastPanelData);
      const newAction = tmp.firstElementChild;
      if (newAction) oldAction.replaceWith(newAction);
    }

    // Re-bind handlers on the freshly-built nodes. wireAnimation is
    // idempotent w.r.t. these elements — every querySelector starts
    // from the panel root so the new nodes get the listeners.
    wireAnimation(_lastPanelData);
  }

  /** When candidate loops arrive, bring the Animation section into view (sidebar is long). */
  function focusAnimationResultsInPanel() {
    requestAnimationFrame(() => {
      const sec = panel.querySelector("[data-anim-section]");
      if (!sec) return;
      sec.classList.remove("is-anim-pulse");
      void sec.offsetWidth;
      sec.classList.add("is-anim-pulse");
      window.setTimeout(() => {
        sec.classList.remove("is-anim-pulse");
      }, 2800);
      sec.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  }

  // Polling watcher specific to animation jobs. Mirrors watchJob() but
  // doesn't touch the cell SVG (animations don't change the static art).
  // Multiple cells can have animation jobs in flight at once, so each
  // watcher is keyed by (category, asset_id, job_id).
  const _animPollers = new Map();   // jobId -> intervalHandle
  function watchAnimationJob(category, assetId, jobId, animMeta) {
    if (_animPollers.has(jobId)) return;
    const handle = setInterval(async () => {
      try {
        const r = await fetch(`/jobs/${jobId}`);
        if (!r.ok) return;
        const j = await r.json();
        if (j.status !== "done" && j.status !== "failed" && j.status !== "killed") {
          return;
        }
        clearInterval(handle);
        _animPollers.delete(jobId);

        // The job is terminal; re-fetch what we need for the cell that
        // owns it. The user may have switched cells in the meantime —
        // stash the result in animStateByCell anyway, and only re-render
        // if the corresponding cell is still open.
        const k = cellKey(category, assetId);
        const cellAnim = animStateByCell[k] || animState(category, assetId);
        if (j.status !== "done") {
          cellAnim.phase = "error";
          cellAnim.errorMessage = (j.error || "job failed").slice(0, 240);
        } else {
          // Fetch the proposal manifest for the gallery.
          const url = animMeta.proposals_url_template.replace("{job_id}", jobId);
          try {
            const rr = await fetch(url, { cache: "no-store" });
            if (!rr.ok) {
              cellAnim.phase = "error";
              cellAnim.errorMessage = `proposals: ${rr.status}`;
            } else {
              const body = await rr.json();
              cellAnim.proposals = body;
              cellAnim.selectedIndex = 0;
              cellAnim.phase = "review";
            }
          } catch (err) {
            cellAnim.phase = "error";
            cellAnim.errorMessage = String(err);
          }
        }

        if (current
            && current.category === category
            && current.asset_id === assetId) {
          reRenderAnimationSection();
          if (cellAnim.phase === "review") {
            focusAnimationResultsInPanel();
          }
        }
      } catch (_) { /* swallow */ }
    }, 2000);
    _animPollers.set(jobId, handle);
  }

  function wireFrame(data) {
    const f = data.frame;
    if (!f) return;

    const section = panel.querySelector("[data-frame-section]");
    if (!section) return;

    section.querySelector("[data-frame-disable]")?.addEventListener("click", async () => {
      if (!confirm("Disable the frame on this board? Panels keep their art; only the rim overlay turns off.")) return;
      try {
        const r = await fetch(f.disable_endpoint, { method: "POST" });
        if (!r.ok) {
          alert("Disable failed: " + (await r.text()));
          return;
        }
        await refreshPanel();
        refreshBoardSvg();
      } catch (err) {
        alert("Network error: " + err);
      }
    });
  }

  // ─── Cell spinner — shown while a generation job is in flight ────────
  // Injects a semi-transparent overlay + rotating arc directly into the SVG
  // so the user sees activity inside the space being generated. Removed
  // automatically when refreshBoardSvg() replaces the board plate HTML.

  function showCellSpinner(category, assetId, positionRef = null) {
    const svg = plate.querySelector("svg");
    if (!svg) return;
    let sel = `a.bf-cell-link[data-category="${CSS.escape(category)}"][data-asset-id="${CSS.escape(assetId)}"]`;
    if (category === "spaces" && positionRef) {
      sel += `[data-position-ref="${CSS.escape(positionRef)}"]`;
    }
    const link = svg.querySelector(sel);
    if (!link) return;

    hideCellSpinner();

    const bb = link.getBBox();
    const cx = bb.x + bb.width / 2;
    const cy = bb.y + bb.height / 2;
    const r  = Math.min(bb.width, bb.height) * 0.22;
    const sw = Math.max(2, r * 0.28);
    const circ = 2 * Math.PI * r;
    const ns = "http://www.w3.org/2000/svg";

    const g = document.createElementNS(ns, "g");
    g.setAttribute("class", "bf-cell-spinner");
    g.setAttribute("pointer-events", "none");

    // dim overlay
    const dim = document.createElementNS(ns, "rect");
    dim.setAttribute("x", bb.x); dim.setAttribute("y", bb.y);
    dim.setAttribute("width", bb.width); dim.setAttribute("height", bb.height);
    dim.setAttribute("fill", "rgba(0,0,0,0.45)");
    g.appendChild(dim);

    // track ring
    const track = document.createElementNS(ns, "circle");
    track.setAttribute("cx", cx); track.setAttribute("cy", cy); track.setAttribute("r", r);
    track.setAttribute("fill", "none");
    track.setAttribute("stroke", SPINNER_STROKE_TRACK);
    track.setAttribute("stroke-width", sw);
    g.appendChild(track);

    // spinning arc
    const arc = document.createElementNS(ns, "circle");
    arc.setAttribute("cx", cx); arc.setAttribute("cy", cy); arc.setAttribute("r", r);
    arc.setAttribute("fill", "none");
    arc.setAttribute("stroke", SPINNER_STROKE_ARC);
    arc.setAttribute("stroke-width", sw);
    arc.setAttribute("stroke-dasharray", `${circ * 0.25} ${circ * 0.75}`);
    arc.setAttribute("stroke-linecap", "round");
    const { durSec, beginSec } = spinnerTiming(category, assetId);
    const anim = document.createElementNS(ns, "animateTransform");
    anim.setAttribute("attributeName", "transform");
    anim.setAttribute("type", "rotate");
    anim.setAttribute("from", `0 ${cx} ${cy}`);
    anim.setAttribute("to",   `360 ${cx} ${cy}`);
    anim.setAttribute("dur", `${durSec.toFixed(2)}s`);
    if (beginSec < 0) anim.setAttribute("begin", `${beginSec.toFixed(3)}s`);
    anim.setAttribute("repeatCount", "indefinite");
    arc.appendChild(anim);
    g.appendChild(arc);

    svg.appendChild(g);
  }

  function hideCellSpinner() {
    plate.querySelector(".bf-cell-spinner")?.remove();
  }

  function hideAllSpinners() {
    plate.querySelectorAll(".bf-cell-spinner").forEach(el => el.remove());
  }

  // Show a spinner on every space/panel cell that isn't already approved.
  // Called when a bulk generate.spaces or generate.all job starts.
  function showAllPendingSpinners() {
    const svg = plate.querySelector("svg");
    if (!svg) return;
    hideAllSpinners();
    svg.querySelectorAll(
      '[data-category="spaces"]:not(.bf-approved), [data-category="panels"]:not(.bf-approved)'
    ).forEach(link => {
      const bb = link.getBBox();
      if (!bb.width || !bb.height) return;
      const cat = link.getAttribute("data-category") || "";
      const aid = link.getAttribute("data-asset-id") || "";
      const cx = bb.x + bb.width / 2;
      const cy = bb.y + bb.height / 2;
      const r  = Math.min(bb.width, bb.height) * 0.22;
      const sw = Math.max(2, r * 0.28);
      const circ = 2 * Math.PI * r;
      const ns = "http://www.w3.org/2000/svg";
      const { durSec, beginSec } = spinnerTiming(cat, aid);

      const g = document.createElementNS(ns, "g");
      g.setAttribute("class", "bf-cell-spinner");
      g.setAttribute("pointer-events", "none");

      const dim = document.createElementNS(ns, "rect");
      dim.setAttribute("x", bb.x); dim.setAttribute("y", bb.y);
      dim.setAttribute("width", bb.width); dim.setAttribute("height", bb.height);
      dim.setAttribute("fill", "rgba(0,0,0,0.45)");
      g.appendChild(dim);

      const track = document.createElementNS(ns, "circle");
      track.setAttribute("cx", cx); track.setAttribute("cy", cy); track.setAttribute("r", r);
      track.setAttribute("fill", "none");
      track.setAttribute("stroke", SPINNER_STROKE_TRACK);
      track.setAttribute("stroke-width", sw);
      g.appendChild(track);

      const arc = document.createElementNS(ns, "circle");
      arc.setAttribute("cx", cx); arc.setAttribute("cy", cy); arc.setAttribute("r", r);
      arc.setAttribute("fill", "none");
      arc.setAttribute("stroke", SPINNER_STROKE_ARC);
      arc.setAttribute("stroke-width", sw);
      arc.setAttribute("stroke-dasharray", `${circ * 0.25} ${circ * 0.75}`);
      arc.setAttribute("stroke-linecap", "round");
      const anim = document.createElementNS(ns, "animateTransform");
      anim.setAttribute("attributeName", "transform");
      anim.setAttribute("type", "rotate");
      anim.setAttribute("from", `0 ${cx} ${cy}`);
      anim.setAttribute("to",   `360 ${cx} ${cy}`);
      anim.setAttribute("dur", `${durSec.toFixed(2)}s`);
      if (beginSec < 0) anim.setAttribute("begin", `${beginSec.toFixed(3)}s`);
      anim.setAttribute("repeatCount", "indefinite");
      arc.appendChild(anim);
      g.appendChild(arc);

      svg.appendChild(g);
    });
  }

  // ─── Board refresh after live changes ─────────────────────────────────
  // Reload only the SVG fragment so the current cell's image updates without
  // losing scroll/panel state. Cheap because the SVG is a server-rendered
  // string; we re-fetch the home page and swap just the .board-plate.

  async function refreshBoardSvg() {
    try {
      const r = await fetch(`${BPATH}/`, { cache: "no-store" });
      if (!r.ok) return;
      const html = await r.text();
      const doc = new DOMParser().parseFromString(html, "text/html");
      const newPlate = doc.getElementById("board-plate");
      if (newPlate) {
        plate.innerHTML = newPlate.innerHTML;
        if (current) markSelected(current.category, current.asset_id, current.position_ref);
      }
    } catch (_) { /* swallow */ }
  }

  // ─── Listen for job updates from jobs.js ─────────────────────────────
  // jobs.js dispatches bf:job-update for every SSE update. We use it here
  // to show bulk-generation spinners and refresh individual spaces as they
  // complete, without waiting for the whole job to finish.
  let _lastSpacesProgress = -1;
  let _spaceRefreshPending = false;
  let _deferredBulkSvgRefresh = false;

  // Coalesce rapid bf:job-update traffic: full-page fetch + SVG rebuild is expensive.
  let _bulkSvgRefreshTimer = null;
  let _bulkSvgMinIntervalMs = 900;
  let _lastBulkSvgRefreshAt = 0;

  function scheduleBulkBoardSvgRefreshCore() {
    const now = Date.now();
    const elapsed = now - _lastBulkSvgRefreshAt;
    const run = () => {
      _bulkSvgRefreshTimer = null;
      _lastBulkSvgRefreshAt = Date.now();
      _spaceRefreshPending = true;
      refreshBoardSvg().then(() => {
        _spaceRefreshPending = false;
        if (_lastSpacesProgress >= 0) showAllPendingSpinners();
      });
    };
    if (_bulkSvgRefreshTimer) clearTimeout(_bulkSvgRefreshTimer);
    if (elapsed >= _bulkSvgMinIntervalMs) {
      run();
      return;
    }
    _bulkSvgRefreshTimer = setTimeout(run, _bulkSvgMinIntervalMs - elapsed);
  }

  /** Defer full-page plate reload while the panel is open or mid-fetch — those GETs starve /api/cell. */
  function scheduleBulkBoardSvgRefresh() {
    if (panel.classList.contains("is-swapping")) {
      _deferredBulkSvgRefresh = true;
      return;
    }
    if (current && panel.classList.contains("is-open")) {
      _deferredBulkSvgRefresh = true;
      return;
    }
    scheduleBulkBoardSvgRefreshCore();
  }

  window.addEventListener("bf:job-update", e => {
    const j = e.detail;
    if (j.operation !== "generate.spaces" && j.operation !== "generate.all") return;

    if (j.status === "queued" || j.status === "running") {
      const progress = j.progress ?? 0;

      if (_lastSpacesProgress === -1) {
        _lastSpacesProgress = progress;
        showAllPendingSpinners();
        return;
      }

      if (progress !== _lastSpacesProgress && !_spaceRefreshPending) {
        _lastSpacesProgress = progress;
        scheduleBulkBoardSvgRefresh();
      }
    } else {
      if (_bulkSvgRefreshTimer) {
        clearTimeout(_bulkSvgRefreshTimer);
        _bulkSvgRefreshTimer = null;
      }
      _lastSpacesProgress = -1;
      _spaceRefreshPending = false;
      hideAllSpinners();
      if (_deferredBulkSvgRefresh) {
        _deferredBulkSvgRefresh = false;
        scheduleBulkBoardSvgRefreshCore();
      }
    }
  });

  let pollHandle = null;
  let _pollInFlight = false;
  function watchJob() {
    if (!watchedJobId) return;
    if (pollHandle) clearInterval(pollHandle);
    pollHandle = setInterval(async () => {
      if (!watchedJobId) {
        clearInterval(pollHandle);
        pollHandle = null;
        return;
      }
      if (_pollInFlight) return;
      _pollInFlight = true;
      try {
        const r = await fetch(`/jobs/${watchedJobId}`);
        if (!r.ok) return;
        const j = await r.json();
        if (j.status === "done" || j.status === "failed" || j.status === "killed") {
          clearInterval(pollHandle);
          pollHandle = null;
          watchedJobId = null;
          hideCellSpinner();
          if (current) {
            const data = await refreshPanel();
            const updated = updateCellImageOnBoard(current.category, current.asset_id, data?.live_url);
            if (!updated) refreshBoardSvg();
          }
        }
      } catch (_) { /* swallow */ }
      finally {
        _pollInFlight = false;
      }
    }, 1500);
  }
  // Start polling when a cell job id is set; outer loop only (re)starts if needed.
  setInterval(() => {
    if (watchedJobId && !pollHandle) watchJob();
  }, 500);

  // ─── Helpers ─────────────────────────────────────────────────────────

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function escapeAttr(s) { return escapeHtml(s); }

  // ─── Deep-link via hash on load ──────────────────────────────────────

  function openFromHash() {
    const h = window.location.hash.slice(1);
    if (!h) return;
    if (h.includes("/")) {
      const parts = h.split("/").map((p) => {
        try {
          return decodeURIComponent(p);
        } catch {
          return p;
        }
      });
      if (parts.length >= 3 && parts[0] === "spaces") {
        openCell(parts[0], parts[1], parts[2]);
        return;
      }
    }
    const colon = h.indexOf(":");
    if (colon < 0) return;
    const cat = h.slice(0, colon);
    const aid = h.slice(colon + 1);
    if (cat && aid) openCell(cat, aid, null);
  }
  openFromHash();

  // Also expose for manual triggers from elsewhere if we want to.
  window.bfOpenCell = openCell;
})();
