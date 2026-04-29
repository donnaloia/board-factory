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

  let current = null;            // { category, asset_id }
  let watchedJobId = null;       // job id we're waiting on for a refresh

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
    refreshPanel().finally(() => {
      panel.classList.remove("is-swapping");
    });
    // Update URL hash so reload returns to same cell.
    history.replaceState(null, "", `#${category}:${asset_id}`);
  }

  function closePanel() {
    current = null;
    wrap.classList.add("is-panel-closed");
    panel.classList.remove("is-open");
    panel.setAttribute("aria-hidden", "true");
    setTimeout(() => { panel.innerHTML = ""; }, 250);
    clearSelected();
    history.replaceState(null, "", window.location.pathname);
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
    try {
      const r = await fetch(`${BPATH}/api/cell/${current.category}/${current.asset_id}`);
      if (!r.ok) {
        panel.innerHTML = `<p class="muted">Could not load cell.</p>`;
        return;
      }
      const data = await r.json();
      panel.innerHTML = renderPanel(data);
      wireActions(data);
    } catch (e) {
      panel.innerHTML = `<p class="muted">Network error.</p>`;
    }
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
    const liveBlock = data.has_live
      ? `<div class="cell-live ${data.frame_locked ? 'with-frame' : ''}">
           <img src="${data.live_url}" alt="">
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

      ${data.frame_locked ? `
      <div class="cell-panel-section">
        <h4>Frame</h4>
        <p class="frame-locked-note">
          <span class="frame-lock">◆ locked</span>
          regen repaints the interior only &mdash; the house frame stays bit-identical.
          <a href="/b/${data.board_id}/frame">manage frame</a>
        </p>
      </div>` : ""}

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
          <span>Clean image</span>
          <span class="est">free · ~1s</span>
        </button>
      </div>

      <div class="cell-panel-section">
        <h4>History · ${data.history.length}</h4>
        ${histBlock}
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
      refine: "refined",
      legacy: "imported",
    })[h.operation] || h.operation || "";
    const marker = h.is_live ? "live" : "restore →";
    const promptAttr = h.prompt != null ? escapeAttr(h.prompt) : "";
    return `
      <button type="button" class="history-row ${h.is_live ? "is-live" : ""}"
              data-promote="${escapeAttr(h.filename)}"
              data-prompt="${promptAttr}"
              data-has-prompt="${h.prompt != null ? "1" : "0"}">
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
        // Send the textarea contents as the override. The server treats
        // empty / catalog-equal values as "no override" so this is safe.
        if (editor) fd.append("prompt_override", editor.value || "");
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
      } catch (err) {
        alert("Network error: " + err);
        btn.removeAttribute("disabled");
      }
    });

    // ─── Clean image (re-quantize + grid-snap the live image) ───
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
          alert("Clean failed: " + (await res.text()));
          btn.removeAttribute("disabled");
          return;
        }
        const json = await res.json();
        watchedJobId = json.job_id;
      } catch (err) {
        alert("Network error: " + err);
        btn.removeAttribute("disabled");
      }
    });

    // ─── History row click: promote + restore that entry's prompt ───
    panel.querySelectorAll("[data-promote]").forEach(btn => {
      btn.addEventListener("click", async () => {
        const filename = btn.getAttribute("data-promote");
        const hasPrompt = btn.getAttribute("data-has-prompt") === "1";
        const promptForEntry = btn.getAttribute("data-prompt") || "";

        const fd = new FormData();
        fd.append("filename", filename);
        const r = await fetch(`${BPATH}/api/cell/${current.category}/${current.asset_id}/promote`,
                              { method: "POST", body: fd });
        if (r.ok) {
          await refreshPanel();
          refreshBoardSvg();
          // After refreshPanel re-renders, restore the textarea to this
          // entry's prompt if it had one (so the editor shows what produced
          // the asset that's now live).
          if (hasPrompt) {
            const newEditor = panel.querySelector("[data-prompt-editor]");
            if (newEditor) {
              newEditor.value = promptForEntry;
              newEditor.setAttribute("data-base", promptForEntry);
              newEditor.dispatchEvent(new Event("input"));
            }
          }
        }
      });
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
  // jobs.js doesn't dispatch events today; we listen for our watched job
  // settling by polling /jobs/<id>. Cheap because it only runs while the
  // user has a job in flight from this panel.

  let pollHandle = null;
  function watchJob() {
    if (!watchedJobId) return;
    if (pollHandle) clearInterval(pollHandle);
    pollHandle = setInterval(async () => {
      if (!watchedJobId) { clearInterval(pollHandle); return; }
      try {
        const r = await fetch(`/jobs/${watchedJobId}`);
        if (!r.ok) return;
        const j = await r.json();
        if (j.status === "done" || j.status === "failed" || j.status === "killed") {
          clearInterval(pollHandle);
          pollHandle = null;
          watchedJobId = null;
          if (current) {
            await refreshPanel();
            refreshBoardSvg();
          }
        }
      } catch (_) { /* swallow */ }
    }, 1500);
  }
  // Start a continuous watcher; it idles when watchedJobId is null.
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
