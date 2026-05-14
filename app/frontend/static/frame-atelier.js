// Frame Atelier — three-phase Propose / Refine / Commit + Approach D batch.
//
// Uses fetch + the existing `bf:job-update` events that jobs.js dispatches
// from /events/jobs SSE; we never open a second EventSource here.
//
// Phases:
//   1. Propose — pick a source (panel / upload), POST /api/frame/propose,
//      consume vision-job progress, then GET /api/frame/proposals/<job_id> to
//      hydrate the candidate list.
//   2. Refine — overlay + draggable corner handles → POST /api/frame/refine
//      (``frames_inference.fit_to_window``); ring slider + preview at typical size.
//   3. Commit — POST /api/frame/commit with the selected candidate +
//      ring_px, optionally enable + enqueue frame.reapply (Approach D)
//      or frame.reapply_one for the source panel only (then redirect to board),
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
  const batchUsd = parseFloat(root.dataset.reapplyBatchUsd || "0");
  const batchSec = parseInt(root.dataset.reapplyBatchSec || "0", 10);
  const singleUsd = parseFloat(root.dataset.reapplySingleUsd || "0");
  const singleSec = parseInt(root.dataset.reapplySingleSec || "0", 10);

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
    bboxOutline: root.querySelector("[data-bbox-outline]"),
    stageFrame: root.querySelector(".atelier-stage-frame"),
    stageHandles: root.querySelector("[data-stage-handles]"),
    toggleOverlay: root.querySelector("[data-toggle-overlay]"),
    maskDiagnostic: root.querySelector("[data-mask-diagnostic]"),
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
    regenSingleWrap: root.querySelector("[data-regen-single-wrap]"),
    regenSinglePanel: root.querySelector("[data-regen-single-panel]"),
    commit: root.querySelector("[data-commit]"),
    commitCostEst: root.querySelector("[data-commit-cost-est]"),
    progressTitle: root.querySelector("[data-progress-title]"),
    progressSummary: root.querySelector("[data-progress-summary]"),
    progressBar: root.querySelector("[data-progress-bar]"),
    progressGrid: root.querySelector("[data-progress-grid]"),
    progressEyebrow: root.querySelector("[data-progress-eyebrow]"),
    progressCard: root.querySelector("[data-progress-card]"),
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
    regenRedirectToBoard: false,
    panelStates: new Map(),      // panel_id -> "queued" | "running" | "done" | "failed"
    overlayUrl: null,
    dragSession: null,           // { handle, opp, startBBox, previewUrl, previewRingPx }
  };

  if (dom.toggleOverlay && state.showOverlay) {
    dom.toggleOverlay.textContent = "Hide rim/hole overlay";
  }

  const fmtMoney = (n) => {
    if (!n) return "free";
    if (n < 0.01) return "$" + n.toFixed(4);
    return "$" + n.toFixed(2);
  };

  /** Server seconds → ``est 5 min`` / ``est 45s`` (matches commit-adopt pill format). */
  function fmtEstDuration(sec) {
    const s = Math.max(0, parseInt(sec, 10) || 0);
    if (s === 0) return "est 0s";
    if (s < 90) return `est ${s}s`;
    const min = Math.ceil(s / 60);
    return `est ${min} min`;
  }

  /** ``$0.54 total · est 5 min`` — or ``free · est …`` when cost is zero. */
  function commitEstLine(usd, sec) {
    const time = fmtEstDuration(sec);
    const money = fmtMoney(usd);
    if (money === "free") {
      return `free · ${time}`;
    }
    return `${money} total · ${time}`;
  }

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
      syncRegenSingleOption();
    });
  });

  function syncRegenSingleOption() {
    if (!dom.regenSingleWrap || !dom.regenSinglePanel) return;
    const isPanel = Boolean(
      state.selectedSource && state.selectedSource.kind === "functional"
        && state.activeTab === "panel",
    );
    dom.regenSingleWrap.hidden = !isPanel;
    if (!isPanel) dom.regenSinglePanel.checked = false;
  }

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
        syncRegenSingleOption();
      });
    });
  }
  wireSourceCards();
  syncRegenSingleOption();

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
      syncRegenSingleOption();
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
    hide(dom.visionStatus);
    dom.runVision.disabled = false;
    dom.visionBar.classList.remove("indeterminate");
    dom.visionBar.style.right = "100%";

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
      paintOverlayFromUrl(cand.preview_url);
    }
    dom.metaSource.textContent =
      `${state.selectedSource.kind}:${state.selectedSource.id}`;
    dom.metaSourceSize.textContent =
      `${state.selectedSource.w} × ${state.selectedSource.h}`;
    dom.metaScore.textContent = `${(cand.score * 100).toFixed(0)}%`;
    if (cand.model_id) dom.metaModel.textContent = cand.model_id;

    refreshPreview();
    refreshCommitEstimate();
    positionHandles();
  }

  function clampRing(v) {
    const n = parseInt(v, 10);
    if (!Number.isFinite(n)) return defaultRing;
    return Math.max(minRing, Math.min(maxRing, n));
  }

  let previewTimer = null;
  let ringOverlayTimer = null;
  /** Bumped when ring slider schedules sync or user grabs a handle — stale async completes ignore. */
  let ringSyncToken = 0;

  function mergeRefineResponse(data) {
    const cand = state.candidates.find((c) => c.index === state.activeCandidateIndex);
    if (!cand || !data.bbox) return;
    cand.bbox = data.bbox;
    if (typeof data.ring_px === "number") {
      cand.ring_px = data.ring_px;
      state.ringPx = clampRing(data.ring_px);
      dom.ringSlider.value = String(state.ringPx);
      dom.ringValue.textContent = state.ringPx;
    }
    if (data.notes != null) cand.notes = data.notes;
    if (data.preview_url) {
      cand.preview_url = data.preview_url;
      paintOverlayFromUrl(data.preview_url);
    }
    refreshCandidateListThumb();
    refreshPreview();
  }

  async function postRefine(bbox, { quiet } = { quiet: false }) {
    if (
      state.proposalJobId == null
      || state.activeCandidateIndex === null
      || !state.selectedSource
    ) {
      return null;
    }
    let res;
    try {
      res = await fetch(`${boardBase}/api/frame/refine`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: state.proposalJobId,
          candidate_index: state.activeCandidateIndex,
          bbox,
          source_kind: state.selectedSource.kind,
          source_id: state.selectedSource.id,
          ring_px: state.ringPx,
        }),
      });
    } catch (e) {
      if (!quiet) alert("Could not save: " + e);
      return null;
    }
    if (!res.ok) {
      const errText = await res.text();
      if (!quiet) {
        alert("Could not save: " + errText);
      } else {
        dom.ringValue.setAttribute("title", errText.slice(0, 200) || "Ring refine failed");
      }
      return null;
    }
    dom.ringValue.removeAttribute("title");
    return res.json();
  }

  async function runRingOverlaySync(expectedToken) {
    if (state.dragSession) return;
    if (state.proposalJobId == null || state.activeCandidateIndex === null) return;
    const cand = state.candidates.find((c) => c.index === state.activeCandidateIndex);
    if (!cand || !cand.bbox) return;
    if (dom.stageFrame) dom.stageFrame.classList.add("is-ring-syncing");
    try {
      const data = await postRefine(cand.bbox, { quiet: true });
      if (expectedToken !== ringSyncToken) return;
      if (data) mergeRefineResponse(data);
    } finally {
      if (expectedToken === ringSyncToken && dom.stageFrame) {
        dom.stageFrame.classList.remove("is-ring-syncing");
      }
    }
  }

  function scheduleRingOverlaySync() {
    const token = ++ringSyncToken;
    if (ringOverlayTimer) clearTimeout(ringOverlayTimer);
    ringOverlayTimer = setTimeout(() => {
      ringOverlayTimer = null;
      runRingOverlaySync(token);
    }, 380);
  }

  function cancelPendingRingOverlaySync() {
    ringSyncToken++;
    if (ringOverlayTimer) {
      clearTimeout(ringOverlayTimer);
      ringOverlayTimer = null;
    }
    if (dom.stageFrame) dom.stageFrame.classList.remove("is-ring-syncing");
  }

  dom.ringSlider.addEventListener("input", () => {
    state.ringPx = clampRing(dom.ringSlider.value);
    dom.ringValue.textContent = state.ringPx;
    if (previewTimer) clearTimeout(previewTimer);
    previewTimer = setTimeout(refreshPreview, 120);
    scheduleRingOverlaySync();
  });

  let previewFetchGen = 0;

  function refreshPreview() {
    if (!state.selectedSource || !dom.previewImg) return;
    const gen = ++previewFetchGen;
    let q = `?source_kind=${encodeURIComponent(state.selectedSource.kind)}`
      + `&source_id=${encodeURIComponent(state.selectedSource.id)}`
      + `&ring_px=${state.ringPx}`
      + `&w=${typicalW}&h=${typicalH}`
      + `&t=${Date.now()}`;
    if (state.proposalJobId && state.activeCandidateIndex !== null) {
      q += `&job_id=${encodeURIComponent(state.proposalJobId)}`
        + `&candidate_index=${encodeURIComponent(state.activeCandidateIndex)}`;
    }
    const bboxCand =
      state.activeCandidateIndex !== null
        ? state.candidates.find((c) => c.index === state.activeCandidateIndex)
        : null;
    if (
      bboxCand && Array.isArray(bboxCand.bbox) && bboxCand.bbox.length === 4
    ) {
      const [bx1, by1, bx2, by2] = bboxCand.bbox;
      q += `&x1=${encodeURIComponent(bx1)}&y1=${encodeURIComponent(by1)}`
        + `&x2=${encodeURIComponent(bx2)}&y2=${encodeURIComponent(by2)}`;
    }
    if (dom.maskDiagnostic && dom.maskDiagnostic.checked) {
      q += "&mask_diagnostic=1";
    }
    const url = `${boardBase}/api/frame/preview.png${q}`;
    fetch(url, { cache: "no-store", credentials: "same-origin" })
      .then((res) => {
        if (gen !== previewFetchGen) return null;
        return res.ok ? res.blob() : null;
      })
      .then((blob) => {
        if (!blob || gen !== previewFetchGen) return;
        const prev = dom.previewImg.dataset.objectUrl;
        if (prev) URL.revokeObjectURL(prev);
        const ou = URL.createObjectURL(blob);
        dom.previewImg.dataset.objectUrl = ou;
        dom.previewImg.src = ou;
      })
      .catch(() => {});
  }

  if (dom.maskDiagnostic) {
    dom.maskDiagnostic.addEventListener("change", () => refreshPreview());
  }

  // Overlay toggle.
  dom.toggleOverlay.addEventListener("click", () => {
    state.showOverlay = !state.showOverlay;
    dom.toggleOverlay.classList.toggle("is-active", state.showOverlay);
    dom.toggleOverlay.textContent = state.showOverlay ? "Hide rim/hole overlay" : "Show rim/hole overlay";
    dom.stageOverlay.classList.toggle("is-hidden", !state.showOverlay);
  });

  // Re-run vision (Refine -> Propose loop).
  dom.rerunVision.addEventListener("click", () => {
    setActivePhase("propose");
    hide(dom.refinePane);
    hide(dom.commitPane);
    dom.runVision.disabled = false;
  });

  function syncOverlayCanvasLayout() {
    if (!dom.stageOverlay || !dom.stageSource || !dom.stageFrame) return;
    const fr = dom.stageFrame.getBoundingClientRect();
    const ir = dom.stageSource.getBoundingClientRect();
    dom.stageOverlay.style.left = `${ir.left - fr.left}px`;
    dom.stageOverlay.style.top = `${ir.top - fr.top}px`;
    dom.stageOverlay.style.width = `${ir.width}px`;
    dom.stageOverlay.style.height = `${ir.height}px`;
  }

  function paintOverlayFromUrl(url) {
    state.overlayUrl = url;
    if (!url || !dom.stageOverlay || !dom.stageSource) return;
    const canvas = dom.stageOverlay;
    if (!canvas.getContext) return;
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      syncOverlayCanvasLayout();
      const rect = dom.stageSource.getBoundingClientRect();
      const w = rect.width;
      const h = rect.height;
      const dpr = window.devicePixelRatio || 1;
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      ctx.drawImage(img, 0, 0, w, h);
      positionHandles();
    };
    img.onerror = () => {};
    img.src = url;
  }

  function snapCoord(v) {
    const g = dom.snapToGrid && dom.snapToGrid.checked ? 4 : 1;
    return Math.round(v / g) * g;
  }

  function clientToSource(clientX, clientY) {
    const ir = dom.stageSource.getBoundingClientRect();
    const sw = state.selectedSource.w;
    const sh = state.selectedSource.h;
    return {
      x: ((clientX - ir.left) / ir.width) * sw,
      y: ((clientY - ir.top) / ir.height) * sh,
    };
  }

  function oppositeCorner(handle, bbox) {
    const [x1, y1, x2, y2] = bbox;
    if (handle === "tl") return [x2, y2];
    if (handle === "tr") return [x1, y2];
    if (handle === "bl") return [x2, y1];
    return [x1, y1];
  }

  function bboxForHandleDrag(handle, nx, ny, opp, sw, sh) {
    const rp = state.ringPx;
    const minW = Math.min(2 * rp + 4, sw);
    const minH = Math.min(2 * rp + 4, sh);
    const [ox, oy] = opp;
    let x1; let y1; let x2; let y2;
    if (handle === "tl") {
      x2 = ox; y2 = oy;
      x1 = snapCoord(Math.min(nx, x2 - minW));
      y1 = snapCoord(Math.min(ny, y2 - minH));
    } else if (handle === "tr") {
      x1 = ox; y2 = oy;
      x2 = snapCoord(Math.max(nx, x1 + minW));
      y1 = snapCoord(Math.min(ny, y2 - minH));
    } else if (handle === "bl") {
      x2 = ox; y1 = oy;
      x1 = snapCoord(Math.min(nx, x2 - minW));
      y2 = snapCoord(Math.max(ny, y1 + minH));
    } else {
      x1 = ox; y1 = oy;
      x2 = snapCoord(Math.max(nx, x1 + minW));
      y2 = snapCoord(Math.max(ny, y1 + minH));
    }
    x1 = Math.max(0, Math.min(sw - minW, x1));
    y1 = Math.max(0, Math.min(sh - minH, y1));
    x2 = Math.max(x1 + minW, Math.min(sw, x2));
    y2 = Math.max(y1 + minH, Math.min(sh, y2));
    return [
      Math.round(x1), Math.round(y1), Math.round(x2), Math.round(y2),
    ];
  }

  async function persistRefineBBox(bbox) {
    const data = await postRefine(bbox, { quiet: false });
    if (!data) return false;
    mergeRefineResponse(data);
    return true;
  }

  function refreshCandidateListThumb() {
    const cand = state.candidates.find((c) => c.index === state.activeCandidateIndex);
    if (!cand || !cand.preview_url) return;
    const li = dom.candidateList.querySelector(`li[data-candidate-index="${cand.index}"]`);
    const thumb = li && li.querySelector(".cand-thumb img");
    if (thumb) thumb.src = cand.preview_url;
  }

  function onHandlePointerMove(ev) {
    const sess = state.dragSession;
    if (!sess || !state.selectedSource) return;
    const sw = state.selectedSource.w;
    const sh = state.selectedSource.h;
    const { x, y } = clientToSource(ev.clientX, ev.clientY);
    const next = bboxForHandleDrag(sess.handle, x, y, sess.opp, sw, sh);
    const cand = state.candidates.find((c) => c.index === state.activeCandidateIndex);
    if (cand) cand.bbox = next;
    positionHandles();
  }

  async function onHandlePointerUp(ev) {
    const sess = state.dragSession;
    state.dragSession = null;
    try {
      ev.currentTarget.releasePointerCapture(ev.pointerId);
    } catch (_e) {
      /* ignore */
    }
    ev.currentTarget.removeEventListener("pointermove", onHandlePointerMove);
    ev.currentTarget.removeEventListener("pointerup", onHandlePointerUp);
    ev.currentTarget.removeEventListener("pointercancel", onHandlePointerUp);

    if (!sess) return;
    const cand = state.candidates.find((c) => c.index === state.activeCandidateIndex);
    if (!cand) return;
    const same = cand.bbox.every((v, i) => v === sess.startBBox[i]);
    if (same) return;
    dom.stageHandles.classList.add("is-busy");
    const ok = await persistRefineBBox(cand.bbox);
    dom.stageHandles.classList.remove("is-busy");
    if (!ok) {
      cand.bbox = sess.startBBox;
      state.ringPx = sess.previewRingPx;
      dom.ringSlider.value = String(state.ringPx);
      dom.ringValue.textContent = state.ringPx;
      if (sess.previewUrl) paintOverlayFromUrl(sess.previewUrl);
      positionHandles();
    }
  }

  function onHandlePointerDown(ev) {
    if (ev.button !== 0) return;
    const handle = ev.currentTarget.dataset.handle;
    const cand = state.candidates.find((c) => c.index === state.activeCandidateIndex);
    if (!cand || !state.selectedSource || !handle) return;
    ev.preventDefault();
    cancelPendingRingOverlaySync();
    const bbox = [...cand.bbox];
    const opp = oppositeCorner(handle, bbox);
    state.dragSession = {
      handle,
      opp,
      startBBox: bbox,
      previewUrl: cand.preview_url,
      previewRingPx: state.ringPx,
    };
    ev.currentTarget.setPointerCapture(ev.pointerId);
    ev.currentTarget.addEventListener("pointermove", onHandlePointerMove);
    ev.currentTarget.addEventListener("pointerup", onHandlePointerUp);
    ev.currentTarget.addEventListener("pointercancel", onHandlePointerUp);
  }

  function wireHandleDrag() {
    if (!dom.stageHandles) return;
    dom.stageHandles.querySelectorAll(".handle").forEach((el) => {
      el.addEventListener("pointerdown", onHandlePointerDown);
    });
  }

  /** Corner handles — drag to resize bbox; persisted via ``POST /api/frame/refine``. */
  function positionHandles() {
    if (!dom.stageHandles || !dom.stageFrame || !dom.stageSource) return;
    const cand = state.candidates.find((c) => c.index === state.activeCandidateIndex);
    if (!cand || !state.selectedSource) {
      dom.stageHandles.style.display = "none";
      if (dom.bboxOutline) dom.bboxOutline.style.display = "none";
      return;
    }
    dom.stageHandles.style.display = "";
    syncOverlayCanvasLayout();
    const fr = dom.stageFrame.getBoundingClientRect();
    const ir = dom.stageSource.getBoundingClientRect();
    const offLeft = ir.left - fr.left;
    const offTop = ir.top - fr.top;
    const sw = state.selectedSource.w;
    const sh = state.selectedSource.h;
    if (!sw || !sh) {
      if (dom.bboxOutline) dom.bboxOutline.style.display = "none";
      return;
    }
    const [x1, y1, x2, y2] = cand.bbox;
    const sx = ir.width / sw;
    const sy = ir.height / sh;

    const px = (x, y) =>
      `translate(${(offLeft + x * sx).toFixed(1)}px, ${(offTop + y * sy).toFixed(1)}px)`;
    const tl = dom.stageHandles.querySelector(".handle-tl");
    const tr = dom.stageHandles.querySelector(".handle-tr");
    const bl = dom.stageHandles.querySelector(".handle-bl");
    const br = dom.stageHandles.querySelector(".handle-br");
    if (tl) tl.style.transform = `${px(x1, y1)}`;
    if (tr) tr.style.transform = `${px(x2, y1)}`;
    if (bl) bl.style.transform = `${px(x1, y2)}`;
    if (br) br.style.transform = `${px(x2, y2)}`;

    /* Dashed outline is only the axis-aligned *crop window*, not the rim silhouette.
       When the pink/cyan vision overlay is on, hide it so the organic masks read clearly. */
    if (dom.bboxOutline) {
      if (state.showOverlay) {
        dom.bboxOutline.style.display = "none";
      } else {
        dom.bboxOutline.style.display = "block";
        dom.bboxOutline.style.left = `${offLeft + x1 * sx}px`;
        dom.bboxOutline.style.top = `${offTop + y1 * sy}px`;
        dom.bboxOutline.style.width = `${Math.max(0, (x2 - x1) * sx)}px`;
        dom.bboxOutline.style.height = `${Math.max(0, (y2 - y1) * sy)}px`;
      }
    }
  }

  wireHandleDrag();

  if (dom.stageSource) {
    dom.stageSource.addEventListener("load", () => {
      if (state.overlayUrl) paintOverlayFromUrl(state.overlayUrl);
      else positionHandles();
    });
    window.addEventListener("resize", () => {
      if (state.overlayUrl) paintOverlayFromUrl(state.overlayUrl);
      else positionHandles();
    });
  }

  if (dom.snapToGrid) {
    dom.snapToGrid.addEventListener("change", () => {
      if (state.dragSession) return;
      positionHandles();
    });
  }

  // ─────────── commit ───────────

  function refreshCommitEstimate() {
    if (!nPanels) {
      dom.commitCostEst.textContent = "free · —";
      return;
    }
    if (dom.regenSinglePanel && dom.regenSinglePanel.checked) {
      dom.commitCostEst.textContent = commitEstLine(singleUsd, singleSec);
      return;
    }
    if (!dom.regenPanels.checked) {
      dom.commitCostEst.textContent = "free · adopt only";
      return;
    }
    dom.commitCostEst.textContent = commitEstLine(batchUsd, batchSec);
  }
  dom.regenPanels.addEventListener("change", () => {
    if (dom.regenPanels.checked && dom.regenSinglePanel) dom.regenSinglePanel.checked = false;
    refreshCommitEstimate();
  });
  if (dom.regenSinglePanel) {
    dom.regenSinglePanel.addEventListener("change", () => {
      if (dom.regenSinglePanel.checked) dom.regenPanels.checked = false;
      refreshCommitEstimate();
    });
  }
  refreshCommitEstimate();

  dom.commit.addEventListener("click", async () => {
    if (!state.selectedSource) return;
    dom.commit.disabled = true;
    const singlePanel =
      Boolean(dom.regenSinglePanel && dom.regenSinglePanel.checked)
      && state.selectedSource && state.selectedSource.kind === "functional";
    const body = {
      source_kind: state.selectedSource.kind,
      source_id: state.selectedSource.id,
      ring_px: state.ringPx,
      job_id: state.proposalJobId || null,
      candidate_index: state.activeCandidateIndex !== null ? state.activeCandidateIndex : null,
      enable_after: dom.enableAfter.checked,
      regen_panels: dom.regenPanels.checked && !singlePanel,
      regen_single_panel_id: singlePanel ? state.selectedSource.id : null,
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
      state.regenRedirectToBoard = Boolean(data.regen_single_panel);
      enterProgressPhase();
    } else {
      window.location.reload();
    }
  });

  // ─────────── approach D progress ───────────

  /** Worker logs use ``panels:<id>`` (draw_cell); skip/fail lines use ``panel:<id>``. */
  function inferPanelCellFromLine(line) {
    const t = String(line || "").trim();
    let m = t.match(/^promoted\s+\S+\s+->\s+live\/panels\/([\w/_-]+)/);
    if (m) return { pid: m[1], st: "done" };
    m = t.match(/^FAIL\s+panels\/([\w/_-]+)/);
    if (m) return { pid: m[1], st: "failed" };
    m = t.match(/^panel:([\w/_-]+)\s+FAILED/i);
    if (m) return { pid: m[1], st: "failed" };
    m = t.match(/^skip\s+panel:([\w/_-]+)/);
    if (m) return { pid: m[1], st: "skipped" };
    m = t.match(/^panel:([\w/_-]+)\s+skipped/i);
    if (m) return { pid: m[1], st: "skipped" };
    m = t.match(/^panel:([\w/_-]+)\s+\(skipped\)/i);
    if (m) return { pid: m[1], st: "skipped" };
    m = t.match(/^panels:([\w/_-]+)\s+\(\d+\/\d+\)/);
    if (m) return { pid: m[1], st: "running" };
    m = t.match(/^draw\s+panels\/([\w/_-]+)\b/);
    if (m) return { pid: m[1], st: "running" };
    return null;
  }

  function panelCellLabel(st) {
    switch (st) {
      case "waiting": return "Waiting…";
      case "running": return "In progress";
      case "done": return "Done";
      case "skipped": return "Skipped";
      case "failed": return "Failed";
      default: return st;
    }
  }

  function refreshBatchSummary(j) {
    const done = Array.from(state.panelStates.values()).filter((s) => s === "done").length;
    const running = Array.from(state.panelStates.values()).filter((s) => s === "running").length;
    const failed = Array.from(state.panelStates.values()).filter((s) => s === "failed").length;
    const pct = typeof j.progress === "number" ? Math.round(j.progress * 100) : null;
    const touched = Array.from(state.panelStates.values()).some((s) => s !== "waiting");
    if (!touched && (j.status === "queued" || j.status === "running")) {
      dom.progressSummary.textContent = pct != null && pct > 0
        ? `Starting batch… ${pct}%`
        : "Starting batch…";
      return;
    }
    const parts = [`${done} of ${nPanels} done`];
    if (running) parts.push(`${running} in progress`);
    if (failed) parts.push(`${failed} failed`);
    dom.progressSummary.textContent = parts.join(" · ");
  }

  function resetProgressGridWaiting() {
    if (!dom.progressGrid || state.regenRedirectToBoard) return;
    dom.progressGrid.querySelectorAll("[data-panel-id]").forEach((cell) => {
      const pid = cell.getAttribute("data-panel-id");
      if (!pid) return;
      state.panelStates.set(pid, "waiting");
      cell.classList.remove("is-running", "is-done", "is-failed", "is-skipped");
      const label = cell.querySelector(".atelier-progress-state");
      if (label) label.textContent = panelCellLabel("waiting");
    });
  }

  function enterProgressPhase() {
    setActivePhase("commit");
    const single = state.regenRedirectToBoard;
    dom.progressTitle.textContent = single ? "Regenerating panel…" : "Reapplying frame…";
    dom.progressSummary.textContent = single
      ? "Applying the new frame to this panel…"
      : "Starting batch…";
    dom.progressBar.classList.add("indeterminate");
    dom.progressBar.style.right = "100%";
    state.panelStates.clear();
    if (dom.progressEyebrow) dom.progressEyebrow.textContent = single ? "One panel" : "Approach D";
    if (dom.progressCard) dom.progressCard.classList.toggle("is-single-regen", Boolean(single));
    if (dom.progressGrid) dom.progressGrid.hidden = Boolean(single);
    if (!single) resetProgressGridWaiting();
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
      if (state.regenRedirectToBoard) {
        dom.progressSummary.textContent = "Applying the new frame to this panel…";
        return;
      }
      const tail = j.log_tail || [];
      tail.forEach((line) => {
        const hit = inferPanelCellFromLine(line);
        if (hit) markPanel(hit.pid, hit.st);
      });
      refreshBatchSummary(j);
      return;
    }
    if (j.status === "done") {
      if (state.regenRedirectToBoard) {
        const home = boardBase ? `${boardBase.replace(/\/?$/, "")}/` : "/";
        window.location.href = home;
        return;
      }
      dom.progressBar.classList.remove("indeterminate");
      dom.progressBar.style.right = "0%";
      dom.progressTitle.textContent = "Frame applied.";
      dom.progressSummary.textContent =
        `Reapply complete — ${j.cost_actual ? "$" + j.cost_actual.toFixed(2) : "free"}.`;
      hide(dom.cancelRegen);
      show(dom.progressDone);
    } else if (j.status === "killed") {
      dom.progressTitle.textContent = "Regeneration cancelled.";
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
    const cell = dom.progressGrid && dom.progressGrid.querySelector(`[data-panel-id="${CSS.escape(pid)}"]`);
    if (!cell) return;
    cell.classList.remove("is-running", "is-done", "is-failed", "is-skipped");
    if (st === "running") cell.classList.add("is-running");
    if (st === "done") cell.classList.add("is-done");
    if (st === "failed") cell.classList.add("is-failed");
    if (st === "skipped") cell.classList.add("is-skipped");
    const label = cell.querySelector(".atelier-progress-state");
    if (label) label.textContent = panelCellLabel(st);
    if (st === "done") {
      const img = cell.querySelector(".atelier-progress-thumb img");
      if (img && img.src) {
        try {
          const u = new URL(img.src, window.location.href);
          u.searchParams.set("t", String(Date.now()));
          img.src = u.toString();
        } catch {
          const base = img.src.split("?")[0];
          img.src = `${base}?t=${Date.now()}`;
        }
      }
    }
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
