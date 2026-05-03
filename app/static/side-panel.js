// side-panel.js
//
// Replaces the per-page experience with an inline side panel docked to the
// right of the board. Clicking any cell on the SVG opens the panel for that
// cell with: live preview, prompt + metadata, regenerate button, and a
// chronological history strip the user can flip between.
//
// Selection model:
//   - Click a cell → swap panel content to that cell (with a quick fade)
//   - Click another cell → panel content swaps in place
//   - Click outside the board (background of board-plate) → panel fades out
//   - X button on the panel → panel closes
//   - URL hash #<category>:<asset_id> deep-links to a preselected cell
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
  const BPATH = `/b/${BOARD_ID}`;

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

  let current = null;            // { category, asset_id }
  let watchedJobId = null;       // job id we're waiting on for a refresh

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
      openCell(category, asset_id);
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

  function openCell(category, asset_id) {
    if (current && current.category === category && current.asset_id === asset_id) {
      return; // already open
    }
    current = { category, asset_id };
    markSelected(category, asset_id);
    wrap.classList.remove("is-panel-closed");
    panel.classList.add("is-open");
    panel.classList.add("is-swapping");
    panel.setAttribute("aria-hidden", "false");
    const openedKey = `${category}:${asset_id}`;
    refreshPanel().finally(() => {
      // Another cell may have been opened while this fetch was in flight.
      if (!current || `${current.category}:${current.asset_id}` !== openedKey) return;
      panel.classList.remove("is-swapping");
      scheduleBulkBoardSvgRefresh();
    });
    // Update URL hash so reload returns to same cell.
    history.replaceState(null, "", `#${category}:${asset_id}`);
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

  function markSelected(category, asset_id) {
    clearSelected();
    plate.querySelectorAll(`a.bf-cell-link[data-category="${category}"][data-asset-id="${cssEscape(asset_id)}"]`)
      .forEach(el => el.classList.add("is-selected"));
  }
  function clearSelected() {
    plate.querySelectorAll("a.bf-cell-link.is-selected")
      .forEach(el => el.classList.remove("is-selected"));
  }
  function cssEscape(s) {
    return (window.CSS && CSS.escape) ? CSS.escape(s) : s.replace(/"/g, '\\"');
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
        return null;
      }
      const data = await r.json();
      if (seq !== _panelFetchSeq) return null;
      panel.innerHTML = renderPanel(data);
      wireActions(data);
      return data;
    } catch (e) {
      if (e && (e.name === "AbortError" || e.code === 20)) return null;
      if (seq !== _panelFetchSeq) return null;
      panel.innerHTML = `<p class="muted">Network error.</p>`;
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

  function renderPanel(data) {
    const spec = data.spec;
    const sizeStr = spec.size ? `${spec.size[0]} × ${spec.size[1]}` : "—";
    const usesStr = spec.uses === 1 ? "1 position" : `${spec.uses} positions`;
    const eyebrow = ({
      space: "Perimeter",
      panel: "Functional",
      centerpiece: "Marquee",
    })[spec.kind] || "Cell";

    // Live preview — when a frame is locked, overlay the composed frame on
    // top so what the user sees in the panel matches what's on the board.
    // Append a timestamp bust so the browser always fetches the current live
    // image even if the mtime-stamped URL matches a previously loaded one.
    const liveSrc = data.live_url
      ? `${data.live_url.split("?")[0]}?_=${Date.now()}`
      : null;
    const liveBlock = data.has_live
      ? `<div class="cell-live ${data.frame_locked ? 'with-frame' : ''}">
           <img src="${liveSrc}" alt="">
           ${data.frame_locked && data.frame_url
              ? `<img class="frame-overlay" src="${data.frame_url}" alt="" aria-hidden="true">`
              : ''}
         </div>`
      : `<div class="cell-live empty">no asset yet</div>`;

    const histBlock = data.history.length === 0
      ? `<p class="cell-history-empty">no history yet — generate to make some.</p>`
      : `<div class="cell-history">${data.history.map(h => renderHistoryRow(h)).join("")}</div>`;

    const cost = data.regen_estimate_usd > 0
      ? `~$${data.regen_estimate_usd.toFixed(3)} · ${data.candidates_per_regen} candidates`
      : `free · ${data.candidates_per_regen} candidates`;

    // Whether the catalog prompt differs from the active (live's) prompt.
    const promptInherited = (data.active_prompt || "") === (data.catalog_prompt || "");

    return `
      <div class="cell-panel-head">
        <div>
          <span class="panel-eyebrow">${eyebrow}</span>
          <h3 class="panel-title">${escapeHtml(spec.title)}</h3>
          <span class="panel-id">${escapeHtml(spec.id)}</span>
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
                  data-base="${escapeAttr(data.active_prompt || "")}"
                  data-catalog="${escapeAttr(data.catalog_prompt || "")}"
                  spellcheck="false"
                  rows="4">${escapeHtml(data.active_prompt || "")}</textarea>
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
        <button class="panel-action is-placeholder" type="button" data-download
                aria-disabled="true" title="Coming soon">
          <span class="arrow">→</span>
          <span>Download</span>
          <span class="est">soon</span>
        </button>
      </div>

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
    const f = data.frame;

    // Status copy: covers all four states so the user always knows where
    // they stand without having to expand the picker.
    let summary;
    if (!f.adopted || !f.enabled) {
      summary = `<span class="frame-empty">no frame · pick a source below</span>`;
    } else if (f.applied_to_this_cell) {
      summary = `<span class="frame-lock">◆ locked</span> from <code>${escapeHtml(f.adopted_meta?.source_id || "—")}</code> · ${f.adopted_meta?.ring_px ?? "—"}px ring`;
    } else {
      summary = `frame adopted board-wide · this panel will pick it up on the next generate`;
    }

    const sources = [
      ...f.panel_sources.map(s => ({ ...s, kind: "panel" })),
      ...(f.mockup_source ? [{ ...f.mockup_source, kind: "mockup" }] : []),
    ];

    // What's the server-recorded "currently adopted" source? We use this to
    // mark the right card as `is-active` so what you see matches the truth.
    const adoptedKind = f.adopted ? f.adopted_meta?.source_kind : null;
    const adoptedId = f.adopted ? f.adopted_meta?.source_id : null;
    const isAdopted = (s) => f.adopted && f.enabled
                          && s.kind === adoptedKind && s.id === adoptedId;

    // The first source the user can preview — used to seed the slider's
    // preview pane when nothing is adopted yet.
    const previewSeed = sources.find(isAdopted)
                     || sources.find(s => s.kind === "mockup")
                     || sources[0]
                     || null;

    const sourceCards = sources.length === 0
      ? ""  // we still render the None card below
      : sources.map(s => `
          <button type="button" class="frame-source ${isAdopted(s) ? "is-active" : ""}"
                  data-frame-source-kind="${s.kind}"
                  data-frame-source-id="${escapeAttr(s.id)}"
                  data-frame-source-w="${s.size[0]}"
                  data-frame-source-h="${s.size[1]}">
            <div class="frame-source-thumb"><img src="${s.url}" alt=""></div>
            <span class="frame-source-label">${escapeHtml(s.label)}</span>
            <span class="frame-source-kind">${s.kind}</span>
          </button>
        `).join("");

    // The "None" card disables the frame board-wide. Active when there is
    // no adopted+enabled frame.
    const noneActive = !f.adopted || !f.enabled;
    const noneCard = `
      <button type="button" class="frame-source frame-source-none ${noneActive ? "is-active" : ""}"
              data-frame-none>
        <div class="frame-source-thumb">
          <span class="frame-none-icon" aria-hidden="true">∅</span>
        </div>
        <span class="frame-source-label">None</span>
        <span class="frame-source-kind">no frame</span>
      </button>
    `;

    const noSourcesNote = sources.length === 0
      ? `<p class="frame-no-sources">No panel art yet — generate at least one functional panel to extract a frame from, or use the mockup once it loads.</p>`
      : "";

    return `
      <div class="cell-panel-section frame-section" data-frame-section>
        <h4>
          <span>Frame</span>
          <button type="button" class="frame-toggle" data-frame-toggle aria-expanded="false">
            Show
          </button>
        </h4>
        <p class="frame-summary">${summary}</p>

        <div class="frame-picker" data-frame-picker hidden>
          <p class="frame-picker-blurb">
            One frame is shared by every functional panel. Click a source to
            adopt it &mdash; every panel reuses the same frame. Pick
            <em>None</em> to drop the frame entirely.
          </p>

          <div class="frame-source-grid">
            ${sourceCards}
            ${noneCard}
          </div>
          ${noSourcesNote}

          ${previewSeed ? `
          <div class="frame-ring">
            <label class="frame-ring-row">
              <span class="frame-ring-label">Ring thickness</span>
              <input type="range" min="${f.min_ring_px}" max="${f.max_ring_px}"
                     value="${f.adopted_meta?.ring_px || f.default_ring_px}"
                     step="1" data-frame-ring>
              <span class="frame-ring-value" data-frame-ring-value>${f.adopted_meta?.ring_px || f.default_ring_px}px</span>
            </label>

            <div class="frame-preview-row">
              <div class="frame-preview-mount">
                <img class="frame-preview-img" data-frame-preview-img alt=""
                     src="">
                <div class="frame-preview-interior"></div>
              </div>
              <p class="frame-preview-caption">live 9-slice preview · release slider to apply</p>
            </div>
          </div>
          ` : ""}

          <div class="frame-actions">
            <button type="button" class="panel-action is-placeholder" data-frame-generate
                    aria-disabled="true"
                    title="Coming soon: AI-generate a brand-new frame from the board's mood and mockup.">
              <span class="arrow">→</span>
              <span>Generate new frame</span>
              <span class="est">soon · AI from mood</span>
            </button>
          </div>
        </div>
      </div>
    `;
  }

  function renderHistoryRow(h) {
    const date = new Date(h.ts_ms);
    const ts = date.toLocaleString(undefined, {
      month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
    const opLabel = ({
      regen: "generated",
      clean: "cleaned",
    })[h.operation] || h.operation || "";
    const marker = h.is_live ? "live" : "restore →";
    return `
      <button type="button" class="history-row ${h.is_live ? "is-live" : ""}"
              data-promote="${escapeAttr(h.filename)}">
        <div class="thumb"><img src="${h.url}" alt=""></div>
        <div class="meta-col">
          <span class="ts">${ts}</span>
          <span class="marker">${opLabel} · ${marker}</span>
        </div>
      </button>
    `;
  }

  function wireActions(data) {
    panel.querySelector(".cell-panel-close")?.addEventListener("click", closePanel);

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
        showCellSpinner(current.category, current.asset_id);
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
        showCellSpinner(current.category, current.asset_id);
      } catch (err) {
        alert("Network error: " + err);
        btn.removeAttribute("disabled");
      }
    });

    // ─── Frame section: expand/collapse + live preview + adopt/disable ───
    wireFrame(data);

    // ─── History row click: promote + restore that entry's prompt ───
    // Prompts come from the JSON payload / refresh response — not HTML
    // data-* attributes (long prompts and quoting break attribute round-trips).
    const historyRows = data.history;
    panel.querySelectorAll("[data-promote]").forEach(btn => {
      btn.addEventListener("click", async () => {
        const filename = btn.getAttribute("data-promote");
        const entry = historyRows.find(h => h.filename === filename);
        const editorImmediate = panel.querySelector("[data-prompt-editor]");
        if (editorImmediate && entry?.prompt != null) {
          editorImmediate.value = entry.prompt;
          editorImmediate.setAttribute("data-base", entry.prompt);
          editorImmediate.dispatchEvent(new Event("input"));
        }

        const fd = new FormData();
        fd.append("filename", filename);
        const r = await fetch(`${BPATH}/api/cell/${current.category}/${current.asset_id}/promote`,
                              { method: "POST", body: fd });
        if (r.ok) {
          const fresh = await refreshPanel();
          const updated = updateCellImageOnBoard(current.category, current.asset_id, fresh?.live_url);
          if (!updated) refreshBoardSvg();
          const newEditor = panel.querySelector("[data-prompt-editor]");
          if (newEditor) {
            const row = fresh?.history?.find(h => h.filename === filename);
            const val = row?.prompt != null
              ? row.prompt
              : (fresh?.active_prompt ?? "");
            newEditor.value = val;
            newEditor.setAttribute("data-base", val);
            newEditor.dispatchEvent(new Event("input"));
          }
        }
      });
    });
  }

  // ─── Frame picker wiring ─────────────────────────────────────────────
  // Why this lives here: the frame is a board-level resource (one shared
  // across all panels) but it's authored per-panel — you discover it where
  // you're already looking. The picker stays inline so the user never
  // loses sight of the board behind them.

  function wireFrame(data) {
    const f = data.frame;
    if (!f) return;

    const section = panel.querySelector("[data-frame-section]");
    if (!section) return;

    const toggle = section.querySelector("[data-frame-toggle]");
    const picker = section.querySelector("[data-frame-picker]");
    const slider = section.querySelector("[data-frame-ring]");
    const valueLabel = section.querySelector("[data-frame-ring-value]");

    // The card the user is currently *previewing* (which may or may not be
    // the same as what the server has adopted). On adopt success, this
    // becomes the truth via refreshPanel().
    let previewCard = section.querySelector(".frame-source.is-active:not(.frame-source-none)")
                   || section.querySelector(".frame-source:not(.frame-source-none)");

    toggle?.addEventListener("click", () => {
      const isOpen = !picker.hidden;
      picker.hidden = isOpen;
      toggle.setAttribute("aria-expanded", String(!isOpen));
      toggle.textContent = isOpen ? "Show" : "Hide";
      if (!isOpen) refreshFramePreview();
    });

    // ─── Click-to-adopt on extract sources ───
    section.querySelectorAll(".frame-source:not(.frame-source-none)").forEach(card => {
      card.addEventListener("click", () => {
        previewCard = card;
        // Visually preview-select immediately. The server response will
        // confirm via refreshPanel().
        section.querySelectorAll(".frame-source").forEach(
          c => c.classList.remove("is-active"));
        card.classList.add("is-active");
        refreshFramePreview();
        adoptCard(card);
      });
    });

    // ─── Click-to-disable on the None card ───
    section.querySelector("[data-frame-none]")?.addEventListener("click", () => {
      section.querySelectorAll(".frame-source").forEach(
        c => c.classList.remove("is-active"));
      section.querySelector("[data-frame-none]").classList.add("is-active");
      disableFrame();
    });

    // ─── Slider: live preview during drag, re-adopt on release ───
    let dragTimer = null;
    slider?.addEventListener("input", () => {
      if (valueLabel) valueLabel.textContent = `${slider.value}px`;
      if (dragTimer) clearTimeout(dragTimer);
      dragTimer = setTimeout(refreshFramePreview, 120);
    });
    slider?.addEventListener("change", () => {
      // Fires on release. Re-adopt with the new ring thickness IF a real
      // source is currently selected (not None).
      const active = section.querySelector(".frame-source.is-active:not(.frame-source-none)");
      if (active) adoptCard(active);
    });

    // Placeholder — eventual behavior: AI-generate a brand-new frame from
    // the board's mood/mockup. Just absorbs the click for now.
    section.querySelector("[data-frame-generate]")?.addEventListener("click", (e) => {
      e.preventDefault();
    });

    // ─── Network actions ───

    async function adoptCard(card) {
      // Block multiple adopts in flight: lock the whole grid, unlock on
      // settle. Cheap server side, but stops the UI from flickering.
      section.querySelectorAll(".frame-source").forEach(c => c.setAttribute("aria-busy", "true"));
      try {
        const fd = new FormData();
        fd.append("source_kind", card.getAttribute("data-frame-source-kind"));
        fd.append("source_id", card.getAttribute("data-frame-source-id"));
        fd.append("ring_px", slider?.value || String(f.default_ring_px));
        fd.append("enable_after", "true");
        const r = await fetch(f.adopt_endpoint, { method: "POST", body: fd });
        if (!r.ok) {
          alert("Adopt failed: " + (await r.text()));
          return;
        }
        await refreshPanel();
        refreshBoardSvg();
      } finally {
        section.querySelectorAll(".frame-source").forEach(c => c.removeAttribute("aria-busy"));
      }
    }

    async function disableFrame() {
      section.querySelectorAll(".frame-source").forEach(c => c.setAttribute("aria-busy", "true"));
      try {
        const r = await fetch(f.disable_endpoint, { method: "POST" });
        if (!r.ok) {
          alert("Disable failed: " + (await r.text()));
          return;
        }
        await refreshPanel();
        refreshBoardSvg();
      } finally {
        section.querySelectorAll(".frame-source").forEach(c => c.removeAttribute("aria-busy"));
      }
    }

    function refreshFramePreview() {
      const img = section.querySelector("[data-frame-preview-img]");
      if (!previewCard || !img) return;
      const ring = slider?.value || String(f.default_ring_px);
      const w = previewCard.getAttribute("data-frame-source-w");
      const h = previewCard.getAttribute("data-frame-source-h");
      const displayW = 220;
      const displayH = Math.max(120, Math.round(220 * (h / w)));
      const url = `${f.preview_endpoint}`
        + `?source_kind=${encodeURIComponent(previewCard.getAttribute("data-frame-source-kind"))}`
        + `&source_id=${encodeURIComponent(previewCard.getAttribute("data-frame-source-id"))}`
        + `&ring_px=${encodeURIComponent(ring)}`
        + `&w=${displayW}&h=${displayH}`
        + `&t=${Date.now()}`;
      img.src = url;
      img.style.width = `${displayW}px`;
      img.style.height = `${displayH}px`;
    }
  }

  // ─── Cell spinner — shown while a generation job is in flight ────────
  // Injects a semi-transparent overlay + rotating arc directly into the SVG
  // so the user sees activity inside the space being generated. Removed
  // automatically when refreshBoardSvg() replaces the board plate HTML.

  function showCellSpinner(category, assetId) {
    const svg = plate.querySelector("svg");
    if (!svg) return;
    const link = svg.querySelector(
      `[data-category="${CSS.escape(category)}"][data-asset-id="${CSS.escape(assetId)}"]`
    );
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
        if (current) markSelected(current.category, current.asset_id);
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
    const colon = h.indexOf(":");
    if (colon < 0) return;
    const cat = h.slice(0, colon);
    const aid = h.slice(colon + 1);
    if (cat && aid) openCell(cat, aid);
  }
  openFromHash();

  // Also expose for manual triggers from elsewhere if we want to.
  window.bfOpenCell = openCell;
})();
