// Generation settings modal + intercept.
//
// Two responsibilities:
//   1) Drive the modal that lets the artist pick palette size / provider /
//      model. The same modal is used for first-time setup and edits.
//   2) Block paid generate actions when the board is not yet configured;
//      pop the modal first, then re-submit the original form on save.
//
// Why capture-phase submit listener: jobs.js attaches its own bubble-phase
// submit handler on every <form data-action>. We need to intercept before
// it fires so we can stop the request, open the modal, and only let it
// through once settings are saved.

(() => {
  const strip   = document.getElementById("gen-settings-strip");
  const modal   = document.getElementById("gen-modal");
  const summary = document.getElementById("gen-settings-summary");
  const editBtn = document.getElementById("gen-settings-edit");
  const form    = document.getElementById("gen-modal-form");
  const errEl   = document.getElementById("gen-modal-error");
  const pixellabHost = document.getElementById("gen-pixellab-options");
  if (!strip || !modal || !form) return;

  const boardId = strip.getAttribute("data-board-id");
  const API = `/b/${boardId}/api/generation`;

  let cache = null;            // last-known { settings, options }
  let pendingForm = null;      // form whose submit we paused, awaiting save

  // ── data load ────────────────────────────────────────────────────────

  async function fetchData() {
    const r = await fetch(API, { headers: { Accept: "application/json" } });
    if (!r.ok) throw new Error("Failed to load generation settings");
    cache = await r.json();
    return cache;
  }

  // ── modal open/close ─────────────────────────────────────────────────

  async function openModal({ forFirstRun = false } = {}) {
    try {
      if (!cache) await fetchData();
    } catch (e) {
      alert("Could not load generation settings: " + e.message);
      return;
    }
    populate(cache.settings, cache.options);
    errEl.hidden = true;
    errEl.textContent = "";
    modal.classList.add("is-open");
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");
    modal.dataset.firstRun = forFirstRun ? "1" : "0";
  }

  function closeModal() {
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("modal-open");
    pendingForm = null;
  }

  // ── populate / serialize ─────────────────────────────────────────────

  function populate(settings, options) {
    setRadio("palette_size", String(settings.palette_size));
    setRadio("provider", settings.provider);
    setRadio("openai_model", settings.openai.model);
    setRadio("openai_quality", settings.openai.quality);

    const presets = (options && options.pixellab_models) || [];
    pixellabHost.innerHTML = presets.map(p => `
      <label class="gen-radio">
        <input type="radio" name="pixellab_model" value="${p.id}">
        <span><strong>${escapeHtml(p.label)}</strong> &mdash; ${escapeHtml(p.description)}</span>
      </label>
    `).join("");
    setRadio("pixellab_model", settings.pixellab.model);

    syncProviderBlocks();
  }

  function setRadio(name, value) {
    form.querySelectorAll(`input[name="${name}"]`).forEach(input => {
      input.checked = (input.value === value);
    });
  }

  function readForm() {
    const fd = new FormData(form);
    return {
      palette_size: Number(fd.get("palette_size")),
      provider: fd.get("provider"),
      openai: {
        model: fd.get("openai_model"),
        quality: fd.get("openai_quality"),
      },
      pixellab: { model: fd.get("pixellab_model") },
    };
  }

  // Show only the model/quality block matching the picked provider.
  function syncProviderBlocks() {
    const picked = (form.querySelector('input[name="provider"]:checked') || {}).value;
    form.querySelectorAll("[data-provider-block]").forEach(block => {
      block.hidden = block.getAttribute("data-provider-block") !== picked;
    });
  }
  form.addEventListener("change", e => {
    if (e.target && e.target.name === "provider") syncProviderBlocks();
  });

  // ── save ─────────────────────────────────────────────────────────────

  async function save() {
    errEl.hidden = true;
    errEl.textContent = "";
    const body = readForm();
    if (!body.palette_size || !body.provider) {
      errEl.textContent = "Pick a palette size and provider.";
      errEl.hidden = false;
      return false;
    }
    try {
      const r = await fetch(API, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        let msg = "Save failed.";
        try { msg = (await r.json()).detail || msg; } catch (_) {}
        errEl.textContent = msg;
        errEl.hidden = false;
        return false;
      }
      const data = await r.json();
      cache = { ...(cache || {}), settings: data.settings };
      strip.setAttribute("data-configured", "true");
      summary.innerHTML = renderSummary(data.settings);
      return true;
    } catch (_) {
      errEl.textContent = "Network error.";
      errEl.hidden = false;
      return false;
    }
  }

  function renderSummary(s) {
    const provider = s.provider === "openai"
      ? `OpenAI &middot; ${escapeHtml(s.openai.model)} &middot; ${escapeHtml(s.openai.quality)} quality`
      : `PixelLab &middot; ${escapeHtml(s.pixellab.model)}`;
    return `${provider} &middot; ${s.palette_size} colors`;
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // ── DOM events ──────────────────────────────────────────────────────

  editBtn.addEventListener("click", () => openModal({ forFirstRun: false }));
  modal.querySelectorAll("[data-close-modal]").forEach(el =>
    el.addEventListener("click", closeModal));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && modal.classList.contains("is-open")) closeModal();
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const ok = await save();
    if (!ok) return;
    closeModal();
    // If we paused a generate form, run it now.
    if (pendingForm) {
      const f = pendingForm;
      pendingForm = null;
      // Mark so our capture handler doesn't intercept again.
      f.dataset.genCleared = "1";
      if (typeof f.requestSubmit === "function") f.requestSubmit();
      else f.submit();
    }
  });

  // ── intercept paid generate actions when not configured ─────────────

  const PAID_ACTION_RE = /\/actions\/(?:generate(?:-missing)?\/(?:spaces|panels|centerpiece|all)|analyze)$/;

  document.addEventListener("submit", (e) => {
    const f = e.target;
    if (!(f instanceof HTMLFormElement)) return;
    if (!f.matches("form[data-action]")) return;
    if (f.dataset.genCleared === "1") return;
    const action = (f.action || "").replace(/\?.*$/, "");
    if (!PAID_ACTION_RE.test(action)) return;
    if (strip.getAttribute("data-configured") === "true") return;

    e.preventDefault();
    e.stopImmediatePropagation();
    pendingForm = f;
    openModal({ forFirstRun: true });
  }, /* useCapture */ true);
})();
