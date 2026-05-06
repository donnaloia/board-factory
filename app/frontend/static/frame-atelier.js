// Frame Atelier — three-phase Propose / Refine / Commit + Approach D batch.
//
// Uses fetch + the existing `bf:job-update` events that jobs.js dispatches
// from /events/jobs SSE; we never open a second EventSource here.
//
// Phases:
//   1. Propose — pick a source (panel / mockup / upload), POST /api/frame/propose,
//      consume vision-job progress, then GET /api/frame/proposals/<job_id> to
//      hydrate the candidate list.
//   2. Refine — show the chosen candidate's overlay over the source image,
//      offer a ring-thickness slider that drives a live preview at typical
//      panel size (the existing /api/frame/preview.png endpoint stays the
//      source of truth so the rim renders the same way the compositor would).
//   3. Commit — POST /api/frame/commit with the selected candidate +
//      ring_px, optionally enable + enqueue frame.reapply (Approach D),
//      then surface batch progress per panel via the same SSE bus.

(function () {
  const root = document.querySelector(".frame-atelier");
  if (!root) return;

  const boardBase = root.dataset.boardBase || "";
  const hasOpenAIKey = root.dataset.hasOpenaiKey === "1";
  const defaultRing = parseInt(root.dataset.defaultRing, 10) || 14;
  const minRing = parseInt(root.dataset.minRing, 10) || 2;
  const maxRing = parseInt(root.dataset.maxRing, 10) || 64;
  const typicalW = parseInt(root.dataset.typicalW, 10) || 260;
  const typicalH = parseInt(root.dataset.typicalH, 10) || 240;
  const nPanels = parseInt(root.dataset.nPanels, 10) || 0;

  const dom = {
    phases: root.querySelectorAll(".atelier-phases .phase"),
    proposePane: root.querySelector('[data-pane="propose"]'),
    refinePane: root.querySelector('[data-pane="refine"]'),
    commitPane: root.querySelector('[data-pane="commit"]'),
    progressOverlay: root.querySelector("[data-progress-overlay]"),
    sourceTabs: root.querySelectorAll("[data-source-tab]"),
    sourceGrids: root.querySelectorAll("[data-source-grid]"),
    uploadInput: root.querySelector("#atelier-upload-input"),
    uploadDrop: root.querySelector("[data-upload-drop]"),
    uploadList: root.querySelector("[data-upload-list]"),
    runVision: root.querySelector("[data-run-vision]"),
    visionCostEst: root.querySelector("[data-vision-cost-est]"),
    visionStatus: root.querySelector("[data-vision-status]"),
    visionSummary: root.querySelector("[data-vision-summary]"),
    visionBar: root.querySelector("[data-vision-bar]"),
    visionLog: root.querySelector("[data-vision-log]"),
    useVision: root.querySelector("#atelier-use-vision"),
    candidateList: root.querySelector("[data-candidate-list]"),
    rerunVision: root.querySelector("[data-rerun-vision]"),
    stageSource: root.querySelector("[data-stage-source]"),
    stageOverlay: root.querySelector("[data-stage-overlay]"),
    stageHandles: root.querySelector("[data-stage-handles]"),
    toggleOverlay: root.querySelector("[data-toggle-overlay]"),
    snapToGrid: root.querySelector("[data-snap-to-grid]"),
    ringSlider: root.querySelector("[data-ring-slider]"),
    ringValue: root.querySelector("[data-ring-value]"),
    metaSource: root.querySelector("[data-meta-source]"),
    metaSourceSize: root.querySelector("[data-meta-source-size]"),
    metaModel: root.querySelector("[data-meta-model]"),
    metaScore: root.querySelector("[data-meta-score]"),
    previewImg: root.querySelector("[data-preview-img]"),
    enableAfter: root.querySelector("[data-enable-after]"),
    regenPanels: root.querySelector("[data-regen-panels]"),
    commit: root.querySelector("[data-commit]"),
    commitCostEst: root.querySelector("[data-commit-cost-est]"),
    progressTitle: root.querySelector("[data-progress-title]"),
    progressSummary: root.querySelector("[data-progress-summary]"),
    progressBar: root.querySelector("[data-progress-bar]"),
    progressGrid: root.querySelector("[data-progress-grid]"),
    cancelRegen: root.querySelector("[data-cancel-regen]"),
    progressDone: root.querySelector("[data-progress-done]"),
    disable: root.querySelector("[data-disable]"),
    statusState: root.querySelector("[data-status-state]"),
    statusMeta: root.querySelector("[data-status-meta]"),
    statusRing: root.querySelector("[data-status-ring]"),
  };

  const state = {
    activeTab: "panel",
    selectedSource: null,        // { kind, id, w, h, label, url }
    proposalJobId: null,
    candidates: [],              // [{ index, bbox, ring_px, score, model_id, preview_url, ... }]
    activeCandidateIndex: null,
    showOverlay: true,
    ringPx: defaultRing,
    regenJobId: null,
    panelStates: new Map(),      // panel_id -> "queued" | "running" | "done" | "failed"
  };

  const fmtMoney = (n) => {
    if (!n) return "free";
    if (n < 0.01) return "$" + n.toFixed(4);
    return "$" + n.toFixed(2);
  };

  // Convenience for the "do you have a key?" copy.
  const visionAvailable = () => hasOpenAIKey && dom.useVision.checked;

  function setActivePhase(name) {
    dom.phases.forEach((el) => {
      const p = el.dataset.phase;
      el.classList.toggle("is-current", p === name);
    });
  }

  function hide(el) { if (el) el.hidden = true; }
  function show(el) { if (el) el.hidden = false; }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // ─────────── tabs ───────────

  dom.sourceTabs.forEach((btn) => {
    btn.addEventListener("click", () => {
      const which = btn.dataset.sourceTab;
      dom.sourceTabs.forEach((b) => b.classList.toggle("is-active", b === btn));
      dom.sourceGrids.forEach((g) => {
        g.hidden = g.dataset.sourceGrid !== which;
      });
      state.activeTab = which;
    });
  });

  // ─────────── source selection ───────────

  function wireSourceCards() {
    root.querySelectorAll("[data-source-kind]").forEach((card) => {
      if (card.classList.contains("is-disabled")) return;
      card.addEventListener("click", () => {
        root.querySelectorAll(".atelier-source-card.is-active")
          .forEach((c) => c.classList.remove("is-active"));
        card.classList.add("is-active");
        state.selectedSource = {
          kind: card.dataset.sourceKind,
          id: card.dataset.sourceId,
          w: parseInt(card.dataset.w, 10) || typicalW,
          h: parseInt(card.dataset.h, 10) || typicalH,
          label: card.querySelector(".atelier-source-label")?.textContent || card.dataset.sourceId,
          url: card.querySelector("img")?.getAttribute("src") || null,
        };
        dom.runVision.disabled = false;
        updateVisionCostEstimate();
      });
    });
  }
  wireSourceCards();

  function updateVisionCostEstimate() {
    if (!visionAvailable() || !state.selectedSource) {
      dom.visionCostEst.textContent = "free · deterministic";
      return;
    }
    dom.visionCostEst.textContent = "~$0.04 · vision";
  }
  dom.useVision.addEventListener("change", updateVisionCostEstimate);
  updateVisionCostEstimate();

  // ─────────── upload ───────────

  if (dom.uploadDrop) {
    dom.uploadDrop.addEventListener("click", () => dom.uploadInput.click());
    dom.uploadDrop.addEventListener("dragover", (e) => {
      e.preventDefault();
      dom.uploadDrop.classList.add("is-drag");
    });
    dom.uploadDrop.addEventListener("dragleave", () => {
      dom.uploadDrop.classList.remove("is-drag");
    });
    dom.uploadDrop.addEventListener("drop", (e) => {
      e.preventDefault();
      dom.uploadDrop.classList.remove("is-drag");
      const file = e.dataTransfer.files?.[0];
      if (file) handleUpload(file);
    });
  }
  if (dom.uploadInput) {
    dom.uploadInput.addEventListener("change", () => {
      if (dom.uploadInput.files?.[0]) handleUpload(dom.uploadInput.files[0]);
    });
  }

  async function handleUpload(file) {
    const fd = new FormData();
    fd.append("file", file);
    let res;
    try {
      res = await fetch(`${boardBase}/api/frame/upload`, {
        method: "POST", body: fd,
      });
    } catch (e) {
      alert("Upload failed: " + e);
      return;
    }
    if (!res.ok) {
      alert("Upload failed: " + (await res.text()));
      return;
    }
    const data = await res.json();
    addUploadCard(data);
  }

  function addUploadCard(data) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "atelier-source-card";
    card.dataset.sourceKind = "upload";
    card.dataset.sourceId = data.source_id;
    card.dataset.w = data.size[0];
    card.dataset.h = data.size[1];
    card.innerHTML = `
      <div class="atelier-source-thumb"><img src="${data.url}" alt=""></div>
      <span class="atelier-source-label">${escapeHtml(data.source_id)}</span>
      <span class="atelier-source-size">${data.size[0]} × ${data.size[1]} (uploaded)</span>
    `;
    dom.uploadList.appendChild(card);
    card.addEventListener("click", () => {
      root.querySelectorAll(".atelier-source-card.is-active")
        .forEach((c) => c.classList.remove("is-active"));
      card.classList.add("is-active");
      state.selectedSource = {
        kind: "upload",
        id: data.source_id,
        w: data.size[0],
        h: data.size[1],
        label: data.source_id,
        url: data.url,
      };
      dom.runVision.disabled = false;
      updateVisionCostEstimate();
    });
  }

  // ─────────── propose: run vision job ───────────

  dom.runVision.addEventListener("click", async () => {
    if (!state.selectedSource) return;
    dom.runVision.disabled = true;
    show(dom.visionStatus);
    dom.visionLog.innerHTML = "";
    dom.visionBar.style.right = "100%";
    dom.visionBar.classList.add("indeterminate");
    dom.visionSummary.textContent = "Analyzing source…";

    const fd = new FormData();
    fd.append("source_kind", state.selectedSource.kind);
    fd.append("source_id", state.selectedSource.id);
    fd.append("candidate_count", String(3));
    fd.append("use_vision", visionAvailable() ? "true" : "false");

    let res;
    try {
      res = await fetch(`${boardBase}/api/frame/propose`, { method: "POST", body: fd });
    } catch (e) {
      dom.visionSummary.textContent = "Vision request failed: " + e;
      dom.runVision.disabled = false;
      return;
    }
    if (!res.ok) {
      dom.visionSummary.textContent = "Vision request failed: " + (await res.text());
      dom.runVision.disabled = false;
      return;
    }
    const data = await res.json();
    state.proposalJobId = data.job_id;
  });

  function appendVisionLog(line) {
    const li = document.createElement("li");
    li.textContent = line;
    dom.visionLog.appendChild(li);
    dom.visionLog.scrollTop = dom.visionLog.scrollHeight;
  }

  // The job tray's SSE stream dispatches `bf:job-update` events for every
  // job change. Filter for our two job ids and react accordingly.
  window.addEventListener("bf:job-update", (e) => {
    const j = e.detail || {};
    if (state.proposalJobId && j.id === state.proposalJobId) {
      onProposeProgress(j);
    } else if (state.regenJobId && j.id === state.regenJobId) {
      onRegenProgress(j);
    }
  });

  function onProposeProgress(j) {
    if (j.status === "running" || j.status === "queued") {
      dom.visionBar.classList.toggle("indeterminate", !j.progress);
      if (j.progress) {
        dom.visionBar.classList.remove("indeterminate");
        dom.visionBar.style.right = `${(100 - j.progress * 100).toFixed(1)}%`;
      }
      const last = (j.log_tail || []).slice(-1)[0];
      if (last && (!dom.visionLog.lastElementChild || dom.visionLog.lastElementChild.textContent !== last)) {
        appendVisionLog(last);
      }
      dom.visionSummary.textContent = "Vision running…";
      return;
    }
    if (j.status === "done") {
      dom.visionBar.classList.remove("indeterminate");
      dom.visionBar.style.right = "0%";
      dom.visionSummary.textContent = "Proposals ready.";
      hydrateProposals(j.id);
      return;
    }
    if (j.status === "failed" || j.status === "killed") {
      dom.visionBar.classList.remove("indeterminate");
      dom.visionSummary.textContent =
        j.status === "killed" ? "Vision cancelled." : `Vision failed: ${j.error || "unknown error"}`;
      dom.runVision.disabled = false;
    }
  }

  async function hydrateProposals(jobId) {
    let res;
    try {
      res = await fetch(`${boardBase}/api/frame/proposals/${jobId}`);
    } catch (e) {
      dom.visionSummary.textContent = "Could not load proposals: " + e;
      return;
    }
    if (!res.ok) {
      dom.visionSummary.textContent = "Could not load proposals: " + (await res.text());
      return;
    }
    const data = await res.json();
    state.candidates = data.candidates || [];
    if (state.candidates.length === 0) {
      dom.visionSummary.textContent = "Vision returned no usable candidates.";
      dom.runVision.disabled = false;
      return;
    }
    enterRefinePhase(data);
  }

  // ─────────── refine ───────────

  function enterRefinePhase(manifest) {
    show(dom.refinePane);
    show(dom.commitPane);
    setActivePhase("refine");

    dom.candidateList.innerHTML = state.candidates.map((c, i) => `
      <li class="${i === 0 ? "is-active" : ""}" data-candidate-index="${c.index}">
        <div class="cand-thumb">${c.preview_url ? `<img src="${c.preview_url}" alt="">` : ""}</div>
        <div class="cand-meta">
          <span class="cand-title">candidate ${c.index + 1}${c.notes ? ` · ${escapeHtml(c.notes)}` : ""}</span>
          <span class="cand-score">${(c.score * 100).toFixed(0)}% · ${c.ring_px}px ring</span>
        </div>
      </li>
    `).join("");

    dom.candidateList.querySelectorAll("li").forEach((li) => {
      li.addEventListener("click", () => {
        const idx = parseInt(li.dataset.candidateIndex, 10);
        selectCandidate(idx);
      });
    });

    selectCandidate(state.candidates[0].index);

    if (manifest && manifest.model_id) {
      dom.metaModel.textContent = manifest.model_id;
    }
  }

  function selectCandidate(index) {
    const cand = state.candidates.find((c) => c.index === index);
    if (!cand) return;
    state.activeCandidateIndex = index;
    dom.candidateList.querySelectorAll("li").forEach((li) => {
      li.classList.toggle("is-active", parseInt(li.dataset.candidateIndex, 10) === index);
    });
    state.ringPx = clampRing(cand.ring_px || defaultRing);
    dom.ringSlider.value = String(state.ringPx);
    dom.ringValue.textContent = state.ringPx;

    if (state.selectedSource && state.selectedSource.url) {
      dom.stageSource.src = state.selectedSource.url;
    }
    if (cand.preview_url) {
      // Layer the candidate overlay PNG above the source. We use a single
      // <img> for now (the canvas is reserved for handle drag previews
      // once Phase B ships).
      dom.stageOverlay.style.backgroundImage = `url(${cand.preview_url})`;
      dom.stageOverlay.style.backgroundSize = "contain";
      dom.stageOverlay.style.backgroundRepeat = "no-repeat";
      dom.stageOverlay.style.backgroundPosition = "center";
    }
    dom.metaSource.textContent =
      `${state.selectedSource.kind}:${state.selectedSource.id}`;
    dom.metaSourceSize.textContent =
      `${state.selectedSource.w} × ${state.selectedSource.h}`;
    dom.metaScore.textContent = `${(cand.score * 100).toFixed(0)}%`;
    if (cand.model_id) dom.metaModel.textContent = cand.model_id;

    refreshPreview();
    refreshCommitEstimate();
  }

  function clampRing(v) {
    const n = parseInt(v, 10);
    if (!Number.isFinite(n)) return defaultRing;
    return Math.max(minRing, Math.min(maxRing, n));
  }

  let previewTimer = null;
  dom.ringSlider.addEventListener("input", () => {
    state.ringPx = clampRing(dom.ringSlider.value);
    dom.ringValue.textContent = state.ringPx;
    if (previewTimer) clearTimeout(previewTimer);
    previewTimer = setTimeout(refreshPreview, 120);
  });

  function refreshPreview() {
    if (!state.selectedSource) return;
    const url = `${boardBase}/api/frame/preview.png`
      + `?source_kind=${encodeURIComponent(state.selectedSource.kind)}`
      + `&source_id=${encodeURIComponent(state.selectedSource.id)}`
      + `&ring_px=${state.ringPx}`
      + `&w=${typicalW}&h=${typicalH}`
      + `&t=${Date.now()}`;
    dom.previewImg.src = url;
  }

  // Overlay toggle.
  dom.toggleOverlay.addEventListener("click", () => {
    state.showOverlay = !state.showOverlay;
    dom.toggleOverlay.classList.toggle("is-active", state.showOverlay);
    dom.toggleOverlay.textContent = state.showOverlay ? "Show overlay" : "Hide overlay";
    dom.stageOverlay.classList.toggle("is-hidden", !state.showOverlay);
  });

  // Re-run vision (Refine -> Propose loop).
  dom.rerunVision.addEventListener("click", () => {
    setActivePhase("propose");
    hide(dom.refinePane);
    hide(dom.commitPane);
    dom.runVision.disabled = false;
  });

  // Handles. For now they only show the stored candidate's bbox; full
  // drag-to-edit lands in Phase B (the ``frames_inference.fit_to_window``
  // helper is already in place server-side for that).
  function positionHandles() {
    if (!dom.stageHandles) return;
    const cand = state.candidates.find((c) => c.index === state.activeCandidateIndex);
    if (!cand || !state.selectedSource) {
      dom.stageHandles.style.display = "none";
      return;
    }
    dom.stageHandles.style.display = "";
    const box = dom.stageSource.getBoundingClientRect();
    const sw = state.selectedSource.w;
    const sh = state.selectedSource.h;
    if (!sw || !sh) return;
    const [x1, y1, x2, y2] = cand.bbox;
    const sx = box.width / sw;
    const sy = box.height / sh;

    const px = (x, y) => `translate(${(x * sx).toFixed(1)}px, ${(y * sy).toFixed(1)}px)`;
    const tl = dom.stageHandles.querySelector(".handle-tl");
    const tr = dom.stageHandles.querySelector(".handle-tr");
    const bl = dom.stageHandles.querySelector(".handle-bl");
    const br = dom.stageHandles.querySelector(".handle-br");
    if (tl) tl.style.transform = `${px(x1, y1)}`;
    if (tr) tr.style.transform = `${px(x2, y1)}`;
    if (bl) bl.style.transform = `${px(x1, y2)}`;
    if (br) br.style.transform = `${px(x2, y2)}`;
  }

  if (dom.stageSource) {
    dom.stageSource.addEventListener("load", positionHandles);
    window.addEventListener("resize", positionHandles);
  }

  // ─────────── commit ───────────

  function refreshCommitEstimate() {
    if (!nPanels) {
      dom.commitCostEst.textContent = "free · 0 panels";
      return;
    }
    if (!dom.regenPanels.checked) {
      dom.commitCostEst.textContent = "free · adopt only";
      return;
    }
    const perPanel = 0.022;     // mirror estimate_generate_one("panels")
    dom.commitCostEst.textContent = `${fmtMoney(perPanel * nPanels)} · ${nPanels} panel${nPanels === 1 ? "" : "s"}`;
  }
  dom.regenPanels.addEventListener("change", refreshCommitEstimate);
  refreshCommitEstimate();

  dom.commit.addEventListener("click", async () => {
    if (!state.selectedSource) return;
    dom.commit.disabled = true;
    const body = {
      source_kind: state.selectedSource.kind,
      source_id: state.selectedSource.id,
      ring_px: state.ringPx,
      job_id: state.proposalJobId || null,
      candidate_index: state.activeCandidateIndex !== null ? state.activeCandidateIndex : null,
      enable_after: dom.enableAfter.checked,
      regen_panels: dom.regenPanels.checked,
    };
    let res;
    try {
      res = await fetch(`${boardBase}/api/frame/commit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } catch (e) {
      alert("Commit failed: " + e);
      dom.commit.disabled = false;
      return;
    }
    if (!res.ok) {
      alert("Commit failed: " + (await res.text()));
      dom.commit.disabled = false;
      return;
    }
    const data = await res.json();
    if (data.regen_job_id) {
      state.regenJobId = data.regen_job_id;
      enterProgressPhase();
    } else {
      window.location.reload();
    }
  });

  // ─────────── approach D progress ───────────

  function enterProgressPhase() {
    setActivePhase("commit");
    dom.progressTitle.textContent = "Reapplying frame…";
    dom.progressSummary.textContent = `0 of ${nPanels} panels regenerated.`;
    dom.progressBar.classList.add("indeterminate");
    dom.progressBar.style.right = "100%";
    state.panelStates.clear();
    show(dom.progressOverlay);
    hide(dom.progressDone);
  }

  function onRegenProgress(j) {
    if (j.status === "queued" || j.status === "running") {
      const ratio = typeof j.progress === "number" ? j.progress : 0;
      if (ratio > 0) {
        dom.progressBar.classList.remove("indeterminate");
        dom.progressBar.style.right = `${(100 - ratio * 100).toFixed(1)}%`;
      }
      const tail = j.log_tail || [];
      const lastFew = tail.slice(-5);
      // Try to detect "panel:<id>" mentions in the log to flip cell state.
      lastFew.forEach((line) => {
        const m = line.match(/panel:([\w/_-]+)/);
        if (!m) return;
        const pid = m[1];
        const stateGuess = /skipped/.test(line) ? "skipped"
          : /FAIL/.test(line) ? "failed"
          : /promoted/.test(line) ? "done"
          : "running";
        markPanel(pid, stateGuess);
      });
      const done = Array.from(state.panelStates.values()).filter((s) => s === "done").length;
      dom.progressSummary.textContent = `${done} of ${nPanels} panels regenerated.`;
      return;
    }
    if (j.status === "done") {
      dom.progressBar.classList.remove("indeterminate");
      dom.progressBar.style.right = "0%";
      dom.progressTitle.textContent = "Frame applied.";
      dom.progressSummary.textContent =
        `Reapply complete — ${j.cost_actual ? "$" + j.cost_actual.toFixed(2) : "free"}.`;
      hide(dom.cancelRegen);
      show(dom.progressDone);
    } else if (j.status === "killed") {
      dom.progressTitle.textContent = "Reapply cancelled.";
      hide(dom.cancelRegen);
      show(dom.progressDone);
    } else if (j.status === "failed") {
      dom.progressTitle.textContent = "Reapply failed.";
      dom.progressSummary.textContent = j.error || "Unknown error — check the job tray.";
      hide(dom.cancelRegen);
      show(dom.progressDone);
    }
  }

  function markPanel(pid, st) {
    state.panelStates.set(pid, st);
    const cell = dom.progressGrid.querySelector(`[data-panel-id="${CSS.escape(pid)}"]`);
    if (!cell) return;
    cell.classList.remove("is-running", "is-done", "is-failed", "is-skipped");
    if (st === "running") cell.classList.add("is-running");
    if (st === "done") cell.classList.add("is-done");
    if (st === "failed") cell.classList.add("is-failed");
    if (st === "skipped") cell.classList.add("is-skipped");
    const label = cell.querySelector(".atelier-progress-state");
    if (label) label.textContent = st;
  }

  dom.cancelRegen.addEventListener("click", async () => {
    if (!state.regenJobId) return;
    dom.cancelRegen.disabled = true;
    try {
      await fetch(`/jobs/${state.regenJobId}/kill`, { method: "POST" });
    } catch (e) { /* ignore */ }
  });
  dom.progressDone.addEventListener("click", () => {
    window.location.reload();
  });

  // ─────────── disable on board ───────────

  if (dom.disable) {
    dom.disable.addEventListener("click", async () => {
      if (!confirm("Disable the frame on this board? Panels keep their art; only the rim overlay turns off.")) return;
      try {
        const r = await fetch(`${boardBase}/api/frame/disable`, { method: "POST" });
        if (!r.ok) {
          alert("Could not disable: " + (await r.text()));
          return;
        }
        window.location.reload();
      } catch (e) {
        alert("Network error: " + e);
      }
    });
  }
})();
